"""read_workspace: read back what is in the dashboard's Workspace card (the latest search result, answer, list...)
so KURAMA can summarize it or answer from it (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="self", safety="safe", max_chars=1500,
      description="Read what is in your Workspace (latest result first) to summarize it or answer from it.")
def read_workspace(item: int = 1) -> str:
    """Read one Workspace item.

    Args:
        item: 1 = the latest, 2 = the one before, ...
    """
    from jarvis.core import workspace
    got = workspace.read(max(1, int(item or 1)))
    if got is None:
        return "error: the workspace is empty."
    title, body = got
    return f"Workspace item: {title}\n{body}"
