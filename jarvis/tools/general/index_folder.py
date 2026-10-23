"""index_folder: (re)index a folder of code/notes for search_knowledge/ask_knowledge, as a background job (safe)."""
from __future__ import annotations

from pathlib import Path

from jarvis.core.registry import tool


@tool(group="knowledge", safety="safe", description="Index a folder of code or notes (incremental, runs in the background) so it can be searched.")
def index_folder(path: str = "") -> str:
    """Index a folder.

    Args:
        path: Folder (or file) to index; empty = the configured roots (this project and ~/notes).
    """
    from jarvis.core import memory

    p = (path or "").strip()
    if p:
        target = Path(p).expanduser()
        if not target.exists():
            return f"error: no such folder: {p}"
        if target.resolve() in (Path("/"), Path.home().resolve()):
            return "error: that folder is too broad; pick a project or notes folder"
        job = memory.start_index_job(target.resolve())
    else:
        job = memory.start_index_job(None)
    return f"Indexing {job.title.removeprefix('index ')} in the background (job #{job.id}); only changed files are re-embedded."
