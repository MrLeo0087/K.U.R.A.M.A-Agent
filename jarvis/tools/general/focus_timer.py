"""focus_timer: a focus (pomodoro) session: Do Not Disturb on now, off + a reminder when time is up (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="daily", safety="safe",
      description="Start a focus/pomodoro session: silences notifications and reminds you when the time is up.")
def focus_timer(minutes: int = 25, task: str = "") -> str:
    """Focus session.

    Args:
        minutes: Length of the session, 5 to 180 (default 25).
        task: What you are focusing on (optional).
    """
    from jarvis.core import reminders
    from jarvis.tools.general import do_not_disturb

    m = max(5, min(int(minutes or 25), 180))
    dnd = do_not_disturb.do_not_disturb.func("on") if hasattr(do_not_disturb.do_not_disturb, "func") \
        else do_not_disturb.do_not_disturb("on")
    what = f" on {task}" if task else ""
    reminders.add(f"Focus session{what} is over. Time for a short break!", f"in {m} minutes", "reminder")
    reminders.add("turn off do not disturb", f"in {m} minutes", "command")
    quiet = "" if str(dnd).startswith("error") else " Notifications are silenced until then."
    return f"Focus mode on for {m} minutes{what}.{quiet} I'll tell you when it's time for a break."
