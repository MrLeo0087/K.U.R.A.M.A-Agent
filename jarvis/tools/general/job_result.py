"""job_result: where a background job saved its output, plus the first lines (safe)."""
from __future__ import annotations

from pathlib import Path

from jarvis.core.registry import tool


@tool(group="jobs", safety="safe", description="Show a background job's output file path and its beginning.")
def job_result(job_id: int) -> str:
    """Get a job's result.

    Args:
        job_id: The job id.
    """
    from jarvis.core import jobs

    j = jobs.get_manager().get(job_id)
    if j is None:
        return f"no job #{job_id}"
    head = f"job #{j.id} {j.status}: {j.title}"
    if j.progress and j.status in jobs.ACTIVE:
        head += f" ({j.progress})"
    if not j.output_path:
        return head + (f"; error: {j.error}" if j.error else "; no output yet")
    p = Path(j.output_path)
    text = p.read_text(encoding="utf-8")[:300] if p.exists() else "(file missing)"
    return f"{head}\npath: {p}\n{text}"
