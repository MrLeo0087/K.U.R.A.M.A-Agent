"""study_notes: quick study notes filed by subject and date (~/Notes/<Subject>/), and showing them again (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import notes
from jarvis.core.registry import tool


@tool(group="study", safety="safe",
      description="Study notes: save a note under a subject (auto-picked if not said) in ~/Notes, show the notes of a "
                  "subject for the last N days, or list subjects.")
def study_notes(action: Literal["add", "show", "subjects"] = "add", text: str = "", subject: str = "",
                days: int = 7) -> str:
    """Study notes.

    Args:
        action: add = save `text`; show = notes of `subject` (or all) for the last `days`; subjects = list them.
        text: The note.
        subject: e.g. "DSA", "Machine Learning" (empty = picked from your subjects).
        days: How far back to show.
    """
    if action == "show":
        return notes.show(subject, days)
    if action == "subjects":
        return ", ".join(notes.subjects()) or "No subjects yet: notes go to General until you name one."
    return notes.add(text, subject)
