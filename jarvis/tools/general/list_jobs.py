"""list_jobs: what Jarvis is working on in the background (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="jobs", safety="safe", description="List background jobs and their status/progress.")
def list_jobs() -> str:
    from jarvis.core import jobs

    items = jobs.get_manager().list(8)
    if not items:
        return "no background jobs"
    return "\n".join(j.describe() for j in items)
