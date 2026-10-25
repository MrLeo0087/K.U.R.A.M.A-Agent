"""write_file (P7c): write a text file (asks first to overwrite or outside the project roots)."""
from __future__ import annotations

from jarvis.core import safety
from jarvis.core.registry import tool
from jarvis.tools.general import _files

MAX_CHARS = 200_000


@tool(group="files", safety="safe",
      description="Create or write a text file with the given content (makes missing folders).")
def write_file(path: str, content: str = "", overwrite: bool = False) -> str:
    """Write a text file.

    Args:
        path: File path (absolute, ~/..., or relative to home).
        content: Text to write.
        overwrite: Replace the file if it already exists.
    """
    p = _files.resolve(path)
    _files.guard(p)
    if p.is_dir():
        return f"error: {p} is a folder"
    if p.exists():
        if not overwrite:
            return f"error: {p} already exists; ask the user, then call again with overwrite=true"
        if not safety.ask(f"Should I overwrite the existing file {p}?"):
            return "The user declined: the file was not overwritten."
    elif not _files.ask_outside(p, "write the file"):
        return "The user declined: the file was not written."
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content[:MAX_CHARS], encoding="utf-8")
    from jarvis.core import focus
    focus.set_path(str(p))  # follow-ups ('open it', 'send it') refer to it
    return f"Wrote {len(content[:MAX_CHARS])} characters to {p}"
