"""The two background jobs of a run, each a small LangGraph graph whose steps show as a checklist in KURAMA's
Progress section:

  plan job   understand (done before, 0 tokens) -> choose the start (scaffold / GitHub, 0 tokens) -> plan (1 call)
             -> estimate -> the plan in the workspace + "say yes to build it" (nothing is written yet)
  build job  start (scaffold) -> write every file (in plan order) -> connect + check -> fix (max 3 rounds)
             -> project memory + TODO -> report (workspace, chat, Telegram's Jobs section)
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, TypedDict

from coder.agent import fixloop
from coder.builder import planner, scaffold, writer
from coder.core import settings
from coder.core.run import Run
from coder.interfaces import link
from coder.llm import budget
from coder.memory import card as memory


class S(TypedDict, total=False):
    run: Run
    ctx: Any
    job: int
    log: list[str]
    error: str
    scaffold_files: list[str]


def _steps(state: S, items: list[tuple[str, str]]) -> None:
    link.steps(state["job"], items)


# ---------------------------------------------------------------- plan
def _choose(state: S) -> dict:
    run = state["run"]
    state["ctx"].progress("choosing how to start")
    files = scaffold.choose(run)
    run.save()
    return {"log": [*state.get("log", []), *(["starts from " + run.scaffold] if run.scaffold else [])],
            "scaffold_files": files}


def _plan(state: S) -> dict:
    run = state["run"]
    _steps(state, [("Understand the request", "done"), ("Plan the files", "doing"), ("Your yes", "todo")])
    state["ctx"].progress("planning the files")
    from coder.memory import onboard, repomap
    if run.kind == "add" and not onboard.known(run.root):  # a project I didn't build: learn it once (card)
        _steps(state, [("Learn the project (first time)", "doing"), ("Plan the files", "todo"), ("Your yes", "todo")])
        state["ctx"].progress("learning the project (first time, then I keep a card)")
        try:
            onboard.learn(run.root, run)
        except Exception as e:  # noqa: BLE001 - the plan still gets the map
            run.note(f"learning failed: {e}")
        _steps(state, [("Learn the project (first time)", "done"), ("Plan the files", "doing"), ("Your yes", "todo")])
    existing = repomap.text(run.root, 4000) if run.kind == "add" else ""
    try:
        planner.make(run, existing, memory.read(run.root), state.get("scaffold_files"))
    except Exception as e:  # noqa: BLE001
        return {"error": f"I couldn't make the plan ({str(e)[:150]}). Try again in a minute."}
    scaffold.fixed_run_cmd(run)
    run.estimate = budget.estimate(run)
    run.save()
    return {}


def plan_job(run: Run):
    """The job function: plans, shows the plan, waits for the owner's yes (api.yes)."""
    from langgraph.graph import END, START, StateGraph

    def job(ctx) -> str | None:
        g = StateGraph(S)
        g.add_node("choose", _choose)
        g.add_node("plan", _plan)
        g.add_edge(START, "choose")
        g.add_edge("choose", "plan")
        g.add_edge("plan", END)
        out = g.compile().invoke({"run": run, "ctx": ctx, "job": ctx.job.id, "log": []})
        if out.get("error"):
            link.steps(ctx.job.id, [("Understand the request", "done"), ("Plan the files", "failed")])
            ctx.progress("» " + out["error"])
            return None
        from coder.interfaces import api
        api.keep_pending(run)
        link.steps(ctx.job.id, [("Understand the request", "done"), ("Plan the files", "done"), ("Your yes", "doing")])
        big = run.estimate > settings.ASK_TOKENS
        link.to_workspace(f"Plan: {run.plan_name}", planner.text(run))
        line = (f"Plan ready: {run.plan_name}, {len(run.files)} files in {run.root}"
                + (f", from {run.scaffold}" if run.scaffold else "")
                + f". About {run.estimate / 1000:.1f}k tokens"
                + (f": that's over your {settings.ASK_TOKENS // 1000}k limit. Say yes to build it anyway, 'send it to "
                   "Claude Code' to let Claude Code build it (no Groq tokens), or tell me what to cut."
                   if big else ". It's in the workspace. Say yes to build it, or tell me what to change."))
        ctx.progress("» " + line)
        if run.channel == "telegram":  # asked from the phone: the plan goes there too (answer yes from the phone)
            link.tell(f"Coding agent: plan for {run.plan_name}", planner.text(run) + "\n\n" + line)
        return None
    return job


