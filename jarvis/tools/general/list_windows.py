"""list_windows: the open windows (title and app) from wmctrl (safe, read-only)."""
from __future__ import annotations

from jarvis.core import config
from jarvis.core.registry import tool
from jarvis.tools.general import _apps
from jarvis.tools.interactive import _proc


@tool(group="windows", safety="safe", description="List the open windows (title and app).")
def list_windows() -> str:
    """List open windows."""
    try:
        wins = _apps.list_windows()
    except _proc.ProcError as e:
        return f"error: {e}"
    if not wins:
        return "no open windows"
    items = [f"{w['title'] or '(untitled)'} [{w['wmclass'].split('.')[-1]}]" for w in wins]
    out = f"{len(wins)} open windows: " + "; ".join(items)
    return out[: config.TOOL_OUTPUT_MAX_CHARS - 20]
