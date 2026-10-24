"""focus_app: bring an open app's window to the front via wmctrl (safe).

No longer a tool of its own: the merged tool calls focus_app() (old name kept as an alias)."""
from __future__ import annotations

from jarvis.tools.general import _apps


def focus_app(name: str) -> str:
    """Focus an app window.

    Args:
        name: The app's name or part of a window title, e.g. "vs code", "terminal", "chrome".
    """
    wins, label = _apps.match_windows(name)
    if not wins:
        return f"{label} isn't open (say 'open {label}' to start it)"
    _apps.wmctrl(["-i", "-a", wins[0]["id"]])
    return f"focused {label}"
