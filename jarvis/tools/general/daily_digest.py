"""daily_digest: the day's digest on demand: conversations, jobs, alerts, notes, tokens, git, weather (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="usage", safety="safe", description="Give the daily digest (conversations, jobs, alerts, notes, tokens, git commits, weather).")
def daily_digest(date: str = "today") -> str:
    """Daily digest.

    Args:
        date: "today", "yesterday", a weekday or YYYY-MM-DD.
    """
    from jarvis.core import digest

    return digest.build_digest(date or "today")
