"""clipboard_history: recent text Jarvis copied (SQLite, no daemon); can copy an old item back. Safe."""
from __future__ import annotations

from jarvis.core import store
from jarvis.core.registry import tool
from jarvis.tools.general import _sys


@tool(group="clipboard", safety="safe", description="List text Jarvis copied recently, or copy item N back to the clipboard.")
def clipboard_history(limit: int = 5, restore: int = 0) -> str:
    """Jarvis's clipboard history (only text Jarvis itself copied).

    Args:
        limit: How many recent items to list (1-20).
        restore: Copy item N (1 = newest) back to the clipboard; 0 = just list.
    """
    limit = max(1, min(int(limit or 5), 20))
    rows = store.clip_recent(max(limit, int(restore or 0)))
    if not rows:
        return "no clipboard history yet (only text Jarvis copied is kept)"
    if restore:
        if not 1 <= int(restore) <= len(rows):
            return f"error: there is no item {restore}; history has {len(rows)}"
        text = rows[int(restore) - 1]["text"]
        try:
            _sys.clip_set(text)
        except _sys.SysError as e:
            return f"error: {e}"
        store.clip_add(text)
        return f"copied item {restore} back to the clipboard ({len(text)} characters)"
    items = [f"{i}) {' '.join(r['text'].split())[:80]}" for i, r in enumerate(rows[:limit], 1)]
    return "clipboard history: " + "; ".join(items)
