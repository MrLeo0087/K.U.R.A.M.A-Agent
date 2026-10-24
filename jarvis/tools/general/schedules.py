"""schedules: list or cancel reminders and scheduled commands in one tool (safe).

Merged from list_schedules and cancel_schedule (their old names still work as aliases).
"""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import alias, tool
from jarvis.tools.general.cancel_schedule import cancel_schedule
from jarvis.tools.general.list_schedules import list_schedules


@tool(group="schedule", safety="safe",
      description="List pending reminders and scheduled commands, or cancel one by its id or words from it.")
def schedules(action: Literal["list", "cancel"] = "list", item: str = "") -> str:
    """Reminders and scheduled commands.

    Args:
        action: list = what is pending, cancel = cancel `item`.
        item: The id or words from the reminder to cancel.
    """
    if action == "cancel":
        return cancel_schedule(item)
    return list_schedules()


alias("list_schedules", "schedules", action="list")
alias("cancel_schedule", "schedules", action="cancel")
