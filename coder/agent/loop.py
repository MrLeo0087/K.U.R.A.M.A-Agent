"""The agent loop (like Claude Code, sized for Groq's free models): a LangGraph graph

    context (0 tokens) -> plan (1 small call) -> step: think + ONE tool -> observe -> step … -> finish
                                                      ^____________________________|
It is not a straight line: every step sees the goal, the plan, its own running notes and the last tool's result,
and decides what to do next (read before editing, run after editing, look again when something fails, re-plan).
It ends when the model says the goal is reached and checked, asks the owner something it can't decide, or hits
the budget (steps / tokens) — then it says where it stopped and offers Claude Code for the rest.

Token care: the project card + a short file list instead of code; tool outputs cut; precise edits instead of
whole files; only the last observation in full, older ones as one-line notes; the plan model is the fast one.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, TypedDict

from coder.interfaces import link
from coder.memory import card as memory
from coder.llm import models
from coder.memory import repomap
from coder.core import settings
from coder.tools import builtin as tools
from coder.core.run import Run

MAX_STEPS = 12
STEP_TOKENS = 1800  # a step's output (an edit can carry code)

_PLAN_SYS = ("You plan a coding task for an agent that can read, grep, edit, write, run commands, run the project, "
             "take screenshots and look at them. Return ONLY JSON: {\"plan\": [\"short step\", …max 6], "
             "\"check\": \"how to verify it is really done\"}. Read before changing; run / screenshot after changing.")
_STEP_SYS = ("You are a careful coding agent working inside the user's project, one tool call per turn. Read (or "
             "grep) the exact lines before an edit and copy the old text exactly; prefer small edits; keep the "
             "project's style; make ALL the changes the goal asks for. When the changes are made, call done: I then "
             "run the project, check its errors and, for anything visual, take a screenshot and compare it with the "
             "goal; if something is still wrong you get it back to fix. To just run something (\"run it and tell me "
             "what it prints\"), use run_project / run, then done with what it printed. Never install or delete by "
             "yourself: call ask. Stay inside the project. Don't read a file again: its current content is in 'Files "
             "you have read'.")
VISUAL = re.compile(r"\b(?:ui|ux|look|looks|design|colou?r|grey|gray|dark|light|button|layout|left|right|center|centre|"
                    r"top|bottom|align|font|size|bigger|smaller|spacing|margin|padding|style|theme|beautiful|ugly|flat|"
                    r"modern|page|screen|header|footer|card|icon|image|responsive|blue|red|green|black|white|purple|orange|yellow|pink|bold|italic)\b", re.I)
MAX_VERIFY = 1  # one fix round after a failed check (each costs a screenshot + a look)
_RUN_GOAL = re.compile(r"\b(?:run|start|launch|execute|screenshot|how (?:does )?it looks?|what (?:does it|it) (?:print|say|show)|output|crash(?:ed|es)?|"
                       r"the command)\b", re.I)
_CHECK_TOOLS = {"run_project", "screenshot", "look", "page_errors"}  # for a change, the verify step does these


class S(TypedDict, total=False):
    run: Run
    ctx: Any
    goal: str
    context: str
    plan: list[str]
    check: str
    notes: list[str]
    last: str
    seen: dict
    steps: int
    done: str
    verified: int
    fixing: bool
    ask: str
    command: str


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {}
    raw = m.group(0)
    for attempt in (raw, re.sub(r",\s*([}\]])", r"\1", raw)):
        try:
            return json.loads(attempt)
        except ValueError:
            continue
    return {}


def context(run: Run) -> str:
    """What the agent knows before it starts (0 tokens): the project card, its files, what is open in VS Code, the
    last crash, the owner's style, the last task (so 'make it grey' continues it)."""
    parts = []
    if card := memory.read(run.root, 1500):
        parts.append("Project card:\n" + card)
    parts.append("Files:\n" + repomap.text(run.root, 1800))
    try:
        from jarvis.core import context as ctxmod
        snap = ctxmod.snapshot()
        f = snap.get("file")
        if f and Path(f).resolve().is_relative_to(run.root.resolve()):
            rel = Path(f).resolve().relative_to(run.root.resolve()).as_posix()
            sel = (snap.get("selection") or "").strip()
            parts.append(f"Open in VS Code: {rel}" + (f"\nSelected there:\n{sel[:600]}" if sel else ""))
    except Exception:  # noqa: BLE001
        pass
    try:
        from jarvis.agents.coding import terminal
        if (crash := terminal.last(1800)) and str(crash.get("cwd") or "").startswith(str(run.root)):
            parts.append(f"Last crash in the VS Code terminal: `{crash.get('command')}`\n{str(crash.get('output'))[-700:]}")
    except Exception:  # noqa: BLE001
        pass
    if style := _style():
        parts.append("The owner's preferences: " + style)
    if last := _last_task(run.root):
        parts.append("The previous task here (\"it\" / \"that\" may mean this): " + last)
    return "\n\n".join(parts)