# ---------------------------------------------------------------- build
def _start(state: S) -> dict:
    run = state["run"]
    from coder.core import safety
    safety.begin(run)
    if run.scaffold:
        state["ctx"].progress("making the starting files")
        if why := scaffold.make(run):
            run.note("scaffold failed: " + why)
            run.scaffold = ""
    run.root.mkdir(parents=True, exist_ok=True)
    return {}


def _checklist(run: Run, doing: int, phase: str = "write") -> list[tuple[str, str]]:
    items = [("Start: " + (run.scaffold.split(" (")[0] if run.scaffold else "empty folder"), "done")]
    for i, f in enumerate(run.files):
        state = "done" if f.path in run.written else ("doing" if i == doing and phase == "write" else "todo")
        if phase != "write" and f.path not in run.written:
            state = "failed"
        items.append((f.path, state))
    items.append(("Connect and check", "doing" if phase == "check" else "done" if phase == "done" else "todo"))
    return items


def _write(state: S) -> dict:
    run, ctx = state["run"], state["ctx"]
    failed = []
    for i, f in enumerate(run.files):
        ctx.check()
        _steps(state, _checklist(run, i))
        ctx.progress(f"writing {f.path} ({i + 1}/{len(run.files)})")
        if problem := writer.write_one(run, f):
            failed.append(problem)
            run.note(problem)
        run.save()
    return {"log": [*state.get("log", []), *failed]}


def _check(state: S) -> dict:
    run, ctx = state["run"], state["ctx"]
    _steps(state, _checklist(run, -1, "check"))
    ctx.progress("checking that the files fit together")
    left = fixloop.loop(run, on_round=lambda n, p: ctx.progress(f"fixing {len(p)} problem(s), round {n}"))
    run.save()
    return {"log": [*state.get("log", []), *left]}


def _look_check(state: S) -> dict:
    """A new app with a screen (a web page, a Tkinter / Pygame window): started, pictured and compared with the
    request by the vision model (one call). What looks wrong goes to the report (\"fix it\" picks it up)."""
    run, ctx = state["run"], state["ctx"]
    if run.problems:
        return {}
    from coder.runtime import preview
    is_page = preview.page_root(run.root) is not None and not (run.root / "package.json").exists()
    src = " ".join((run.root / f).read_text(encoding="utf-8", errors="replace")[:3000] for f in run.written
                   if f.endswith(".py") and (run.root / f).is_file())
    has_window = bool(re.search(r"^\s*(?:import|from)\s+(?:tkinter|pygame)\b", src, re.M))
    if not (is_page or has_window):
        return {}
    from coder.tools import builtin as tools
    ctx.progress("📸 a picture of it, compared with what you asked")
    if not tools.t_screenshot(run).startswith("screenshot saved"):
        return {}
    seen = tools.t_look(run, f"This app was just built for the request: \"{run.request[:300]}\". Does it look "
                             "complete and good? One line per problem (missing parts, broken layout, unreadable "
                             "text). Last line exactly: LOOKS GOOD or NEEDS WORK.")
    if "NEEDS WORK" in seen.upper():  # suggestions, not failures: it works, it may look better (offered, not forced)
        tips = [ln.strip(" -*•") for ln in seen.splitlines() if ln.strip() and "NEEDS WORK" not in ln.upper()][:4]
        run.todo = [*tips, *run.todo][:6]
        run.notes = (run.notes + "\nThe look check suggests: " + "; ".join(tips))[:800]
    return {}


