"""Per-project memory, in the project itself: .kurama/project.md (what it is, the stack, how to run it, each file's
job, the decisions made) and TODO.md (what is left). The agent reads these instead of re-reading the code, and
"continue the project" starts from TODO.md."""
from __future__ import annotations

import re
import time
from pathlib import Path

from coder.core.run import Run


def path(root: Path) -> Path:
    return root / ".kurama" / "project.md"


def read(root: Path, limit: int = 2500, with_map: bool = False) -> str:
    """The project card (without its Map section unless asked: the map is sent on its own, fresh)."""
    p = path(root)
    try:
        t = p.read_text(encoding="utf-8") if p.is_file() else ""
    except OSError:
        return ""
    if not with_map:
        t = re.sub(r"^## Map\b.*?(?=^## |\Z)", "", t, flags=re.M | re.S)
    return t[:limit]


def write(run: Run) -> None:
    """After a run: the project card, merged with what was there (decisions are appended, never lost)."""
    p = path(run.root)
    p.parent.mkdir(parents=True, exist_ok=True)
    old = read(run.root, 40000, with_map=True)
    decisions = re.findall(r"^- \d{4}-\d\d-\d\d: .+$", old, re.M)
    decisions.append(f"- {time.strftime('%Y-%m-%d')}: {run.request.strip()[:200]}"
                     + (f" ({run.scaffold})" if run.scaffold else ""))
    known = dict(re.findall(r"^- `([^`]+)`: (.*)$", old.split("## Decisions")[0], re.M))  # an addition keeps the
    known.update({f.path: f.purpose for f in run.files})  # files it didn't touch
    files = "\n".join(f"- `{k}`: {v}" for k, v in known.items())
    overview = section(old, "Overview") or run.notes.strip() or run.request.strip()
    from coder.memory import repomap
    p.write_text(
        f"# {run.plan_name or run.root.name}\n\n" + HEADER + f"\n\nStack: {run.stack or _old(old, 'Stack') or 'unknown'}\n\n"
        f"Run: `{run.run_cmd or _old(old, 'Run').strip('`') or '?'}`\n\n## Overview\n\n{overview}\n\n"
        f"## Files\n\n{files}\n\n## Map (functions, classes, ids per file; refreshed every run)\n\n"
        f"{repomap.text(run.root, 5000)}\n\n## Decisions\n\n" + "\n".join(decisions[-30:]) + "\n", encoding="utf-8")
    if run.kind != "new":  # an existing project's .gitignore is the owner's: never touched
        return
    try:  # a new project's .gitignore keeps the agent's folder out of git
        gi = run.root / ".gitignore"
        if not gi.exists() or ".kurama/" not in gi.read_text(encoding="utf-8"):
            with gi.open("a", encoding="utf-8") as fh:
                fh.write("\n.kurama/\n")
    except OSError:
        pass


HEADER = ("_KURAMA's card for this project: what it is, every file's job and what it defines. The coding agent reads "
          "this instead of the whole code; it is updated after every change it makes._")


def section(text: str, name: str) -> str:
    m = re.search(rf"^## {name}\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else ""


def readme(run: Run) -> None:
    """A README.md for every new project (0 tokens: from the plan) when the plan didn't write one."""
    p = run.root / "README.md"
    if run.kind != "new" or p.exists() or len(run.files) <= 2:  # a tiny program needs no README
        return
    files = "\n".join(f"- `{f.path}`: {f.purpose}" for f in run.files)
    p.write_text(f"# {run.plan_name or run.root.name}\n\n{run.request.strip()}\n\n"
                 + (f"## How it works\n\n{run.notes.strip()}\n\n" if run.notes.strip() else "")
                 + f"## Files\n\n{files}\n\n"
                 + (f"## Run\n\n```bash\n{run.run_cmd}\n```\n" if run.run_cmd else ""), encoding="utf-8")
    run.written.append("README.md")


def _old(text: str, field: str) -> str:
    m = re.search(rf"^{field}: (.+)$", text, re.M)
    return m.group(1).strip() if m else ""


def todo(root: Path) -> list[str]:
    p = root / "TODO.md"
    try:
        return re.findall(r"^\s*-\s*\[ \]\s*(.+)$", p.read_text(encoding="utf-8"), re.M) if p.is_file() else []
    except OSError:
        return []


def add_todo(root: Path, items: list[str]) -> None:
    if not items:
        return
    p = root / "TODO.md"
    old = p.read_text(encoding="utf-8") if p.is_file() else "# TODO\n\n"
    new = [i for i in items if i not in old]
    if new:
        p.write_text(old.rstrip() + "\n" + "".join(f"- [ ] {i}\n" for i in new), encoding="utf-8")


def tick(root: Path, item: str) -> None:
    """A TODO.md item done: '- [ ]' -> '- [x]'."""
    p = root / "TODO.md"
    try:
        t = p.read_text(encoding="utf-8")
    except OSError:
        return
    p.write_text(t.replace(f"- [ ] {item}", f"- [x] {item}", 1), encoding="utf-8")


def note_task(run: Run, goal: str, done: str, notes: list[str]) -> None:
    """After a task: the card gets a decision line and a fresh map (what each file defines now)."""
    p = path(run.root)
    old = read(run.root, 40000, with_map=True)
    if not old:
        return
    from coder.memory import repomap
    line = f"- {time.strftime('%Y-%m-%d')}: {goal.strip()[:160]}" + (f" -> {done.strip()[:160]}" if done else "")
    old = re.sub(r"(## Decisions\s*\n)", lambda m: m.group(1) + line + "\n", old, count=1) if "## Decisions" in old \
        else old.rstrip() + f"\n\n## Decisions\n\n{line}\n"
    old = re.sub(r"(## Map[^\n]*\n\n).*?(?=^## |\Z)", lambda m: m.group(1) + repomap.text(run.root, 5000) + "\n\n",
                 old, count=1, flags=re.M | re.S)
    p.write_text(old, encoding="utf-8")
