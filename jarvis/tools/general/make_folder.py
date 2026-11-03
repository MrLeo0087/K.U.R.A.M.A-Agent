"""make_folder (P7c): create a folder. Creating never asks (nothing is lost); system folders are refused."""
from __future__ import annotations

from jarvis.core.registry import tool
from jarvis.tools.general import _files


@tool(group="files", safety="safe", description="Create a folder (and missing parent folders).")
def make_folder(path: str) -> str:
    """Create a folder.

    Args:
        path: Folder path (absolute, ~/..., or relative to home).
    """
    p = _files.resolve(path, create=True)
    _files.guard(p)
    if p.is_dir():
        return f"The folder {p} already exists."
    if p.exists():
        return f"error: {p} exists and is a file"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return f"error: couldn't create {p}: {e.strerror or e}"
    from jarvis.core import focus
    focus.set_path(str(p))  # follow-ups ('open it', 'send it') refer to it
    try:  # the new folder is "that folder / here" for the next request or step ('then open that folder in vs code'
        from jarvis.core import focus  # opened the folder from before, 11-04)
        focus.set_path(str(p))
    except Exception:  # noqa: BLE001
        pass
    return f"Created folder {p}"
