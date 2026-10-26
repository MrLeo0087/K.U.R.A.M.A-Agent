"""clipboard_history: what was copied in the last 24 h (the clipboard_watch worker records every copy; SQLite, only
on this laptop): list, search by words, 'N minutes ago', copy an old item back, clear. Safe.

No longer a tool of its own: the merged tool calls clipboard_history() (old name kept as an alias)."""
from __future__ import annotations

import time

from jarvis.core import store
from jarvis.tools.general import _sys


_shown: dict = {"rows": [], "at": 0.0}  # the last list shown: "copy back number 2" means ITS item 2


def _ago(ts: float) -> str:
    m = int((time.time() - ts) // 60)
    return "just now" if m < 1 else f"{m} min ago" if m < 60 else f"{m // 60} h ago"


def clipboard_history(limit: int = 5, restore: int = 0, query: str = "", minutes_ago: float = 0,
                      clear: bool = False) -> str:
    """Copy history.

    Args:
        limit: How many items to list (1-20).
        restore: Copy item N of this list back to the clipboard; 0 = just list.
        query: Only copies containing these words ('link', 'github', 'password' is never kept).
        minutes_ago: The copies nearest to that many minutes ago.
        clear: Forget the whole history.
    """
    if clear:
        n = store.clip_clear()
        return f"Forgot {n} copied items."
    limit = max(1, min(int(limit or 5), 20))
    words = [w for w in query.lower().split() if w not in ("the", "a", "text", "thing", "one", "stuff")]
    want_link = any(w in ("link", "links", "url", "urls", "website") for w in words)
    words = [w for w in words if w not in ("link", "links", "url", "urls", "website")]
    rows = store.clip_search(" ".join(words), float(minutes_ago or 0), 200 if want_link else max(limit, int(restore or 0)))
    if want_link:
        rows = [r for r in rows if "http" in r["text"] or "www." in r["text"]][: max(limit, int(restore or 0))]
    if not rows:
        return ("Nothing like that was copied in the last 24 hours." if query or minutes_ago
                else "Nothing copied yet (I keep what you copy for 24 hours).")
    if restore and not (query or minutes_ago) and _shown["rows"] and time.time() - _shown["at"] < 900:
        rows = _shown["rows"]
    if restore:
        if not 1 <= int(restore) <= len(rows):
            return f"There's no item {restore}; I found {len(rows)}."
        text = rows[int(restore) - 1]["text"]
        try:
            _sys.clip_set(text)
        except _sys.SysError as e:
            return f"error: {e}"
        return f"Copied it back ({len(text)} characters): {' '.join(text.split())[:80]}"
    if minutes_ago and not query:
        r = rows[0]
        return f"Around then ({_ago(r['created'])}) you copied:\n{r['text'][:1500]}"
    _shown.update(rows=rows[:limit], at=time.time())
    items = [f"{i}. {' '.join(r['text'].split())[:90]} ({_ago(r['created'])})" for i, r in enumerate(rows[:limit], 1)]
    return "Copied:\n" + "\n".join(items) + "\n(Say 'copy back number 2' to copy one again.)"
