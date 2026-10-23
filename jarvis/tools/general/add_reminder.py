"""add_reminder: remind the user at a time, once or repeating (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="schedule", safety="safe",
      description="Set a reminder at a time (once or repeating); alerts on desktop, Telegram and by voice.")
def add_reminder(text: str, when: str) -> str:
    """Set a reminder.

    Args:
        text: What to remind about (e.g. "call mom").
        when: Time phrase, e.g. "at 5 pm", "in 20 minutes", "tomorrow at 9", "every weekday at 9:30".
    """
    from jarvis.core import reminders

    return reminders.add(text, when, "reminder")
