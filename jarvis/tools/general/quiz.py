"""quiz: questions made once from your notes, asked again with spaced repetition (safe; making costs ~800 tokens,
asking and grading are free)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import study
from jarvis.core.registry import tool


@tool(group="study", safety="safe",
      description="Study quiz from the user's notes with spaced repetition: make questions for a subject, ask the next "
                  "due one, show its answer, grade it (right/wrong), or stats.")
def quiz(action: Literal["ask", "make", "answer", "right", "wrong", "stats"] = "ask", subject: str = "") -> str:
    """Quiz.

    Args:
        action: ask = next due question; make = new questions from `subject` notes; answer = show the answer;
            right / wrong = how it went; stats = progress.
        subject: e.g. "DSA" (empty = any).
    """
    if action == "make":
        return study.make(subject) if subject.strip() else "error: from which subject's notes?"
    if action == "answer":
        return study.answer()
    if action in ("right", "wrong"):
        return study.grade(action == "right")
    if action == "stats":
        return study.stats()
    return study.ask(subject)
