"""list_jobs: what KURAMA is working on in the background (safe).

No longer a tool of its own: the merged tool calls list_jobs() (old name kept as an alias)."""
from __future__ import annotations



def list_jobs() -> str:
    from jarvis.core import jobs

    items = jobs.get_manager().list(8)
    if not items:
        return "no background jobs"
    return "\n".join(j.describe() for j in items)
