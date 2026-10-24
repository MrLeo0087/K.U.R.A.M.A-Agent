"""timetable: save your class schedule once, then today/tomorrow/week/next class, with a heads-up before each class
(safe; 0 tokens after it is saved)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import study
from jarvis.core.registry import tool


@tool(group="study", safety="safe",
      description="Class timetable: save it (pasted text, one class per line), show today/tomorrow/the week, or the "
                  "next class; reminds before each class.")
def timetable(action: Literal["today", "tomorrow", "week", "next", "set"] = "today", text: str = "") -> str:
    """Timetable.

    Args:
        action: today, tomorrow, week, next, or set (save `text` as the timetable).
        text: The timetable, e.g. "Mon 9:00-10:00 DSA Room 201" per line (other layouts work too).
    """
    if action == "set":
        return study.set_timetable(text) if text.strip() else "error: paste the timetable"
    return study.show(action)
