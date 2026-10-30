"""move_path (P7c): move or rename a file or folder. Renaming in place never asks (nothing is lost, nothing is
overwritten); moving to another folder asks first."""
from __future__ import annotations

import shutil

from jarvis.core import safety
from jarvis.core.registry import tool
from jarvis.tools.general import _files


@tool(group="files", safety="safe", description="Move or rename a file or folder (never overwrites).")
def move_path(source: str, destination: str, rename: bool = False) -> str:
    """Move or rename a file or folder (never overwrites).

    Args:
        source: Existing file or folder.
        destination: New path, an existing folder to move it into, or (rename) just the new name.
        rename: True = give it a new name in the same folder ('rename Test to Old_test').
    """
    src = _files.resolve(source)
    _files.guard(src)
    if not src.exists():
        return f"error: {src} does not exist"
    new = (destination or "").strip().strip("\"'").rstrip("/")
    if not new:
        return "error: what should the new name or place be?"
    if rename or ("/" not in new and not new.startswith("~") and not _files.resolve(new).is_dir()):
        dst = src.parent / new  # a bare name = a rename in the same folder (never a fuzzy match elsewhere)
        if src.is_file() and not dst.suffix and src.suffix:
            dst = dst.with_suffix(src.suffix)  # 'rename report.pdf to final' -> final.pdf
    else:
        dst = _files.resolve(new, create=True)
        if dst.is_dir():
            dst = dst / src.name
    _files.guard(dst)
    if dst.exists():
        return f"error: {dst} already exists"
    if dst.parent != src.parent and not safety.ask(f"Should I move {src} to {dst.parent}?"):
        return "The user declined: nothing was moved."
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    from jarvis.core import focus
    focus.set_path(str(dst))  # follow-ups ('open it', 'send it') refer to it
    return f"Renamed {src.name} to {dst.name} ({dst.parent})" if dst.parent == src.parent else f"Moved {src} to {dst}"
