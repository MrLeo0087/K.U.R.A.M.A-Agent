"""delete_to_trash (P7c): move a file or folder to the trash with `gio trash` (asks first; never rm -rf)."""
from __future__ import annotations

from jarvis.core.registry import tool
from jarvis.tools.general import _files


@tool(group="files", safety="confirm", description="Move a file or folder to the trash (can be restored).")
def delete_to_trash(path: str) -> str:
    """Move a file or folder to the trash.

    Args:
        path: File or folder to delete.
    """
    p = _files.resolve(path)
    _files.guard(p)
    if not p.exists():
        return f"error: {p} does not exist"
    _files.trash(p)
    return f"Moved {p} to the trash"
