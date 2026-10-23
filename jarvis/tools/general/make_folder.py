"""make_folder (P7c): create a folder (asks first outside the project roots)."""
from __future__ import annotations

from jarvis.core.registry import tool
from jarvis.tools.general import _files


@tool(group="files", safety="safe", description="Create a folder (and missing parent folders).")
def make_folder(path: str) -> str:
    """Create a folder.

    Args:
        path: Folder path (absolute, ~/..., or relative to home).
    """
    p = _files.resolve(path)
    _files.guard(p)
    if p.is_dir():
        return f"The folder {p} already exists."
    if p.exists():
        return f"error: {p} exists and is a file"
    if not _files.ask_outside(p, "create the folder"):
        return "The user declined: the folder was not created."
    p.mkdir(parents=True, exist_ok=True)
    return f"Created folder {p}"
