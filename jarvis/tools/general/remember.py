"""remember: save a short note the user dictates ("remember 1234") in SQLite (safe)."""
from __future__ import annotations

from jarvis.core import store
from jarvis.core.registry import tool

MAX_CHARS = 1000


@tool(group="memory", safety="safe", description="Save a short note or fact the user asks you to remember.")
def remember(text: str) -> str:
    """Remember something.

    Args:
        text: Exactly what to remember, e.g. "1234" or "the wifi password is on the fridge".
    """
    text = " ".join((text or "").split())[:MAX_CHARS]
    if not text:
        return "error: nothing to remember"
    note_id = store.note_add(text)
    return f"remembered (note {note_id}): {text}"