def small_project(run: Run, limit: int = 9000) -> dict:
    """A small project's code given at once (its files as 'read'): no read-steps needed (each step costs ~2.5k
    tokens of context, so 4 reads cost more than the files themselves)."""
    files = [f for f in repomap.files(run.root, 40) if f.suffix in (".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css",
                                                                     ".json", ".md") and f.name not in ("package-lock.json",)]
    files = [f for f in files if ".kurama" not in f.parts and f.name not in ("README.md", "TODO.md")]
    if not files or sum(f.stat().st_size for f in files) > limit:
        return {}
    return {f.relative_to(run.root).as_posix(): tools.t_read(run, f.relative_to(run.root).as_posix()) for f in files}


# ---------------------------------------------------------------- the graph
def _plan(state: S) -> dict:
    run = state["run"]
    state["ctx"].progress("planning")
    try:
        out = _json(models.ask(run, "plan", _PLAN_SYS, f"Task: {state['goal']}\n\n{state['context']}", 600))
    except Exception:  # noqa: BLE001 - a default plan; the loop decides step by step anyway
        out = {}
    plan = [str(x)[:120] for x in (out.get("plan") or [])][:6] or ["read the relevant files", "make the change",
                                                                     "run / check it"]
    _steps(state, plan, 0)
    return {"plan": plan, "check": str(out.get("check") or "")[:200]}


def _steps(state: S, plan: list[str], doing: int, notes: list[str] | None = None) -> None:
    items = [(p, "done" if i < doing else "doing" if i == doing else "todo") for i, p in enumerate(plan)]
    if notes:
        items.append((notes[-1][:90], "doing"))
    link.steps(state["job"] if "job" in state else state["ctx"].job.id, items)


def _seen_text(seen: dict) -> str:
    """The files the agent has read, as they are NOW (so it never reads them again; newest first, ~7k characters)."""
    out, total = [], 0
    for rel in reversed(list(seen)):
        body = seen[rel]
        if total + len(body) > 7000:
            out.append(f"--- {rel} (read earlier; read it again if you need it)")
            continue
        out.append(f"--- {rel} ---\n{body}")
        total += len(body)
    return "\n".join(out)


