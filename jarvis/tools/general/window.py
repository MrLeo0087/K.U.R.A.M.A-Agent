"""window: list open windows, switch to one, or snap/maximize/minimize one (safe).

Merged from list_windows, focus_app and snap_window (their old names still work as aliases).
"""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import alias, tool
from jarvis.tools.general.focus_app import focus_app
from jarvis.tools.general.list_windows import list_windows
from jarvis.tools.general.snap_window import snap_window


def show_desktop(on: bool = True) -> str:
    """'go to the home screen' / 'show desktop': every window minimized (wmctrl's show-desktop mode; nothing closes)."""
    from jarvis.tools.general import _sys
    try:
        _sys.run(["wmctrl", "-k", "on" if on else "off"])
    except Exception as e:  # noqa: BLE001 - no wmctrl / no X11
        return f"error: couldn't show the desktop ({e})"
    return "Showing the desktop: every window is minimized (nothing was closed)." if on else "Windows are back."


@tool(group="windows", safety="safe",
      description="Windows: list the open ones, switch to an app's window, snap left/right, maximize, minimize, "
                  "restore, or desktop (go to the home screen: minimize every window; undesktop brings them back).")
def window(action: Literal["list", "focus", "left", "right", "maximize", "minimize", "restore", "desktop",
                           "undesktop"] = "list", name: str = "") -> str:
    """Manage windows.

    Args:
        action: list, focus (switch to `name`), desktop (home screen: minimize all), undesktop, or a position for
            the active window / `name`'s window.
        name: The app or window title (empty = the active window for positions).
    """
    if action in ("desktop", "undesktop"):
        return show_desktop(action == "desktop")
    if action == "focus":
        return focus_app(name) if name else "error: which app should I switch to?"
    if action == "list":
        return list_windows()
    return snap_window(action, name)


alias("list_windows", "window", action="list")
alias("focus_app", "window", action="focus")
alias("snap_window", "window", lambda a: {"action": a.get("position", "maximize"), "name": a.get("window", "")})
