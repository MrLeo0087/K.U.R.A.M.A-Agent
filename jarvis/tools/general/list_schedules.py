"""list_schedules: pending reminders and scheduled commands (safe).

No longer a tool of its own: the merged tool calls list_schedules() (old name kept as an alias)."""
from __future__ import annotations



def list_schedules() -> str:
    from jarvis.core import reminders

    return reminders.list_text()
