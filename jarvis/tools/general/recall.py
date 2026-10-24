"""recall: read back remembered notes (all, last, or matching a query) or, with which="profile", the facts
KURAMA learned about the user (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import store
from jarvis.core.registry import tool


def format_notes(notes: list[dict], total: int) -> str:
    """notes newest first -> numbered oldest-first list."""
    items = "; ".join(f"{i}) {n['text']}" for i, n in enumerate(reversed(notes), 1))
    more = f" (the last {len(notes)} of {total})" if total > len(notes) else ""
    word = "thing" if len(notes) == 1 else "things"
    return f"You asked me to remember {len(notes)} {word}{more}: {items}."


@tool(group="memory", safety="safe", description="Recall remembered notes (all, last, search) or what you know about the user (profile).")
def recall(which: Literal["all", "last", "search", "profile"] = "all", query: str = "", limit: int = 10) -> str:
    """Recall notes.

    Args:
        which: "all" (newest 10), "last" (most recent note), "search" (notes containing query) or "profile" (facts about the user).
        query: Text to look for when which is "search".
        limit: Max notes to return.
    """
    limit = max(1, min(int(limit or 10), 50))
    if which == "profile":
        from jarvis.core import profile
        return profile.describe(limit)
    if which == "last":
        notes = store.notes_recent(1)
        return f"The last thing you told me to remember: {notes[0]['text']}." if notes else \
            "You haven't asked me to remember anything yet."
    query = (query or "").strip()
    if which == "search" or query:
        notes = store.notes_recent(limit, query)
        if not notes:
            return f"I have no notes about {query!r}." if query else "error: give a query to search for"
        return format_notes(notes, len(notes))
    notes = store.notes_recent(limit)
    if not notes:
        return "You haven't asked me to remember anything yet."
    return format_notes(notes, store.notes_count())
