"""clipboard: read, write or show the history of the clipboard in one tool (safe).

Merged from read_clipboard, write_clipboard and clipboard_history (their old names still work as aliases).
"""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import alias, tool
from jarvis.tools.general.clipboard_history import clipboard_history
from jarvis.tools.general.read_clipboard import read_clipboard
from jarvis.tools.general.write_clipboard import write_clipboard


@tool(group="clipboard", safety="safe",
      description="Clipboard: read what is on it, copy text to it, or list recent copies / restore item N.")
def clipboard(action: Literal["read", "write", "history"] = "read", text: str = "", max_chars: int = 0,
              limit: int = 5, restore: int = 0) -> str:
    """Use the clipboard.

    Args:
        action: read = what is on the clipboard now, write = copy `text` to it, history = recent copies.
        text: The text to copy (action=write).
        max_chars: Read at most this many characters (0 = default).
        limit: How many history items to list.
        restore: Copy history item N back to the clipboard (action=history).
    """
    if action == "write":
        return write_clipboard(text)
    if action == "history":
        return clipboard_history(limit, restore)
    return read_clipboard(max_chars)


alias("read_clipboard", "clipboard", action="read")
alias("write_clipboard", "clipboard", action="write")
alias("clipboard_history", "clipboard", action="history")