def _act(state: S) -> dict:
    run, ctx = state["run"], state["ctx"]
    ctx.check()
    notes, seen = state.get("notes") or [], dict(state.get("seen") or {})
    # the project card + file list only until it has read what it needs (then they are dead weight: tokens)
    ctx_text = state["context"][:2600] if len(seen) < 2 else state["context"][:500]
    user = (f"Goal: {state['goal']}\nPlan: " + " | ".join(state.get("plan") or []) +
            (f"\nDone when: {state['check']}" if state.get("check") else "") +
            f"\n\n{ctx_text}" + (f"\n\nFiles you have read (current content):\n{_seen_text(seen)}" if seen else "")
            + "\n\nYour steps so far:\n" + ("\n".join(notes[-14:]) or "(none)") +
            ("\n\nResult of your last step:\n" + state["last"] if state.get("last") else ""))
    from jarvis.core import llm
    running = bool(_RUN_GOAL.search(state["goal"]))  # 'run it and tell me': it may run; a change: the code checks it
    schemas = tools.SCHEMAS if running else [x for x in tools.SCHEMAS if x["function"]["name"] not in _CHECK_TOOLS]
    if state.get("fixing"):  # the check found something: the next call must be the fix itself
        schemas = [x for x in tools.SCHEMAS if x["function"]["name"] in ("edit", "write", "grep", "ask")]
    try:
        r = llm.chat([{"role": "system", "content": _STEP_SYS}, {"role": "user", "content": user}], tier="smart",
                     tools=schemas, tool_choice="required", purpose="coder_step", max_tokens=STEP_TOKENS)
    except Exception as e:  # noqa: BLE001 - one failed call is a note, the next step tries again
        step = state.get("steps", 0) + 1
        return {"last": f"(the AI call failed: {str(e)[:120]})", "steps": step, "notes": [*notes, f"{step}. (AI call failed)"]}
    run.tokens += int(r.prompt_tokens or 0) + int(r.completion_tokens or 0)
    step = state.get("steps", 0) + 1
    call = (r.tool_calls or [None])[0]
    if call is None:
        return {"last": "Call exactly ONE tool.", "steps": step, "notes": [*notes, f"{step}. (no tool called)"]}
    name = call.get("name") or ""
    try:
        args = json.loads(call.get("arguments") or "{}") if isinstance(call.get("arguments"), str) else (call.get("arguments") or {})
    except ValueError:
        args = {}
    if name == "done":
        return {"done": str(args.get("summary") or "Done.")[:500], "steps": step}
    if name in ("edit", "write"):
        state["fixing"] = False
    if run.written and name not in ("edit", "write", "read", "grep", "find", "list") and not running:
        # the changes are made and it wanders (run / git status / again…): the code checks the work now
        return {"done": "Made the changes: " + ", ".join(sorted(set(run.written))), "steps": step}
    if name == "ask":
        return {"ask": str(args.get("question") or "")[:400], "command": str(args.get("command") or "")[:300], "steps": step}
    ctx.progress(f"{_icon(name)} {name} {_short_args(args)}"[:120])
    obs = tools.call(run, name, args)
    if name == "read" and not obs.startswith(("tool error", "no ")) and "doesn't exist" not in obs:
        seen[str(args.get("path"))] = obs
    if name in ("edit", "write") and obs.startswith(("edited", "wrote")):  # what it read is now the NEW text
        rel = str(args.get("path"))
        seen[rel] = tools.call(run, "read", {"path": rel})
    note = f"{step}. {name}({_short_args(args)}): {obs.splitlines()[0][:120] if obs else ''}"
    _steps(state, state.get("plan") or [], min(len(state.get("plan") or []) - 1, step // 2), [*notes, note])
    last = obs if name != "read" else f"(the content of {args.get('path')} is now in 'Files you have read')"
    sig = note.split(". ", 1)[-1]
    if sum(1 for n in notes[-3:] if n.split(". ", 1)[-1] == sig) >= 1:  # the same call, the same result again
        last += ("\n(You already did exactly this and got the same result. Don't repeat it: do something different, "
                 "or call done / ask.)")
    return {"last": last, "notes": [*notes, note], "steps": step, "seen": seen,
            "fixing": bool(state.get("fixing")) and name not in ("edit", "write")}


def _verify(state: S) -> dict:
    """The code checks the work (cheap and reliable with a small model): run it; a visual goal gets a screenshot
    compared with the goal by the vision model. Something wrong -> back to the loop with exactly that."""
    run, ctx = state["run"], state["ctx"]
    rounds = state.get("verified", 0) + 1
    if not run.written:  # nothing was changed (a question, a run): nothing to check
        return {"verified": rounds}
    ctx.progress("▶️ running it to check")
    problems = []
    out = tools.t_run_project(run)
    if re.search(r"errors:\n|Traceback|exit: [1-9]|Error:|crash", out):
        problems.append("Running it shows a problem:\n" + out[-900:])
    if VISUAL.search(state["goal"]) and not problems:
        ctx.progress("📸 screenshot to compare with what you asked")
        shot = tools.t_screenshot(run)
        if shot.startswith("screenshot saved"):
            seen = tools.t_look(run, f"The user asked: \"{state['goal'][:300]}\". Check each requested change in this "
                                     "screenshot: one line per change, 'done' or 'not done' with why. Judge only what "
                                     "was asked (not other styling). Last line exactly: ALL DONE or NOT DONE.")
            up = seen.upper()
            ok_n, bad_n = len(re.findall(r"\bDONE\b", up)) - len(re.findall(r"NOT DONE", up)), len(re.findall(r"NOT DONE", up))
            if not ("ALL DONE" in up or (bad_n <= 1 and ok_n >= 3 * bad_n + 2)):  # (a picky judge: one doubtful
                #                                                      point among many done ones is not a redo)
                problems.append("The screenshot shows it isn't fully done yet:\n" + seen)
    note = f"check {rounds}: " + ("all good" if not problems else problems[0].splitlines()[0][:100])
    notes = [*(state.get("notes") or []), note]
    if problems and rounds <= MAX_VERIFY:
        return {"verified": rounds, "done": "", "notes": notes, "fixing": True,
                "last": "\n".join(problems) + "\nFix this now with edit (the files' current content is above), "
                        "then call done again."}
    return {"verified": rounds, "notes": notes}


def _after_verify(state: S) -> str:
    return "act" if not state.get("done") and not state.get("ask") and state.get("last") else "finish"


def _route(state: S) -> str:
    run = state["run"]
    if state.get("ask"):
        return "finish"
    if state.get("done"):
        return "verify"
    if state.get("steps", 0) >= MAX_STEPS or run.tokens >= settings.ASK_TOKENS * 1.5:
        return "finish"
    return "act"


def _finish(state: S) -> dict:
    run = state["run"]
    notes = state.get("notes") or []
    if run.written:
        memory.note_task(run, state["goal"], state.get("done") or "", notes)
    _save_last_task(run.root, state["goal"], state.get("done") or "", notes)
    _learn_style(state["goal"])
    return {}


def graph():
    from langgraph.graph import END, START, StateGraph
    g = StateGraph(S)
    g.add_node("plan", _plan)
    g.add_node("act", _act)
    g.add_node("verify", _verify)
    g.add_node("finish", _finish)
    g.add_edge(START, "plan")
    g.add_edge("plan", "act")
    g.add_conditional_edges("act", _route, {"act": "act", "verify": "verify", "finish": "finish"})
    g.add_conditional_edges("verify", _after_verify, {"act": "act", "finish": "finish"})
    g.add_edge("finish", END)
    return g.compile()


def task_job(run: Run, goal: str):
    """The background job: the loop, then a report (chat line, workspace with screenshots, Telegram)."""
    def job(ctx) -> str | None:
        from coder.core import safety
        safety.begin(run)
        ctx.progress("reading the project")
        state = graph().invoke({"run": run, "ctx": ctx, "goal": goal, "context": context(run), "notes": [],
                                "steps": 0, "seen": small_project(run)}, {"recursion_limit": 2 * MAX_STEPS + 10})
        line = _report(run, goal, state, ctx.job.id)
        ctx.progress("» " + line)
        return str(run.root)
    return job


def _report(run: Run, goal: str, state: dict, job_id: int) -> str:
    shots = sorted((run.dir / "shots").glob("*.png")) if (run.dir / "shots").exists() else []
    changed = sorted(set(run.written))
    md = [f"# {goal[:80]}", "", f"Project: `{run.root}`", f"Steps: {state.get('steps', 0)} · tokens: {run.tokens / 1000:.1f}k",
          "", "## What I did", *[f"- {n}" for n in state.get("notes") or []]]
    if changed:
        md += ["", "## Files changed", *[f"- `{c}`" for c in changed], "", "Say 'undo that' to put them back."]
    link.to_workspace(f"Task: {goal[:50]}", "\n".join(md))
    for s in shots[-2:]:  # before / after pictures next to it
        link.to_workspace_file(s, f"{goal[:30]} {s.stem}")
    if state.get("ask"):
        _save_waiting(run, goal, state)
        return state["ask"]
    if state.get("done"):
        line = state["done"] + (f" ({len(changed)} file(s) changed, {run.tokens / 1000:.1f}k tokens)" if changed else "")
        link.tell_result(f"✅ {goal[:60]}", line, shots[-1] if shots else None, run.channel)
        return line
    return (f"I stopped after {state.get('steps', 0)} steps ({run.tokens / 1000:.1f}k tokens) without finishing: "
            + ((state.get("notes") or ["nothing done"])[-1])[:160] + ". Say 'continue' to go on, or 'send it to "
            "Claude Code' to let Claude Code finish it.")


# ---------------------------------------------------------------- memory between tasks
def _icon(name: str) -> str:
    return {"read": "📖", "grep": "🔎", "find": "🔎", "list": "📂", "edit": "✏️", "write": "📝", "run": "▶️",
            "run_project": "▶️", "screenshot": "📸", "look": "👀", "page_errors": "🐞"}.get(name, "•")


def _short_args(args: dict) -> str:
    keep = {k: (str(v)[:40] + "…" if len(str(v)) > 40 else str(v)) for k, v in (args or {}).items()
            if k not in ("content", "new", "old")}
    return ", ".join(f"{k}={v}" for k, v in keep.items())


def _last_path() -> Path:
    return settings.data_dir() / "last_task.json"


def _save_last_task(root: Path, goal: str, done: str, notes: list[str]) -> None:
    _last_path().write_text(json.dumps({"root": str(root), "goal": goal, "done": done, "notes": notes[-8:],
                                        "t": time.time()}), encoding="utf-8")


def _last_task(root: Path) -> str:
    try:
        d = json.loads(_last_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if d.get("root") != str(root) or time.time() - float(d.get("t") or 0) > 6 * 3600:
        return ""
    return f"{d['goal']} -> {d.get('done') or 'unfinished'}; " + " / ".join(n[:80] for n in d.get("notes", [])[-4:])


def _waiting_path() -> Path:
    return settings.data_dir() / "loop_waiting.json"


def _save_waiting(run: Run, goal: str, state: dict) -> None:
    _waiting_path().write_text(json.dumps({"root": str(run.root), "goal": goal, "ask": state.get("ask"),
                                           "command": state.get("command") or "", "notes": state.get("notes") or [],
                                           "t": time.time()}), encoding="utf-8")


def waiting() -> dict | None:
    try:
        d = json.loads(_waiting_path().read_text(encoding="utf-8"))
        return d if time.time() - float(d.get("t") or 0) < 1800 else None
    except (OSError, ValueError):
        return None


def drop_waiting() -> None:
    _waiting_path().unlink(missing_ok=True)


_STYLE_WORDS = re.compile(r"\b(?:dark|light|minimal|modern|flat|rounded|grey|gray|blue|green|purple|orange|red|black|"
                          r"white|tailwind|bootstrap|typescript|type hints|tabs|spaces|material|glass)\b", re.I)


def _style() -> str:
    try:
        return (settings.data_dir() / "style.txt").read_text(encoding="utf-8")[-400:]
    except OSError:
        return ""


def _learn_style(goal: str) -> None:
    """'use grey', 'dark theme', 'with tailwind': remembered as the owner's taste for the next tasks (0 tokens)."""
    if _STYLE_WORDS.search(goal or "") and re.search(r"\b(?:use|make|prefer|want|like|with|always)\b", goal, re.I):
        with (settings.data_dir() / "style.txt").open("a", encoding="utf-8") as fh:
            fh.write(f"- {goal.strip()[:140]}\n")
