"""life: the owner's personal trackers: money (spending, budget, report), habits, long goals, studies (timetable,
notes, quiz, lecture recorder), the day's summary, token use (safe dispatcher)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.core._hub import Act, run

TABLE = {
    "spent": Act("expenses", lambda a: {"action": "add", "text": a.get("text")}),
    "money": Act("expenses", lambda a: {"action": "report", "period": a.get("period", "month")}),
    "budget": Act("expenses", lambda a: {"action": "budget", "text": a.get("text", "")}),
    "habit": Act("habits", lambda a: {"action": "add", "text": a.get("text")}),
    "habit_done": Act("habits", lambda a: {"action": "done", "text": a.get("text")}),
    "habits": Act("habits", lambda a: {"action": "status"}),
    "goals": Act("goals", lambda a: {"action": "overview" if not a.get("text") else "status", "goal": a.get("text", "")}),
    "add_goal": Act("goals", lambda a: {"action": "add", "name": a.get("text"), "end": a.get("period", "")}),
    "timetable": Act("timetable", lambda a: {"action": a.get("period", "today") if a.get("period") in ("today", "tomorrow", "week", "next") else "today"}),
    "notes": Act("study_notes", lambda a: {"action": "add" if a.get("text") else "show", "text": a.get("text", "")}),
    "quiz": Act("quiz", lambda a: {"action": "ask", "subject": a.get("text", "")}),
    "lecture": Act("lecture", lambda a: {"action": "stop" if (a.get("text") or "") == "stop" else "start"}),
    "day_summary": Act("daily_digest"),
    "tokens": Act("token_usage", lambda a: {"period": a.get("period", "today") if a.get("period") in ("today", "week", "month") else "today"}),
}


@tool(group="core", safety="safe",
      description="Personal trackers: spent (log spending), money (report), budget, habit (new), habit_done, habits, goals "
                  "(long tasks), add_goal, timetable (classes), notes (study notes), quiz, lecture (record), day_summary "
                  "(what we did today), tokens (AI usage).")
def life(action: Literal["spent", "money", "budget", "habit", "habit_done", "habits", "goals", "add_goal", "timetable", "notes",
                         "quiz", "lecture", "day_summary", "tokens"], text: str = "",
         period: str = "") -> str:
    """Life trackers.

    Args:
        action: What to do.
        text: What was spent ('500 on food'), the habit, the goal, the note, the quiz subject, or 'stop' (lecture).
        period: money/tokens: today, week, month; timetable: today, tomorrow, week, next; add_goal: when it ends.
    """
    return run(TABLE, {"action": action, "text": text, "period": period})
