"""schedule_command: run a KURAMA command later or repeatedly (confirm: it acts unattended)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="schedule", safety="confirm",
      description="Make KURAMA RUN an action later or repeatedly (e.g. 'weather in Kathmandu' every day at 8, shut down at 11). "
      "NOT for tasks/work the user will do (reading, studying, calls): use add_reminder.")
def schedule_command(command: str, when: str) -> str:
    """Schedule a command.

    Args:
        command: The request to run, as the user would say it (e.g. "daily digest").
        when: Time phrase, e.g. "at 7 am", "in 1 hour", "every day at 8am", "every 30 minutes".
    """
    from jarvis.core import reminders

    return reminders.add(command, when, "command")
