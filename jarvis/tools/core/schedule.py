"""schedule: reminders (alerts at a time), alarms, timers, the stopwatch, scheduled commands; list, cancel, move,
rename. To-dos are the separate todo tool. Safe dispatcher (scheduled commands still ask first)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.core._hub import Act, duration, run

TABLE = {
    "remind": Act("add_reminder", lambda a: {"text": a.get("text"), "when": a.get("when")}),
    "alarm": Act("set_alarm", lambda a: {"when": a.get("when"), "label": a.get("text", "")}),
    "timer": Act("set_timer", lambda a: {**duration(a.get("when", "")), "label": a.get("text", "")}),
    "stopwatch": Act("stopwatch", lambda a: {"action": a.get("item", "status")}),
    "list": Act("schedules", lambda a: {"action": "list"}),
    "cancel": Act("schedules", lambda a: {"action": "cancel", "item": a.get("item") or a.get("text")}),
    "move": Act("schedules", lambda a: {"action": "move", "item": a.get("item"), "when": a.get("when")}),
    "rename": Act("schedules", lambda a: {"action": "rename", "item": a.get("item"), "text": a.get("text")}),
    "run_later": Act("schedule_command", lambda a: {"command": a.get("text"), "when": a.get("when")}),
}


@tool(group="core", safety="safe",
      description="Alerts in time: remind (a reminder at a time), alarm (rings), timer (countdown), stopwatch; list, "
                  "cancel, move or rename one; run_later = KURAMA does a command later. Not for to-dos (use todo).")
def schedule(action: Literal["remind", "alarm", "timer", "stopwatch", "list", "cancel", "move", "rename", "run_later"],
             text: str = "", when: str = "", item: str = "") -> str:
    """Reminders, alarms, timers and the stopwatch.

    Args:
        action: remind, alarm, timer, stopwatch, list, cancel, move, rename, run_later.
        text: What to remind about / the alarm label / the new name / the command to run later.
        when: The time ('at 5 pm', 'tomorrow 6 am', 'every day at 8') or, for timer, the length ('5 minutes').
        item: Which reminder (id or words) for cancel/move/rename; stopwatch: start, stop, lap, reset, status.
    """
    return run(TABLE, {"action": action, "text": text, "when": when, "item": item})
