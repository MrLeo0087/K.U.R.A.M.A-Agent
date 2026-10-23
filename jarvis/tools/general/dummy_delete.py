"""dummy_delete: proves the confirm flow. It never deletes anything."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="files", safety="confirm", description="Delete a file or folder (demo: deletes nothing).")
def dummy_delete(path: str, recursive: bool = False) -> str:
    """Pretend to delete a path.

    Args:
        path: File or folder to delete.
        recursive: Also delete folder contents.
    """
    what = "folder and its contents" if recursive else "path"
    return f"[dry run] would delete {what}: {path} (nothing was deleted)"
