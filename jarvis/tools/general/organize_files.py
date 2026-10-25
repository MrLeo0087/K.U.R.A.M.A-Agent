"""organize_files: rename + sort a messy folder by what is inside the files; asks first, undo-able (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="daily", safety="safe",
      description="Smart organize a messy folder (Downloads by default): give files with meaningless names "
                  "(IMG_2031, doc(3)) real names from their content and sort into type/topic folders. Shows the plan "
                  "and asks first; 'undo' puts everything back.")
def organize_files(action: Literal["organize", "preview", "undo"] = "organize", folder: str = "downloads",
                   rename: bool = True) -> str:
    """Organize files.

    Args:
        action: organize (plan, ask, apply), preview (plan only) or undo (the last run).
        folder: The folder to organize (loose names work; default Downloads).
        rename: Also give meaningless names real ones (False = only sort into folders).
    """
    from jarvis.core import organizer, safety
    if action == "undo":
        return organizer.undo_last()
    from jarvis.core.paths import resolve_target
    d = resolve_target(folder or "downloads")
    if isinstance(d, str):
        return d
    if not d.is_dir():
        return f"error: {d} is not a folder"
    from jarvis.tools.general.send_file_telegram import too_broad
    if too_broad(d):
        return f"error: {d} is a whole home folder or disk; pick a folder like Downloads."
    moves = organizer.plan(d, rename)
    if not moves:
        return f"{d.name} already looks organized."
    shown = organizer.describe(moves, d)
    if action == "preview":
        return f"Plan for {d.name} ({len(moves)} files):\n{shown}"
    if not safety.ask(f"Organize {len(moves)} files in {d.name}?\n{shown}"):
        return "Okay, nothing was moved."
    organizer.apply(moves)
    from jarvis.core import focus
    focus.set_path(d)
    return f"Organized {len(moves)} files in {d.name}. Say 'undo organize' to put them back."
