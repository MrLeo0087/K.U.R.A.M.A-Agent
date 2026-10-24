"""write_clipboard: put text on the clipboard (xclip) and keep it in KURAMA's own history (safe).

No longer a tool of its own: the merged tool calls write_clipboard() (old name kept as an alias)."""
from __future__ import annotations

from jarvis.core import store
from jarvis.tools.general import _sys

MAX_CHARS = 100_000


def write_clipboard(text: str) -> str:
    """Copy text to the clipboard.

    Args:
        text: Exactly the text to copy.
    """
    if not text:
        return "error: nothing to copy"
    text = text[:MAX_CHARS]
    try:
        _sys.clip_set(text)
    except _sys.SysError as e:
        return f"error: {e}"
    store.clip_add(text)
    return f"copied {len(text)} characters to the clipboard"
