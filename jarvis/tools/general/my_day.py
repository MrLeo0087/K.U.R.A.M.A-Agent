"""my_day: 'start my day' opens yesterday's tabs, VS Code project and music; 'done for today' saves them, snapshots
the project, sends a report to Telegram and (asks first) closes Brave + VS Code and sleeps the laptop (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="system", safety="safe",
      description="Start my day (open the saved tabs, VS Code project, music) or done for today (save them, "
                  "report to Telegram, then asks to close apps and sleep the laptop).")
def my_day(action: Literal["start", "done"] = "start") -> str:
    """Start or end the work day.

    Args:
        action: start or done.
    """
    from jarvis.core import day, safety
    return day.done(ask=safety.ask) if action == "done" else day.start()
