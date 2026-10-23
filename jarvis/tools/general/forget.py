"""forget: delete remembered notes: the last one, all, or one by id (confirm)."""
from __future__ import annotations

from jarvis.core import store
from jarvis.core.registry import tool


@tool(group="memory", safety="confirm", description="Delete remembered notes: the last one, all of them, or one by note id.")
def forget(which: str = "last") -> str:
    """Forget notes.

    Args:
        which: "last", "all", or a note id number.
    """
    w = (which or "last").strip().lower().lstrip("#")
    if w == "all":
        return f"forgot {store.notes_clear()} note(s)"
    if w == "last":
        notes = store.notes_recent(1)
        if not notes:
            return "there are no notes to forget"
        store.note_delete(notes[0]["id"])
        return f"forgot: {notes[0]['text']}"
    if w.isdigit():
        return f"forgot note {w}" if store.note_delete(int(w)) else f"error: no note with id {w}"
    return "error: which must be 'last', 'all' or a note id"
