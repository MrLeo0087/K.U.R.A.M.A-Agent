"""recall_session: what we talked about in past sessions (last / yesterday / a date / a topic), zero LLM (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="memory", safety="safe", description="Recall past conversations: the last session, a day (yesterday, a weekday, YYYY-MM-DD) or a topic.")
def recall_session(query: str = "last") -> str:
    """Recall past chats.

    Args:
        query: "last", "today", "yesterday", a weekday, a date like 2026-10-22, or words to search for.
    """
    from jarvis.core import episodes

    return episodes.recall(query or "last")