def _finish(state: S) -> dict:
    run = state["run"]
    memory.readme(run)
    memory.write(run)
    memory.add_todo(run.root, run.todo)
    if run.todo_item and not run.problems:
        memory.tick(run.root, run.todo_item)
    _record_tokens(run)
    _steps(state, _checklist(run, -1, "done"))
    return {}


def _record_tokens(run: Run) -> None:
    p = settings.data_dir() / "projects.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        d = {}
    e = d.setdefault(str(run.root), {"tokens": 0, "runs": 0})
    e["tokens"] += run.tokens
    e["runs"] += 1
    e["last"] = time.strftime("%Y-%m-%d %H:%M")
    p.write_text(json.dumps(d, indent=1), encoding="utf-8")


def report(run: Run) -> str:
    ok = not run.problems and all(f.path in run.written for f in run.files)
    lines = [f"# {run.plan_name}", "", f"Folder: `{run.root}`",
             f"Files written: {sum(f.path in run.written for f in run.files)}/{len(run.files)}" + (f" (on {run.scaffold})" if run.scaffold else ""),
             f"Tokens: {run.tokens / 1000:.1f}k"]
    lines += ["", "## Files", *[f"- `{f.path}`: {f.purpose}" for f in run.files]]
    if run.run_cmd:
        lines += ["", "## Run it", f"```\n{run.run_cmd}\n```"]
    if run.problems:
        lines += ["", "## Still to fix", *[f"- {p}" for p in run.problems[:10]]]
    if run.todo:
        lines += ["", "## Next ideas (in TODO.md)", *[f"- {t}" for t in run.todo]]
    lines += ["", "Undo everything: say 'undo the project'." if ok else "Say 'fix it' for the rest, or 'undo the project'."]
    return "\n".join(lines)


def build_job(run: Run):
    from langgraph.graph import END, START, StateGraph

    def job(ctx) -> str | None:
        g = StateGraph(S)
        for name, fn in (("start", _start), ("write", _write), ("check", _check), ("look", _look_check),
                         ("finish", _finish)):
            g.add_node(name, fn)
        g.add_edge(START, "start")
        g.add_edge("start", "write")
        g.add_edge("write", "check")
        g.add_edge("check", "look")
        g.add_edge("look", "finish")
        g.add_edge("finish", END)
        g.compile().invoke({"run": run, "ctx": ctx, "job": ctx.job.id, "log": []})
        from coder.core import run as runmod
        runmod.finish(run)
        link.pin(run.root)  # the project just built is the one being worked on now ("fix it", "add X" go there)
        link.to_workspace(f"Built: {run.plan_name}", report(run))
        link.open_folder(run.root)
        ok = not run.problems and all(f.path in run.written for f in run.files)
        needs = (f" It needs {', '.join(run.needs)}: say 'set it up' and I'll make a .venv, install requirements.txt, "
                 "run it and fix anything that breaks." if run.needs else "")
        if "The look check suggests:" in run.notes:  # it works; it could look better: offered, not forced
            needs += " " + run.notes[run.notes.index("The look check suggests:"):][:300] + " (say 'do that' to apply)."
        line = (f"{run.plan_name} is ready in {run.root} ({len(set(run.written))} files, all checks passed, "
                f"{run.tokens / 1000:.1f}k tokens). Run it with: {run.run_cmd or 'see README'}.{needs}" if ok else
                f"{run.plan_name} is built in {run.root} ({sum(f.path in run.written for f in run.files)}/{len(run.files)} files), but "
                f"{len(run.problems)} problem(s) are left (in the workspace). Say 'fix it' to try again.")
        ctx.progress("» " + line)
        link.tell(f"✅ Coding agent: {run.plan_name}" if ok else f"Coding agent: {run.plan_name} (needs a look)", line)
        from coder.interfaces import api
        if nxt := api.next_queued():  # 'after that, add dark mode': the next one is planned now
            link.tell("Coding agent: next in the queue", nxt)
        return str(run.root)
    return job
