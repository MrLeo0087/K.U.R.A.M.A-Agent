"""cancel_schedule: cancel a reminder / scheduled command by id or words (safe).

No longer a tool of its own: the merged tool calls cancel_schedule() (old name kept as an alias)."""
from __future__ import annotations



def cancel_schedule(item: str) -> str:
    """Cancel a reminder.

    Args:
        item: Reminder id (e.g. "3") or words from its text (e.g. "call mom").
    """
    from jarvis.core import reminders

    return reminders.cancel(item)
