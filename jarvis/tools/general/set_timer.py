"""set_timer: a countdown that rings (sound + notification) when it ends; kept in the schedule so it survives a
restart and can be listed/cancelled like reminders. Safe."""
from __future__ import annotations

import time
from datetime import datetime

from jarvis.core import store
from jarvis.core.registry import tool
from jarvis.tools.general.stopwatch import fmt


@tool(group="clock", safety="safe", description="Start a countdown timer that rings when it ends.")
def set_timer(minutes: float = 0, seconds: float = 0, hours: float = 0, label: str = "") -> str:
    """Set a timer.

    Args:
        minutes: Minutes.
        seconds: Seconds.
        hours: Hours.
        label: What it's for ("tea", "pasta"), optional.
    """
    total = float(hours or 0) * 3600 + float(minutes or 0) * 60 + float(seconds or 0)
    if total < 1:
        return "error: tell me how long (for example 5 minutes)"
    if total > 24 * 3600:
        return "error: timers go up to 24 hours; use an alarm for later"
    due = time.time() + total
    text = label.strip() or f"{fmt(total)} timer"
    sid = store.schedule_add(text, "timer", due)
    return f"Timer set for {fmt(total)} (rings at {datetime.fromtimestamp(due):%I:%M:%S %p}, #{sid})."
