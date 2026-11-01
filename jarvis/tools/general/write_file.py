"""write_file (P7c): write a text file (asks first only to overwrite an existing one)."""
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
    if path.lower().rsplit(".", 1)[-1] in ("png", "jpg", "jpeg", "gif", "webp", "bmp", "mp3", "mp4", "wav", "pdf", "zip"):
        # text can't make a real picture / sound / pdf ("generate a random image" wrote a 1-pixel base64 PNG, 11-01)
        return ("error: write_file only writes text. For a picture use the create tool (action image); for audio "
                "create (audio); for a PDF write the text, then convert it.")
    p = _files.resolve(path, create=True)
    _files.guard(p)
    if p.is_dir():
        return f"error: {p} is a folder"
    if p.exists():
        # one yes/no box (the old "ask the user, then call again with overwrite=true" looped: the general files
        # tool can't pass overwrite, so every "yes" asked again)
        if not safety.ask(f"Should I overwrite the existing file {p}?"):
            return "The user declined: the file was not overwritten."
    p.parent.mkdir(parents=True, exist_ok=True)  # a NEW file never asks: nothing is lost
    p.write_text(content[:MAX_CHARS], encoding="utf-8")
    from jarvis.core import focus
    focus.set_path(str(p))  # follow-ups ('open it', 'send it') refer to it
    return f"Wrote {len(content[:MAX_CHARS])} characters to {p}"
