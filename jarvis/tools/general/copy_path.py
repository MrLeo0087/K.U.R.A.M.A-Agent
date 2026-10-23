"""copy_path (P7c): copy a file or folder (asks first)."""
from __future__ import annotations

import shutil

from jarvis.core.registry import tool
from jarvis.tools.general import _files


@tool(group="files", safety="confirm", description="Copy a file or folder.")
def copy_path(source: str, destination: str) -> str:
    """Copy a file or folder (never overwrites).

    Args:
        source: Existing file or folder.
        destination: New path, or an existing folder to copy it into.
    """
    src, dst = _files.resolve(source), _files.resolve(destination)
    _files.guard(dst)
    if not src.exists():
        return f"error: {src} does not exist"
    if dst.is_dir():
        dst = dst / src.name
    if dst.exists():
        return f"error: {dst} already exists"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, symlinks=True)
    else:
        shutil.copy2(src, dst)
    return f"Copied {src} to {dst}"
