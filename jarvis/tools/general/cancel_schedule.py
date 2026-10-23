"""cancel_schedule: cancel a reminder / scheduled command by id or words (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="schedule", safety="safe", description="Cancel a reminder or scheduled command by its id or words from it.")
def cancel_schedule(item: str) -> str:
    """Cancel a reminder.

    Args:
        item: Reminder id (e.g. "3") or words from its text (e.g. "call mom").
    """
    from jarvis.core import reminders

    return reminders.cancel(item)
