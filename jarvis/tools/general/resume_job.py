"""resume_job: continue an interrupted writing job from its next section (safe).

No longer a tool of its own: the merged tool calls resume_job() (old name kept as an alias)."""
from __future__ import annotations



def resume_job(job: str) -> str:
    """Resume a writing job.

    Args:
        job: Job id (e.g. "3").
    """
    from jarvis.core import jobs

    return jobs.resume(job)
