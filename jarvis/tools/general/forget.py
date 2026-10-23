"""forget: delete remembered notes (the last one, all, or one by id) or one learned fact about the user (confirm)."""
from __future__ import annotations

from jarvis.core import store
from jarvis.core.registry import tool


@tool(group="memory", safety="confirm", description="Delete remembered notes (last, all, or by id) or a learned fact about the user.")
def forget(which: str = "last", fact: str = "") -> str:
    """Forget notes or a profile fact.

    Args:
        which: "last", "all", or a note id number (ignored when fact is given).
        fact: A learned fact to forget, e.g. "I live in Pokhara" or "favourite editor".
    """
    if (fact or "").strip():
        from jarvis.core import profile
        key = profile.find_key(fact)
        if not key:
            return f"error: I don't have a fact matching {fact!r}"
        value = store.profile_get(key)
        store.profile_delete(key)
        return f"forgot: {profile.render_fact({'key': key, 'value': value or ''})}"
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
