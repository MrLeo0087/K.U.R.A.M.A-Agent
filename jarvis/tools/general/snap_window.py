"""snap_window: snap the active or a named window to the left/right half, maximize, minimize or
restore it (wmctrl + xdotool; the work area comes from `wmctrl -d`, else the display size minus the
GNOME top bar). Safe."""
from __future__ import annotations

import os
import re
from typing import Literal

from jarvis.core import config
from jarvis.core.registry import tool
from jarvis.tools.general import _apps, _sys
from jarvis.tools.interactive import _proc

MAX = "maximized_vert,maximized_horz"


def work_area() -> tuple[int, int, int, int]:
    """(x, y, w, h) usable for windows on the current desktop."""
    full_w, full_h = (int(v) for v in _sys.run(["xdotool", "getdisplaygeometry"]).split()[:2])
    m = None
    for line in _sys.run(["wmctrl", "-d"]).splitlines():
        if " * " in f" {line} ":
            m = re.search(r"WA: (-?\d+),(-?\d+) (\d+)x(\d+)", line)
            break
    if m:
        x, y, w, h = (int(v) for v in m.groups())
        if (w, h) != (full_w, full_h) or (x, y) != (0, 0):
            return x, y, w, h
    off = config.SNAP_PANEL_OFFSET if "gnome" in os.getenv("XDG_CURRENT_DESKTOP", "").lower() else 0
    return 0, off, full_w, full_h - off


def _target(window: str) -> tuple[str, str]:
    """(hex window id, label) for a named window or the active one."""
    if window.strip():
        wins, label = _apps.match_windows(window)
        if not wins:
            raise _sys.SysError(f"no open window matches {window!r}")
        return hex(int(wins[0]["id"], 16)), label
    wid = _sys.run(["xdotool", "getactivewindow"]).strip()
    if not wid.isdigit():
        raise _sys.SysError("no active window")
    return hex(int(wid)), "the active window"


@tool(group="windows", safety="safe", description="Snap the active or a named window left/right, maximize, minimize or restore it.")
def snap_window(position: Literal["left", "right", "maximize", "minimize", "restore"], window: str = "") -> str:
    """Arrange a window.

    Args:
        position: left or right half, maximize, minimize, or restore (un-maximize / un-minimize).
        window: App name or window title (e.g. "firefox", "vs code"); empty = the active window.
    """
    try:
        wid, label = _target(window)
        if position in ("left", "right"):
            x, y, w, h = work_area()
            half = w // 2
            left = x if position == "left" else x + half
            _sys.run(["wmctrl", "-i", "-r", wid, "-b", f"remove,{MAX}"])
            _sys.run(["wmctrl", "-i", "-r", wid, "-e", f"0,{left},{y},{half},{h}"])
            _sys.run(["wmctrl", "-i", "-r", wid, "-b", "add,maximized_vert"])
            return f"snapped {label} to the {position} half"
        if position == "maximize":
            _sys.run(["wmctrl", "-i", "-r", wid, "-b", f"add,{MAX}"])
            return f"maximized {label}"
        if position == "minimize":
            _sys.run(["xdotool", "windowminimize", str(int(wid, 16))])
            return f"minimized {label}"
        if position == "restore":
            _sys.run(["wmctrl", "-i", "-r", wid, "-b", f"remove,{MAX}"])
            _sys.run(["wmctrl", "-i", "-a", wid])  # also un-minimizes and focuses it
            return f"restored {label}"
        return f"error: unknown position {position!r}"
    except (_sys.SysError, _proc.ProcError, ValueError) as e:
        return f"error: {e}"
