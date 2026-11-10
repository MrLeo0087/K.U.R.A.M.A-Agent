"""Study mode's one tool (group study_mode: offered only while Study mode is on)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="study_mode", safety="safe", max_chars=3000,
      description="Study mode: answer about the highlighted text in its page's context (explain, meaning here, "
                  "simpler, nepali, hindi, summary of the selection, page_summary, quiz, more = the long version of "
                  "the last answer, translate, write = a paragraph / essay from the page, ask = any other question "
                  "about it); save = put the last answer in the notes (only when asked); notes = today's saved "
                  "notes; glossary = the saved terms.")
def study(task: Literal["explain", "meaning", "simpler", "nepali", "hindi", "summary", "page_summary", "quiz", "more",
                        "translate", "write", "ask", "save", "notes", "glossary"] = "explain", request: str = "") -> str:
    """Study helper.

    Args:
        task: What to do with the selection / page.
        request: The student's own words (for ask / write / translate).
    """
    from jarvis.core import studymode
    if task == "notes":
        return studymode.notes_today()
    if task == "glossary":
        return studymode.glossary()
    return studymode.answer(task, request)
