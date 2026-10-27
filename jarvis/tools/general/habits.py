"""habits: daily habits with streaks in ~/Documents/KURAMA/habits.xlsx, 0 tokens (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="tracker", safety="safe", description="Daily habits with streaks: add a habit (name, target per day, "
      "reminder time), check in ('I drank water'), status (streaks, what's left today), undo today's check-in, delete.")
def habits(action: Literal["status", "add", "done", "undo", "delete"] = "status", text: str = "") -> str:
    """Habit tracker.

    Args:
        action: status, add (text = 'drink water 8 glasses a day remind me at 10 am'), done (text = what the user did),
            undo (text = the habit), delete (text = the habit).
        text: The user's words.
    """
    from jarvis.core import habits as hb

    if action == "add":
        return hb.add(*hb.parse_new(text))
    if action == "done":
        return hb.check_in(text) or "Which habit? " + (", ".join(hb.names()) or "You have no habits yet.")
    if action == "undo":
        return hb.undo(text)
    if action == "delete":
        return hb.delete(text)
    return hb.status_text()
