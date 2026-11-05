"""snap_window: snap the active or a named window to the left/right half, maximize, minimize or
restore it (wmctrl + xdotool; the work area comes from `wmctrl -d`, else the display size minus the
GNOME top bar). Safe.

No longer a tool of its own: the merged tool calls snap_window() (old name kept as an alias)."""
from __future__ import annotations

import os
import re
from typing import Literal

from jarvis.core import config
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
        title, q = str(wins[0].get("title") or ""), window.strip()
        if q and (i := title.lower().find(q.lower())) >= 0 and q.lower() not in label.lower():
            label = title[i:i + len(q)]  # 'minimize youtube' = the YouTube tab's window, not "Video Downloader"
        return hex(int(wins[0]["id"], 16)), label
    wid = _sys.run(["xdotool", "getactivewindow"]).strip()
    if not wid.isdigit():
        raise _sys.SysError("no active window")
    try:  # typed or said in KURAMA's own chat: KURAMA is the active window, but "the window" is the one you were in
        name = _sys.run(["xdotool", "getwindowname", wid]).strip()
    except (_sys.SysError, _proc.ProcError):
        name = ""
    if name.lower().startswith("kurama") or "127.0.0.1:8000" in name or "localhost:8000" in name:
        from jarvis.core import rewrite
        below, _ = rewrite.target_window(skip_hidden=True)
        if below:
            title = rewrite._window_name(below, 40) or "the window"
            return hex(below), title
    return hex(int(wid)), "the active window"


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
