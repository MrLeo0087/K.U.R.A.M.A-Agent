"""read_later: a reading list in an Excel sheet; save the highlighted link or the open page, list, open (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="browser", safety="safe", description="Reading list (Excel sheet): save the highlighted link or the page "
      "open in the browser for later, show the list, open item N (marks it read), mark read, remove.")
def read_later(action: Literal["add", "list", "last", "open", "read", "remove"] = "add", url: str = "", n: int = 0) -> str:
    """Read later list.

    Args:
        action: add (the highlighted link / the page open in the browser), list, last (the newest saved link),
            open (item n), read (mark n read), remove (item n).
        url: ONLY a link the user literally gave in their message; never invent one (empty = the open page).
        n: the item number from the list (1 = newest unread).
    """
    from jarvis.core import readlater

    return readlater.run(action, url, n)
