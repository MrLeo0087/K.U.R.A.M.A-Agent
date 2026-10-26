"""goals: long tasks that last weeks or months: countdowns, daily check-ins, progress log, report (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="schedule", safety="safe", description="Long goals (weeks-months, Excel): exam countdown reminders, project "
      "daily check-in question + progress log, today's/week's summary, progress, edit, pause, done, formatted report.")
def goals(action: Literal["add", "list", "overview", "status", "today", "week", "log", "edit", "pause", "resume", "done", "delete",
                          "report", "link"] = "list", goal: str = "", name: str = "", end: str = "", remind: str = "",
          ask: str = "", ask_at: str = "", text: str = "", status: str = "", repo: str = "") -> str:
    """Long goals.

    Args:
        action: add (new goal), list, status (progress, days left), today / week (what was done), log (save a
            progress note), edit, pause, resume, done, delete, report (formatted report in its folder), link (git repo).
        goal: which existing goal (its name).
        name: the new goal's name (add) or a new name (edit), e.g. 'Physics exam', 'KURAMA app'.
        end: end date, e.g. 'in 30 days', 'in 6 months', 'November 28'.
        remind: reminder times, e.g. '7 am and 8 pm', 'twice a day', 'off'.
        ask: the daily check-in question ('yes' = the default one, 'off' = stop asking).
        ask_at: time of the check-in question, e.g. '9 pm'.
        text: the progress note (log).
        status: edit only: active, paused, done.
        repo: git folder (link); empty = the current coding project.
    """
    from jarvis.core import goals as g

    return g.run(action, goal, name, end, remind, ask, ask_at, text, status, repo)
