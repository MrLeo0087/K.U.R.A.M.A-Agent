"""organize_files: rename + sort a messy folder by what is inside the files. The plan is made in the BACKGROUND and
shown in the workspace; the user then says yes / no / what to change (the plan waits ORGANIZE_PLAN_TTL_S) (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="daily", safety="safe",
      description="Smart organize a messy folder (Downloads by default): plan in the background (real names for "
                  "files like IMG_2031, topic folders for documents), shown in the workspace; then apply it (yes), "
                  "change it (edit + what to change), cancel it (no), or undo the last run.")
def organize_files(action: Literal["organize", "apply", "edit", "cancel", "undo"] = "organize",
                   folder: str = "downloads", change: str = "", rename: bool = True) -> str:
    """Organize files.

    Args:
        action: organize (make a plan), apply (the waiting plan: the user said yes), edit (change the waiting
            plan as `change` says), cancel (the user said no), undo (the last organize).
        folder: The folder to organize (loose names work; default Downloads).
        change: For edit: what to change, e.g. "keep the pictures where they are".
        rename: Also give meaningless names real ones (False = only sort into folders).
    """
    from jarvis.core import organizer
    if action == "undo":
        return organizer.undo_last()
    if action == "apply":
        return organizer.apply_pending()
    if action == "cancel":
        return organizer.cancel_pending()
    if action == "edit":
        return organizer.edit_pending(change or "")
    from jarvis.core import focus
    from jarvis.core.paths import resolve_target
    pasted = focus.said_path()  # a folder path written in the message wins over a loose name ('organize this folder')
    if pasted is not None and pasted.is_dir() and not str(folder or "").startswith("/"):
        d = pasted
    elif folder and focus.is_anaphora(folder):  # 'organize it / this folder': the Files app's folder, else the last one
        d = focus.refer("this folder") or resolve_target("downloads")  # (a file found = its folder)
    else:
        d = resolve_target(folder or "downloads")
    if isinstance(d, str):
        return d
    if not d.is_dir():
        return f"error: {d} is not a folder"
    from jarvis.tools.general.send_file_telegram import too_broad
    if too_broad(d):
        return f"error: {d} is a whole home folder or disk; pick a folder like Downloads."
    return organizer.start(d, rename)
