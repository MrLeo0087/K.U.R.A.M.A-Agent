"""Safety gate for tool calls: safe -> run, confirm -> needs the user's yes, blocked -> refuse.

Every call (allowed, denied, blocked, error) is written to the SQLite action log
(store.log_tool with safety + outcome). Confirmation is pluggable per mode: terminal input in
text mode, a spoken yes/no hook in voice mode; anything unanswered is denied.
"""
from __future__ import annotations

import contextvars
import logging
import re
import select
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from jarvis.core import config, registry, store
from jarvis.core.registry import ToolResult
from jarvis.core.shellcheck import check_shell  # noqa: F401  (re-exported)

log = logging.getLogger("jarvis.safety")

ConfirmFn = Callable[[str], bool]

YES_WORDS = {
    "y", "yes", "yeah", "yea", "yep", "yup", "sure", "ok", "okay", "confirm", "confirmed", "affirmative",
    "proceed", "haan", "han", "haa", "ha", "hā", "ho", "hajur", "huncha", "hunchha", "hunxa",
    "theek", "thik", "ji", "jee", "हो", "हाँ", "हां", "हा", "जी", "हजुर", "हुन्छ", "ठीक",
}
YES_PHRASES = ("do it", "go ahead", "of course", "run it", "just run", "go for it", "please do", "yes please",
               "make it", "create it", "create a tool", "make a tool", "make one", "carry on", "continue",
               "absolutely", "definitely", "why not", "sounds good", "let's do", "lets do", "gara", "garnus",
               "gardinus", "karo", "kar do", "kardo", "chalau", "chala do", "चलाउ", "गर", "करो", "कर दो")
NO_WORDS = {
    "n", "no", "nope", "nah", "don't", "dont", "cancel", "stop", "abort", "deny", "negative", "never",
    "nahi", "nahin", "nai", "mat", "hoina", "haina", "hoeena", "नहीं", "नही", "ना", "मत", "होइन",
    "हैन", "होईन", "नाइ", "पर्दैन",
}
_TOKEN = re.compile(r"[^\s,.!?।॥;:\"'()]+")


def parse_yes_no(text: str | None) -> bool | None:
    """True for yes, False for no, None if unclear. "No" wins over "yes" when both appear."""
    if not text:
        return None
    low = text.strip().lower()
    tokens = set(_TOKEN.findall(low))
    if tokens & NO_WORDS or "don't" in low or "do not" in low:
        return False
    if tokens & YES_WORDS or any(p in low for p in YES_PHRASES):
        return True
    return None


# --- confirmation hooks ---
def deny_all(prompt: str) -> bool:
    return False


def text_confirm(prompt: str, timeout: float | None = None) -> bool:
    """Ask on the terminal; no answer within the timeout (or EOF) means no."""
    timeout = config.CONFIRM_TIMEOUT_S if timeout is None else timeout
    print(f"\n[confirm] {prompt} [y/N] ", end="", flush=True)
    try:
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if not ready:
            print("(timed out: no)")
            return False
        line = sys.stdin.readline()
    except (OSError, ValueError, TypeError):  # stdin without fileno (tests, IDE consoles)
        try:
            line = input()
        except (EOFError, OSError):
            return False
    if not line:
        return False
    return parse_yes_no(line) is True


_HOOKS: dict[str, ConfirmFn] = {"text": text_confirm}


def set_confirm_hook(mode: str, fn: ConfirmFn | None) -> None:
    if fn is None:
        _HOOKS.pop(mode, None)
    else:
        _HOOKS[mode] = fn


def get_confirm(mode: str) -> ConfirmFn:
    return _HOOKS.get(mode, deny_all)


# --- per-call context (P7c): tools that ask their own questions (toolsmith, file writes) ---
_CTX: contextvars.ContextVar[dict] = contextvars.ContextVar("jarvis_tool_ctx", default={})


def context() -> dict:
    """The running tool call's context: confirm fn, user_text, lang, mode (empty outside execute)."""
    return _CTX.get()


_asking = [0]  # yes/no questions waiting right now, in ANY tool thread (nested hub calls have their own _CTX)
_asking_lock = threading.Lock()


def _wait_for_user(fn: Callable[[str], bool], prompt: str) -> bool:
    """Ask, and while the user hasn't answered, no tool counts as slow (it is never moved to the background:
    a turn that ended under an open yes/no card turned the user's 'Yes' into 'declined')."""
    with _asking_lock:
        _asking[0] += 1
    try:
        return bool(fn(prompt))
    except Exception as e:
        log.warning("confirmation failed: %s", e)
        return False
    finally:
        with _asking_lock:
            _asking[0] -= 1


def asking_now() -> bool:
    return _asking[0] > 0


def ask(prompt: str) -> bool:
    """Ask the user from inside a tool (the caller's confirm hook); no hook or an error means no."""
    ctx = _CTX.get()
    return _wait_for_user(ctx.get("confirm") or deny_all, prompt)


def describe(tool: registry.BaseTool, args: dict) -> str:
    """Short question for the user, e.g. "Should I delete a file (path=/tmp/x)?"."""
    if tool.name in ("run_command", "run_python"):  # the owner approves the exact command / program
        body = args.get("command") or args.get("code") or ""
        where = f" in {args['folder']}" if args.get("folder") else ""
        return f"Should I run this {'command' if tool.name == 'run_command' else 'Python program'}{where}?\n{str(body)[:600]}"
    what = tool.description.rstrip(". ")
    what = what[:1].lower() + what[1:]
    shown = ", ".join(f"{k}={str(v)[:60]}" for k, v in args.items())
    return f"Should I {what}{f' ({shown})' if shown else ''}?"


