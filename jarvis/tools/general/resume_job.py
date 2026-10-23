"""resume_job: continue an interrupted writing job from its next section (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="jobs", safety="safe", description="Resume an interrupted or cancelled writing job from its next section.")
def resume_job(job: str) -> str:
    """Resume a writing job.

    Args:
        job: Job id (e.g. "3").
    """
    from jarvis.core import jobs

    return jobs.resume(job)
