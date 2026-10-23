"""Safety gate for tool calls: safe -> run, confirm -> needs the user's yes, blocked -> refuse.

Every call (allowed, denied, blocked, error) is written to the SQLite action log
(store.log_tool with safety + outcome). Confirmation is pluggable per mode: terminal input in
text mode, a spoken yes/no hook in voice mode; anything unanswered is denied.
"""
from __future__ import annotations

import logging
import re
import select
import shlex
import sys
import time
from typing import Any, Callable

from jarvis.core import config, registry, store
from jarvis.core.registry import ToolResult

log = logging.getLogger("jarvis.safety")

ConfirmFn = Callable[[str], bool]

YES_WORDS = {
    "y", "yes", "yeah", "yea", "yep", "yup", "sure", "ok", "okay", "confirm", "confirmed", "affirmative",
    "proceed", "haan", "han", "haa", "ha", "hā", "ho", "hajur", "huncha", "hunchha", "hunxa",
    "theek", "thik", "ji", "jee", "हो", "हाँ", "हां", "हा", "जी", "हजुर", "हुन्छ", "ठीक",
}
YES_PHRASES = ("do it", "go ahead", "of course")
NO_WORDS = {
    "n", "no", "nope", "nah", "don't", "dont", "cancel", "stop", "abort", "deny", "negative", "never",
    "nahi", "nahin", "nai", "mat", "hoina", "haina", "hoeena", "नहीं", "नही", "ना", "मत", "होइन",
    "हैन", "होईन", "नाइ", "पर्दैन",
}
_TOKEN = re.compile(r"[^\s,.!?।॥;:\"'()]+")
_SHELL_META = re.compile(r"[;&|`<>]|\$\(|\$\{|\n")


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


def describe(tool: registry.BaseTool, args: dict) -> str:
    """Short question for the user, e.g. "Should I delete a file (path=/tmp/x)?"."""
    what = tool.description.rstrip(". ")
    what = what[:1].lower() + what[1:]
    shown = ", ".join(f"{k}={str(v)[:60]}" for k, v in args.items())
    return f"Should I {what}{f' ({shown})' if shown else ''}?"


# --- shell allowlist (for later shell tools) ---
def check_shell(cmd: str | list[str]) -> tuple[bool, str]:
    """(allowed, reason). Only allowlisted binaries; no sudo, pipes, redirects or chaining."""
    if isinstance(cmd, str):
        if _SHELL_META.search(cmd):
            return False, "shell operators (; & | ` < > $()) are not allowed"
        try:
            argv = shlex.split(cmd)
        except ValueError as e:
            return False, f"cannot parse command: {e}"
    else:
        argv = list(cmd)
    if not argv:
        return False, "empty command"
    binary = argv[0].rsplit("/", 1)[-1]
    if binary in ("sudo", "su", "doas", "pkexec"):
        return False, f"{binary} is never allowed"
    if binary not in config.SHELL_ALLOWLIST:
        return False, f"{binary} is not in the shell allowlist"
    return True, "ok"


# --- the gate ---
def execute(name: str, args: Any = None, confirm: ConfirmFn | None = None,
            reg: registry.Registry | None = None) -> ToolResult:
    """Run one tool call through the safety policy and log it."""
    reg = reg or registry.REGISTRY
    t0 = time.monotonic()
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
        ask = confirm or deny_all
        try:
            approved = bool(ask(describe(tool, clean)))
        except Exception as e:
            log.warning("confirmation failed: %s", e)
            approved = False
        if not approved:
            return done(ToolResult(False, f"The user declined: {name} was not run.", "denied"),
                        "denied", "confirm", clean)
    res = reg.call(name, clean)
    return done(res, "allowed" if res.ok else "error", level, clean)
