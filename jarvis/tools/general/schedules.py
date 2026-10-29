"""schedules: list or cancel reminders and scheduled commands in one tool (safe).

Merged from list_schedules and cancel_schedule (their old names still work as aliases).
"""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import alias, tool
from jarvis.tools.general.cancel_schedule import cancel_schedule
from jarvis.tools.general.list_schedules import list_schedules


@tool(group="schedule", safety="safe",
      description="List pending reminders, alarms and scheduled commands; cancel, move (new time) or rename one.")
def schedules(action: Literal["list", "cancel", "move", "rename"] = "list", item: str = "", when: str = "",
              text: str = "") -> str:
    """Reminders, alarms and scheduled commands (to-dos are the separate todo tool).

    Args:
        action: list = what is pending, cancel / move / rename `item`.
        item: The id or words from the reminder.
        when: The new time (move), e.g. "6 pm", "tomorrow at 9".
        text: The new wording (rename).
    """
    from jarvis.core import reminders
    if action == "cancel":
        return cancel_schedule(item)
    if action == "move":
        return reminders.move(item, when)
    if action == "rename":
        return reminders.rename(item, text)
    return list_schedules()


alias("list_schedules", "schedules", action="list")
alias("cancel_schedule", "schedules", action="cancel")
