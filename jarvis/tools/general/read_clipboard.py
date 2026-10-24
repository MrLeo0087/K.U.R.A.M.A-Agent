"""read_clipboard: the current clipboard text, truncated (xclip; safe, read-only).

No longer a tool of its own: the merged tool calls read_clipboard() (old name kept as an alias)."""
from __future__ import annotations

from jarvis.core import config
from jarvis.tools.general import _sys


def read_clipboard(max_chars: int = 0) -> str:
    """Read the clipboard.

    Args:
        max_chars: Return at most this many characters (default 500).
    """
    try:
        text = _sys.clip_get()
    except _sys.SysError as e:
        return f"error: {e}"
    if not text.strip():
        return "the clipboard is empty (or holds no text)"
    limit = max(1, min(int(max_chars or config.CLIPBOARD_READ_MAX), config.CLIPBOARD_READ_MAX))
    more = f" (first {limit} shown)" if len(text) > limit else ""
    return f"clipboard ({len(text)} chars{more}): {text[:limit]}"
