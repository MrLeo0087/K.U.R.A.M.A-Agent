"""close_app: close an app's windows gracefully via wmctrl (confirm: may lose unsaved work)."""
from __future__ import annotations

from jarvis.core.registry import tool
from jarvis.tools.general import _apps


@tool(group="apps", safety="confirm", description="Close all open windows of an app by name (may lose unsaved work).")
def close_app(name: str) -> str:
    """Close an app's windows.

    Args:
        name: The app's name or part of a window title, e.g. "vs code", "files", "firefox".
    """
    wins, label = _apps.match_windows(name)
    if not wins:
        return f"no open window matches {name!r}"
    for w in wins:
        _apps.wmctrl(["-i", "-c", w["id"]])
    return f"closed {len(wins)} window(s) of {label}"
