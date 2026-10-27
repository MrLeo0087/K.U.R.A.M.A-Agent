"""time_machine: snapshots of your code you never have to think about. What changed since a time, the history of
a file, put a file back as it was, protect a new project (safe; restoring asks first).

Diffs are plain git output (0 tokens).
"""
from __future__ import annotations

from typing import Literal

from jarvis.core import safety, timemachine as tm
from jarvis.core.registry import tool


@tool(group="git", safety="safe", max_chars=2500,
      description="Code time machine (automatic snapshots, even uncommitted): what changed since a time ('2 hours "
                  "ago', 'yesterday'), history of a file, restore a file as it was then, undo a restore, protect a "
                  "project, snapshot now.")
def time_machine(action: Literal["changes", "history", "restore", "undo", "protect", "snapshot", "list", "pin", "unpin",
                                 "forget", "watch"] = "changes",
                 project: str = "", when: str = "1 hour ago", file: str = "") -> str:
    """Code time machine.

    Args:
        action: changes = diff since `when`; history = snapshots (of `file`); restore = put `file` back as it was at
            `when` (asks first); undo = undo the last restore; protect = start snapshotting `project`;
            snapshot = save one now; list = watched projects; pin = always show `project` on the Coding card;
            unpin = automatic again; forget = stop watching `project` (code untouched); watch = watch it again.
        project: Project folder (loose names work); empty = the one you changed most recently.
        when: A time like "2 hours ago", "yesterday 18:00", "this morning", or a snapshot id.
        file: A file inside the project, e.g. "train.py" or "src/model.py".
    """
    try:
        if action == "list":
            return tm.overview()
        if action == "pin":
            return tm.pin(project)
        if action == "unpin":
            return tm.unpin()
        if action == "forget":
            return tm.forget(project)
        if action == "watch":
            return tm.unforget(project)
        if action == "undo":
            return tm.undo()
        if action == "protect":  # 'watch the project at <path>' / 'watch this project' (= the folder open in VS Code)
            if project.strip() and project.strip().lower() not in ("this", "it", "this project", "current"):
                p = tm.resolve(project)
            else:
                p = tm.vscode_folder()
                if p is None:
                    return "Which folder? Say 'watch the project at /path/to/folder'."
            return tm.add_project(p)
        p = tm.resolve(project)
        if action == "snapshot":
            return tm.snapshot(p, "manual")
        if action == "history":
            return tm.history(p, file)
        if action == "restore":
            if not file:
                return "error: which file should I put back?"
            if not safety.ask(f"Put {file} in {p.name} back as it was {when}? (Your current version is kept.)"):
                return "The user said no, so nothing was changed."
            return tm.restore(p, file, when)
        return tm.diff(p, when, file)
    except tm.TMError as e:
        return f"error: {e}"

