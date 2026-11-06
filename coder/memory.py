"""Per-project memory, in the project itself: .kurama/project.md (what it is, the stack, how to run it, each file's
job, the decisions made) and TODO.md (what is left). The agent reads these instead of re-reading the code, and
"continue the project" starts from TODO.md."""
from __future__ import annotations

import re
import time
from pathlib import Path

from coder.run import Run


def path(root: Path) -> Path:
    return root / ".kurama" / "project.md"


def read(root: Path, limit: int = 2500) -> str:
    p = path(root)
    try:
        return p.read_text(encoding="utf-8")[:limit] if p.is_file() else ""
    except OSError:
        return ""


def write(run: Run) -> None:
    """After a run: the project card, merged with what was there (decisions are appended, never lost)."""
    p = path(run.root)
    p.parent.mkdir(parents=True, exist_ok=True)
    old = read(run.root, 20000)
    decisions = re.findall(r"^- \d{4}-\d\d-\d\d: .+$", old, re.M)
    decisions.append(f"- {time.strftime('%Y-%m-%d')}: {run.request.strip()[:200]}"
                     + (f" ({run.scaffold})" if run.scaffold else ""))
    files = "\n".join(f"- `{f.path}`: {f.purpose}" for f in run.files)
    p.write_text(
        f"# {run.plan_name or run.root.name}\n\nStack: {run.stack or 'unknown'}\n\nRun: `{run.run_cmd or '?'}`\n\n"
        f"## Files\n\n{files}\n\n## Decisions\n\n" + "\n".join(decisions[-30:]) + "\n"
        + (f"\n## Notes\n\n{run.notes.strip()}\n" if run.notes.strip() else ""), encoding="utf-8")
    if run.kind != "new":  # an existing project's .gitignore is the owner's: never touched
        return
    try:  # a new project's .gitignore keeps the agent's folder out of git
        gi = run.root / ".gitignore"
        if not gi.exists() or ".kurama/" not in gi.read_text(encoding="utf-8"):
            with gi.open("a", encoding="utf-8") as fh:
                fh.write("\n.kurama/\n")
    except OSError:
        pass


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
