"""list_schedules: pending reminders and scheduled commands (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="schedule", safety="safe", description="List pending reminders and scheduled commands.")
def list_schedules() -> str:
    from jarvis.core import reminders

    return reminders.list_text()
