"""cancel_job: stop a running background job by id or title words (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="jobs", safety="safe", description="Cancel a background job by its id or words from its title.")
def cancel_job(job: str = "") -> str:
    """Cancel a background job.

    Args:
        job: Job id (e.g. "3") or words from its title (e.g. "nepal essay"); empty = the newest running job.
    """
    from jarvis.core import jobs

    j = jobs.get_manager().cancel(job)
    if j is None:
        return f"no job matches {job!r}" if job else "no running job"
    if j.status in ("done", "failed"):
        return f"job #{j.id} already {j.status}: {j.title}"
    return f"cancelled job #{j.id}: {j.title}"
