"""write_document: start a long writing job (essay, article, story, report, code) in the background (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="jobs", safety="safe",
      description="Write a long essay/article/story/report or code file in the background; returns a job id at once.")
def write_document(request: str) -> str:
    """Start a background writing job.

    Args:
        request: The full writing request, including topic and length (e.g. "a 1000-word essay about Nepal").
    """
    from jarvis.core import jobs, planner

    job = jobs.start_task(request, lang=planner.detect_lang(request))
    return f"started job #{job.id}: {job.title} (writing in the background, saved under data/outputs)"
