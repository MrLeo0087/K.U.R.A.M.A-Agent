"""A session = the agent's memory of ONE project across tasks (like a Claude Code conversation):

    data/coder/sessions/<project-key>/
      session.json   the project, and its tasks: goal, status (running / done / asked / stopped), result, the
                     files changed, short step notes, tokens, when
      events.jsonl   every step as it happened (task start, plan, each tool call and a line of its result, the
                     check, the end): what the agent really did, for "what did you do?" and for debugging

What it gives the agent: follow-ups ("make it grey", "move that left") come with the last tasks of this project;
a task cut off by a restart is known and "continue" picks it up; tokens per task and per project.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from coder.core import settings

KEEP_TASKS = 40  # the newest tasks kept in session.json (events.jsonl is trimmed to ~400 KB)


def _dir(root: Path) -> Path:
    key = f"{root.name}-{hashlib.sha1(str(root.resolve()).encode()).hexdigest()[:8]}"
    d = settings.data_dir() / "sessions" / key
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load(root: Path) -> dict:
    try:
        return json.loads((_dir(root) / "session.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"project": str(root), "created": time.time(), "tasks": []}


def _save(root: Path, d: dict) -> None:
    d["tasks"] = d.get("tasks", [])[-KEEP_TASKS:]
    (_dir(root) / "session.json").write_text(json.dumps(d, indent=1), encoding="utf-8")


def log(root: Path, kind: str, **data: Any) -> None:
    """One event into events.jsonl (never raises: memory must not break the work)."""
    try:
        p = _dir(root) / "events.jsonl"
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": round(time.time(), 1), "kind": kind, **data}, ensure_ascii=False)[:4000] + "\n")
        if p.stat().st_size > 400_000:  # keep the newest half
            lines = p.read_text(encoding="utf-8").splitlines(True)
            p.write_text("".join(lines[len(lines) // 2:]), encoding="utf-8")
    except OSError:
        pass


def task_start(root: Path, task_id: str, goal: str) -> None:
    d = _load(root)
    d["tasks"].append({"id": task_id, "goal": goal[:500], "status": "running", "t": time.time(), "result": "",
                       "files": [], "notes": [], "tokens": 0})
    _save(root, d)
    log(root, "task_start", task=task_id, goal=goal[:300])


def task_end(root: Path, task_id: str, status: str, result: str, files: list[str], notes: list[str],
             tokens: int) -> None:
    d = _load(root)
    for t in reversed(d["tasks"]):
        if t["id"] == task_id:
            t.update(status=status, result=result[:500], files=sorted(set(files))[:30], notes=notes[-10:],
                     tokens=tokens, ended=time.time())
            break
    _save(root, d)
    log(root, "task_end", task=task_id, status=status, result=result[:300], tokens=tokens)


def recent(root: Path, n: int = 3, max_age_h: float = 24) -> list[dict]:
    """The last tasks of this project (newest last), for follow-ups."""
    now = time.time()
    return [t for t in _load(root).get("tasks", []) if now - float(t.get("t") or 0) < max_age_h * 3600][-n:]


def recap(root: Path) -> str:
    """The last tasks as a few lines for the agent's context ('it' / 'that' / 'make it grey' refer to these)."""
    tasks = recent(root)
    lines = []
    for i, t in enumerate(tasks):
        files = ", ".join(t.get("files") or []) or "no files"
        head = "THE LAST TASK (what 'it' / 'that' / 'too' / 'more' means): " if i == len(tasks) - 1 else "earlier: "
        lines.append(f"- {head}{t.get('goal', '')[:160]} -> {t.get('result', '')[:160] or '…'} ({files})")
    return "\n".join(lines)


def unfinished(root: Path) -> dict | None:
    """The last task when it didn't finish (stopped at the budget, cut off by a restart): 'continue' resumes it."""
    tasks = _load(root).get("tasks", [])
    last = tasks[-1] if tasks else None
    if last and last.get("status") in ("running", "stopped") and time.time() - float(last.get("t") or 0) < 24 * 3600:
        return last
    return None


def tokens(root: Path) -> int:
    return sum(int(t.get("tokens") or 0) for t in _load(root).get("tasks", []))


def last_events(root: Path, n: int = 30) -> list[dict]:
    try:
        lines = (_dir(root) / "events.jsonl").read_text(encoding="utf-8").splitlines()[-n:]
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out
