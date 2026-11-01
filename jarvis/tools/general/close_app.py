"""close_app: close an app's windows gracefully via wmctrl (safe: like clicking X, the app still asks about
unsaved work; force-killing is kill_app, which needs a yes)."""
from __future__ import annotations

from jarvis.core.registry import tool
from jarvis.tools.general import _apps


@tool(group="apps", safety="safe", description="Close all open windows of an app by name (like clicking X).")
def close_app(name: str) -> str:
    """Close an app's windows.

    Args:
        name: The app's name or part of a window title, e.g. "vs code", "files", "firefox".
    """
    wins, label = _apps.match_windows(name)
    if not wins:
        return f"no open window matches {name!r}"
    from jarvis.core import safety, taskgraph
    before = taskgraph.windows_before()
    if before is not None:  # a step of a multi-step request: close only what the request opened
        new = [w for w in wins if w["id"] not in before]
        if new:
            for w in new:
                _apps.wmctrl(["-i", "-c", w["id"]])
            kept = len(wins) - len(new)
            return f"closed {len(new)} window(s) of {label} opened by this request" + \
                (f"; your other {kept} window(s) stay open" if kept else "")
        if not safety.ask(f"{label} was already open before this request (maybe with your work). Close it anyway?"):
            return f"Left {label} open: it was open before this request, and I only close what I opened."
    for w in wins:
        _apps.wmctrl(["-i", "-c", w["id"]])
    return f"closed {len(wins)} window(s) of {label}"
