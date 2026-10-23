"""move_path (P7c): move or rename a file or folder (asks first)."""
from __future__ import annotations

import shutil

from jarvis.core.registry import tool
from jarvis.tools.general import _files


@tool(group="files", safety="confirm", description="Move or rename a file or folder.")
def move_path(source: str, destination: str) -> str:
    """Move or rename a file or folder (never overwrites).

    Args:
        source: Existing file or folder.
        destination: New path, or an existing folder to move it into.
    """
    src, dst = _files.resolve(source), _files.resolve(destination)
    _files.guard(src)
    _files.guard(dst)
    if not src.exists():
        return f"error: {src} does not exist"
    if dst.is_dir():
        dst = dst / src.name
    if dst.exists():
        return f"error: {dst} already exists"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return f"Moved {src} to {dst}"
