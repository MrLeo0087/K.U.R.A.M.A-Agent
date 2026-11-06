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
