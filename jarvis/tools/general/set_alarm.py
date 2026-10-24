"""set_alarm: an alarm at a time ("6 am", "tomorrow at 7", "every weekday at 6:30") that rings for a while and
also reaches the phone. Safe."""
from __future__ import annotations

from jarvis.core import reminders
from jarvis.core.registry import tool


@tool(group="clock", safety="safe", description="Set an alarm at a time (rings with sound; can repeat daily/weekdays).")
def set_alarm(when: str, label: str = "") -> str:
    """Set an alarm.

    Args:
        when: The time, e.g. "6 am", "tomorrow at 7:30", "every day at 6", "every weekday at 6:30".
        label: What it's for, optional ("go for a walk").
    """
    out = reminders.add(label.strip() or "Alarm", when if when.strip().lower().startswith(("at ", "in ", "every", "tomorrow", "today", "on ")) else f"at {when}", kind="alarm")
    return out.replace("reminder", "alarm")
