"""read_later: my list = to-dos + links to read later (Excel sheet), with tags and optional due times (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="browser", safety="safe", description="My list (to-dos + read later, Excel): add the highlighted link/open "
      "page or a to-do, optional tag and time (reminds 10 min before + at the time), list, done N (removes it), open N.")
def read_later(action: Literal["add", "todo", "list", "last", "open", "done", "remove", "clear", "today", "ask", "reschedule", "rename"] = "add", url: str = "",
               n: int = 0, text: str = "", tag: str = "", when: str = "") -> str:
    """My list.

    Args:
        action: add (the highlighted link / the page open in the browser), todo (add the task in text), list,
            last (the newest saved link), open (link n), done (item n finished: removed), remove (item n, or the item
            named in text), clear (every to-do + reminder; text 'read' = the reading list), today (to-do + classes
            + long tasks), reschedule (item named in text -> new time in when), rename (text 'old » new').
        url: ONLY a link the user literally gave in their message; never invent one (empty = the open page).
        n: the item number from the list.
        text: the to-do task (action todo); for list: 'todo' or 'read' shows only that part.
        tag: optional tag, e.g. work, study, shopping.
        when: optional time, e.g. 'in 2 hours', 'at 2 pm', 'tomorrow 2 pm', 'November 28 5 pm'.
    """
    from jarvis.core import readlater

    return readlater.run(action, url, n, text, tag, when)