# --- shell allowlist: lives in shellcheck.py (stdlib only, used by daemons too) ---


# --- the gate ---
def execute(name: str, args: Any = None, confirm: ConfirmFn | None = None,
            reg: registry.Registry | None = None, ctx: dict | None = None) -> ToolResult:
    """Run one tool call through the safety policy and log it."""
    reg = reg or registry.REGISTRY
    t0 = time.monotonic()
    name, args = reg.resolve(name, args)  # a retired tool name runs the tool that replaced it
    tool = reg.get(name)

    def done(res: ToolResult, outcome: str, safety: str, logged_args: Any) -> ToolResult:
        try:
            store.log_tool(name, logged_args, res.ok, int((time.monotonic() - t0) * 1000),
                           safety=safety, error=res.error, outcome=outcome, result=res.output)
        except Exception as e:  # logging must never break the agent
            log.warning("could not log tool call: %s", e)
        return res

    if tool is None:
        return done(ToolResult(False, f"error: unknown tool {name!r}", "unknown tool"),
                    "error", "unknown", args)
    try:
        clean = reg.parse_args(tool, args)
    except registry.ToolError as e:
        return done(ToolResult(False, f"error: {e}", str(e)), "error", registry.safety_of(tool), args)

    level = registry.safety_of(tool)
    if level == "blocked":
        return done(ToolResult(False, f"Refused: {name} is blocked by the safety policy.",
                               "blocked"), "blocked", "blocked", clean)
    if level == "confirm":
        approved = _wait_for_user(confirm or deny_all, describe(tool, clean))
        if not approved:
            return done(ToolResult(False, f"The user declined: {name} was not run.", "denied"),
                        "denied", "confirm", clean)
    token = _CTX.set({**(ctx or {}), "confirm": confirm or deny_all})
    try:
        res = _call_or_background(reg, name, clean, ctx or {})
    finally:
        _CTX.reset(token)
    return done(res, "allowed" if res.ok else "error", level, clean)


BACKGROUND_SAID = "That's taking a while, so I'm finishing it in the background (job #{id}). I'll tell you when it's done."
BACKGROUND_NOTE = ("Still working after {s:.0f} s, so this keeps running in the background as job #{id}. Tell the user "
                   "in one short sentence that you're doing it in the background, they can keep talking to you, and "
                   "you'll tell them when it's done. Don't wait for it and don't make up the result.")


def _call_or_background(reg: registry.Registry, name: str, clean: Any, ctx: dict) -> ToolResult:
    """Run the tool; if it is still busy after config.TOOL_BACKGROUND_AFTER_S, hand it to a background job so the
    turn (and the voice loop) is free again. The job saves the result (Workspace) and announces it when done."""
    wait = config.TOOL_BACKGROUND_AFTER_S
    if (not wait or name in config.TOOL_NO_BACKGROUND or "jobs" not in ctx
            or threading.current_thread().name.startswith(("job", "tool-"))):
        return reg.call(name, clean)
    box: dict[str, ToolResult] = {}
    finished = threading.Event()
    run_ctx = contextvars.copy_context()  # keeps _CTX (confirm hook, workspace shelf) in the worker thread

    def work() -> None:
        try:
            box["res"] = run_ctx.run(reg.call, name, clean)
        except Exception as e:  # reg.call already catches tool errors; this is a last guard
            box["res"] = ToolResult(False, f"error: {type(e).__name__}: {e}", str(e))
        finally:
            finished.set()

    threading.Thread(target=work, name=f"tool-{name}", daemon=True).start()
    live = _CTX.get()  # the same dict the tool thread sees: it says when the tool is waiting on the user
    busy = 0.0
    while not finished.wait(0.25):
        if not live.get("asking") and not asking_now():
            busy += 0.25
        if busy >= wait:
            break
    else:
        return box["res"]
    from jarvis.core import jobs, workspace

    def follow(jc: Any) -> str | None:
        while not finished.wait(1.0):
            jc.check()  # "cancel job N" stops waiting (the tool thread itself can't be killed)
        res = box["res"]
        if not res.ok:
            raise RuntimeError(res.output[:300])
        lang = ctx.get("lang") or "en"
        shelf = list(ctx.get("published") or [])
        if shelf:  # the tool already put its full result in the workspace
            jc.progress("» " + workspace.short_line(res.output, lang))
            return str(Path(config.OUTPUTS_DIR) / shelf[-1])
        title = f"{name.replace('_', ' ')}: {(ctx.get('user_text') or '')[:60]}"
        line, path = workspace.to_workspace(title, res.output, lang)  # the answer itself, not just "done"
        jc.progress("» " + line)
        return str(path) if path else None

    args_txt = ", ".join(str(v)[:30] for v in (clean.values() if isinstance(clean, dict) else [clean]) if v)
    job = jobs.get_manager().submit(f"{name.replace('_', ' ')}{': ' + args_txt if args_txt else ''}"[:80],
                                    "tool", follow, request=ctx.get("user_text", ""), lang=ctx.get("lang") or "en")
    if job.id not in ctx["jobs"]:  # JobManager.submit may have listed it already
        ctx["jobs"].append(job.id)
    log.info("tool %s still running after %.0f s: continues as job #%d", name, wait, job.id)
    return ToolResult(True, BACKGROUND_NOTE.format(s=wait, id=job.id))
