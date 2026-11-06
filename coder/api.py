"""What KURAMA calls (jarvis/agents/coding/tools.py):

  start(request)   a new project / file / feature: understood at once (0 tokens), a question if it can't tell,
                   else the plan job starts (1 call) and the plan comes to the workspace; while a plan waits, a
                   request that changes it ("use Tailwind", "drop the scoreboard") makes a new plan instead
  yes()            build the waiting plan (the build job: files, checks, fixes; progress in the Progress section)
  no()             drop the waiting plan
  undo_last()      put back what the last build did (new projects go to the trash)
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from coder import engine, link, settings, understand
from coder.run import FileSpec, Run, new

PENDING_TTL_S = 1800
_NEW_REQUEST = re.compile(r"\b(?:new|another)\s+(?:project|app|game|website|file)\b|\b(?:create|build|make|start)\s+(?:a|an|the)\b", re.I)


def _pending_path() -> Path:
    return settings.data_dir() / "pending.json"


def keep_pending(run: Run) -> None:
    from dataclasses import asdict
    d = asdict(run)
    d["root"] = str(run.root)
    d["until"] = time.time() + PENDING_TTL_S
    _pending_path().write_text(json.dumps(d), encoding="utf-8")


def pending() -> Run | None:
    p = _pending_path()
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except ValueError:
        d = None
    if not d or time.time() > float(d.pop("until", 0)):
        return None
    files = [FileSpec(**f) for f in d.pop("files", [])]
    d["root"] = Path(d["root"])
    run = Run(**{k: v for k, v in d.items() if k in Run.__dataclass_fields__})
    run.files = files
    return run


def drop() -> None:
    _pending_path().unlink(missing_ok=True)


def _question_key() -> Path:
    return settings.data_dir() / "question.json"


def start(request: str, confirmed: bool = False) -> str:
    request = " ".join((request or "").split())
    if not request:
        return "Tell me what to build, e.g. 'a rock paper scissors game in HTML, CSS and JavaScript'."
    if (q := later(request)) is not None:  # 'after that, add dark mode' while a build runs
        return q
    waiting = pending()
    if waiting is not None and not _NEW_REQUEST.search(request):  # 'use tailwind' / 'drop the scoreboard'
        waiting.request = f"{waiting.request}. Change: {request}"
        waiting.files, waiting.tokens = [], 0
        drop()
        link.submit(f"Plan again: {waiting.plan_name or waiting.root.name}", engine.plan_job(waiting))
        return f"Changing the plan ({request}). The new plan comes to the workspace in a few seconds."
    q = _question_key()
    if q.exists():  # the answer to 'web or python?': the original request + the answer
        try:
            asked = json.loads(q.read_text(encoding="utf-8"))
            if time.time() - float(asked.get("ts", 0)) < 600 and len(request.split()) <= 6:
                said = request.lower()
                request = asked["request"] + (" in HTML, CSS and JavaScript" if re.search(r"\bweb|browser|html", said)
                                              else " in Python with Pygame" if "python" in said or "pygame" in said
                                              else f" ({request})")
        except (ValueError, KeyError):
            pass
        q.unlink(missing_ok=True)
    if len(request.split()) < 2:
        return "Tell me what to build, e.g. 'a rock paper scissors game in HTML, CSS and JavaScript'."
    stack = understand.stack_of(request)
    if ask := understand.question(request, stack):
        q.write_text(json.dumps({"request": request, "ts": time.time()}), encoding="utf-8")
        return ask
    root, kind = understand.folder(request)
    run = new(request, root)
    run.stack, run.kind = stack, kind
    run.channel = link.channel()
    run.save()
    job = link.submit(f"Plan: {root.name}", engine.plan_job(run))
    where = "in the open project" if kind == "add" else f"in {root}"
    return f"Planning it {where} (job #{job}). The plan comes to the workspace; nothing is written before your yes."


def yes() -> str:
    run = pending()
    if run is None:
        return "No plan is waiting. Tell me what to build."
    drop()
    job = link.submit(f"Build: {run.plan_name or run.root.name}", engine.build_job(run))
    mark_building(job)
    return (f"Building {run.plan_name or run.root.name}: {len(run.files)} files (job #{job}). Watch it in the "
            "Progress section; I'll tell you when it's ready.")


def no() -> str:
    if pending() is None:
        return "No plan is waiting."
    drop()
    return "Okay, I dropped the plan. Nothing was written."


def cost_waiting() -> bool:
    return pending() is not None


def take_cost() -> dict | None:  # (the old project flow's name; a waiting plan is the cost question now)
    return {"action": "coder"} if pending() is not None else None


def undo_last() -> str:
    from coder import run as runmod, safety
    d = runmod.last_run()
    return safety.undo(d) if d is not None else "I haven't built anything to undo."


# ---------------------------------------------------------------- checking and reviewing (step 2)
def project_root() -> Path | None:
    """The project these are about: the one open in VS Code, else the last one built."""
    if (r := link.vscode_root()) is not None:
        return r
    from coder import run as runmod
    d = runmod.last_run()
    try:
        return Path(json.loads((d / "undo.json").read_text(encoding="utf-8"))["root"]) if d else None
    except (OSError, ValueError, KeyError):
        return None


def write_tests(request: str = "") -> str:
    from coder import testing
    root = project_root()
    if root is None:
        return "Open the project in VS Code first, then ask again."
    only = (re.search(r"\b([\w-]+)\.py\b", request or "") or [None, ""])[1]
    mods = [m for m in testing.modules(root) if not only or only in m.name]
    if not mods:
        return f"{root.name} has no Python modules to test{' named ' + only if only else ''}."

    def job(ctx) -> str | None:
        ctx.progress(f"writing tests for {len(mods[:6])} module(s)")
        run, written = testing.write(root, only)
        ctx.progress("running them")
        ok, out = testing.run_tests(root)
        from coder import run as runmod
        runmod.finish(run)
        last = out.strip().splitlines()[-1] if out.strip() else ""
        ctx.progress("» " + (f"Wrote {len(written)} test file(s) in {root.name}/tests; they all pass ({last})." if ok else
                             f"Wrote {len(written)} test file(s); some fail ({last}). Say 'make the tests pass' and I'll fix the code."))
        return str(root / "tests")
    n = link.submit(f"Tests for {root.name}", job)
    return f"Writing tests for {len(mods[:6])} module(s) of {root.name} (job #{n}), then I'll run them."


def make_tests_pass() -> str:
    from coder import testing
    root = project_root()
    if root is None:
        return "Open the project in VS Code first, then ask again."

    def job(ctx) -> str | None:
        ctx.progress("running the tests")
        ok, out, run = testing.make_pass(root, on_round=lambda n, files: ctx.progress(f"fixing {', '.join(files)} (round {n})"))
        from coder import run as runmod
        runmod.finish(run)
        last = out.strip().splitlines()[-1] if out.strip() else ""
        ctx.progress("» " + (f"All tests pass in {root.name} ({last})." + (f" I changed {len(run.written) or 'some'} file(s): 'undo the project' puts them back." if run.tokens else "")
                             if ok else f"Still failing after my fixes ({last}). The details are in the workspace."))
        if not ok:
            link.to_workspace(f"Tests: {root.name}", "```\n" + out[-3500:] + "\n```")
        return None
    n = link.submit(f"Make the tests pass: {root.name}", job)
    return f"Running the tests of {root.name} and fixing what fails (job #{n})."


def review_changes() -> str:
    from coder import review
    root = project_root()
    if root is None:
        return "Open the project in VS Code first."
    text = review.review(root)
    link.to_workspace(f"Review: {root.name}", text)
    first = text.strip().splitlines()[0] if text.strip() else ""
    return first + (" The whole review is in the workspace." if len(text.splitlines()) > 1 else "")


def _commit_path() -> Path:
    return settings.data_dir() / "commit.json"


def commit_prepare() -> str:
    from coder import review
    root = project_root()
    if root is None:
        return "Open the project in VS Code first."
    msg = review.commit_message(root)
    if not msg:
        return "There's nothing to commit."
    _commit_path().write_text(json.dumps({"root": str(root), "message": msg, "until": time.time() + 900}), encoding="utf-8")
    return f"Commit message:\n{msg}\n\nSay yes to commit everything in {root.name} with it."


def commit_waiting() -> bool:
    try:
        d = json.loads(_commit_path().read_text(encoding="utf-8"))
        return time.time() < float(d.get("until", 0))
    except (OSError, ValueError):
        return False


def commit_yes() -> str:
    from coder import review
    d = json.loads(_commit_path().read_text(encoding="utf-8"))
    _commit_path().unlink(missing_ok=True)
    return review.commit(Path(d["root"]), d["message"])


def commit_no() -> str:
    _commit_path().unlink(missing_ok=True)
    return "Okay, not committed."


def diffs() -> str:
    from coder import review
    return review.diffs()


def reject(name: str) -> str:
    from coder import review
    return review.reject(name)


# ---------------------------------------------------------------- seeing it run (step 3)
def preview_page() -> str:
    from coder import preview
    root = project_root()
    return preview.open_page(root) if root else "Open the project in VS Code first."


def check_page() -> str:
    """The errors the page showed while the owner used it -> fixed (a job)."""
    from coder import fixloop, preview
    root = project_root()
    if root is None:
        return "Open the project in VS Code first."
    found = preview.seen(root) or preview.selftest(root) or []
    if not found:
        return "The page showed no errors. (Say 'how does it look?' for a look at the design.)"

    def job(ctx) -> str | None:
        run = new(f"fix the page errors in {root.name}", root)
        run.kind = "add"
        ctx.progress(f"fixing {len(found)} page error(s)")
        fixloop.fix_round(run, found)
        left = fixloop.problems(run)
        from coder import run as runmod
        runmod.finish(run)
        ctx.progress("» " + ("Fixed: the page runs without errors now. Reload it to see." if not left else
                             f"{len(left)} error(s) are left: " + "; ".join(left[:3])))
        return None
    n = link.submit(f"Fix the page: {root.name}", job)
    return f"The page showed {len(found)} error(s); fixing them (job #{n}): " + "; ".join(found[:2])


def look_at_page(request: str = "") -> str:
    from coder import preview
    root = project_root()
    if root is None:
        return "Open the project in VS Code first."

    def job(ctx) -> str | None:
        ctx.progress("taking a look at the page")
        text = preview.look(root, request)
        link.to_workspace(f"How {root.name} looks", text)
        ctx.progress("» " + (text.splitlines()[0][:200] if text else "No answer.") + " (the whole look is in the workspace)")
        return None
    n = link.submit(f"Look at {root.name}", job)
    return f"Looking at the page (job #{n})."


# ---------------------------------------------------------------- the rest (step 4)
def _queue_path() -> Path:
    return settings.data_dir() / "queue.json"


def _active_path() -> Path:
    return settings.data_dir() / "active.json"


def building() -> bool:
    """A build job is running now (queued requests wait for it)."""
    try:
        d = json.loads(_active_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    from jarvis.core import jobs
    j = jobs.get_manager().get(int(d.get("job") or 0))
    return j is not None and j.status in ("queued", "running")


def mark_building(job_id: int) -> None:
    _active_path().write_text(json.dumps({"job": job_id}), encoding="utf-8")


def queue(request: str) -> str:
    items = queued()
    items.append(request)
    _queue_path().write_text(json.dumps(items), encoding="utf-8")
    return f"Queued (#{len(items)}): I'll plan '{request[:80]}' when the current build is done."


def queued() -> list[str]:
    try:
        return list(json.loads(_queue_path().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []


def next_queued() -> str:
    """After a build: the next queued request starts planning (its plan then waits for a yes)."""
    items = queued()
    if not items:
        return ""
    first, rest = items[0], items[1:]
    _queue_path().write_text(json.dumps(rest), encoding="utf-8")
    return start(first)


_LATER = re.compile(r"^\s*(?:after\s+(?:that|this|it)|then|next|when\s+(?:you(?:'re| are)|it(?:'s| is))\s+done|"
                    r"once\s+(?:that|it)(?:'s| is)\s+done)\b[\s,]*", re.I)


def later(request: str) -> str | None:
    """'after that, add dark mode' while a build runs -> queued. None = not a queued request."""
    if not _LATER.search(request or "") or not building():
        return None
    return queue(_LATER.sub("", request).strip() or request)


def continue_project() -> str:
    """'continue the project': its first open TODO.md item, planned as an addition."""
    from coder import memory
    root = project_root()
    if root is None:
        return "Open the project in VS Code first."
    items = memory.todo(root)
    if not items:
        return f"{root.name} has nothing left in TODO.md. Tell me what to add."
    run = new(items[0], root)
    run.kind, run.stack, run.todo_item = "add", understand.stack_of(memory.read(root)), items[0]
    run.save()
    n = link.submit(f"Plan: {items[0][:50]}", engine.plan_job(run))
    return f"Next in {root.name}'s TODO: '{items[0]}'. Planning it (job #{n}); the plan comes to the workspace."


def handoff() -> str:
    """The waiting plan built by Claude Code instead (a big one: uses the Claude Code plan, not Groq tokens)."""
    from coder import planner
    run = pending()
    if run is None:
        return "No plan is waiting to hand over."
    drop()
    prompt = (f"Build this project in this folder ({run.root}). Request: {run.request}. Follow this plan, keep the "
              f"structure clean and production quality, then run it and fix any errors:\n\n{planner.text(run)}")
    link.to_workspace(f"Prompt for Claude Code: {run.plan_name}", prompt)
    return link.claude_code(prompt, run.root)


def tokens_report() -> str:
    p = settings.data_dir() / "projects.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "The coding agent hasn't built anything yet."
    root = project_root()
    if root is not None and str(root) in d:
        e = d[str(root)]
        return f"{root.name}: {e['tokens'] / 1000:.1f}k tokens over {e['runs']} run(s) (last {e.get('last', '?')})."
    rows = sorted(d.items(), key=lambda kv: -kv[1]["tokens"])[:6]
    return "Tokens per project: " + "; ".join(f"{Path(k).name} {v['tokens'] / 1000:.1f}k ({v['runs']} runs)" for k, v in rows) + "."


def learn_project() -> str:
    """Read the open project once (facts + one small call) and write its card."""
    from coder import onboard
    root = project_root()
    if root is None:
        return "Open the project in VS Code first."

    def job(ctx) -> str | None:
        ctx.progress("reading the project's map, manifests and README")
        ctx.progress("» " + onboard.learn(root))
        link.to_workspace(f"Project card: {root.name}", (root / ".kurama" / "project.md").read_text(encoding="utf-8")
                          if (root / ".kurama" / "project.md").exists() else "")
        return None
    n = link.submit(f"Learn {root.name}", job)
    again = " (again: the card is rewritten)" if onboard.known(root) else ""
    return f"Learning {root.name}{again} (job #{n}): its map and manifests, one small AI call, no full code read."
