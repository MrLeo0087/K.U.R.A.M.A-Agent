"""job_result: where a background job saved its output, plus the first lines (safe).

No longer a tool of its own: the merged tool calls job_result() (old name kept as an alias)."""
from __future__ import annotations

from pathlib import Path



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
    from jarvis.core import longjobs
    if longjobs.is_long(j.id):  # long jobs: the last steps + tokens
        last = longjobs.steps(j.id, 5)
        head += f"; {j.tokens} tokens" + ("; steps: " + " | ".join(s["text"] for s in last) if last else "")
    if not j.output_path:
        return head + (f"; error: {j.error}" if j.error else "; no output yet")
    p = Path(j.output_path)
    text = p.read_text(encoding="utf-8")[:300] if p.exists() else "(file missing)"
    return f"{head}\npath: {p}\n{text}"
