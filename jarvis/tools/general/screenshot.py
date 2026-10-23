"""screenshot: capture the full screen, the active window or a selected area to
~/Pictures/Screenshots/jarvis-YYYYmmdd-HHMMSS.png (gnome-screenshot, else scrot). Safe."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from jarvis.core import config
from jarvis.core.registry import tool
from jarvis.tools.general import _sys

FLAGS = {"gnome-screenshot": {"full": [], "window": ["-w"], "area": ["-a"]},
         "scrot": {"full": [], "window": ["-u"], "area": ["-s"]}}


def new_path() -> Path:
    d = Path(config.SCREENSHOT_DIR).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"jarvis-{datetime.now():%Y%m%d-%H%M%S}.png"
    n = 1
    while p.exists():  # two shots in the same second
        p = d / f"jarvis-{datetime.now():%Y%m%d-%H%M%S}-{n}.png"
        n += 1
    return p


@tool(group="screen", safety="safe", description="Take a screenshot (full screen, active window, or a selected area); returns the file path.")
def screenshot(mode: Literal["full", "window", "area"] = "full") -> str:
    """Take a screenshot.

    Args:
        mode: full (whole screen), window (active window) or area (user drags a rectangle).
    """
    if mode not in ("full", "window", "area"):
        return f"error: unknown mode {mode!r}"
    tools = [t for t in config.SCREENSHOT_TOOLS if _sys.which(t)]
    if not tools:
        return "error: no screenshot tool found: sudo apt install gnome-screenshot (or scrot)"
    path = new_path()
    timeout = 60 if mode == "area" else 15  # area waits for the user's selection
    errors = []
    for t in tools:
        argv = [t, "-f", str(path), *FLAGS[t][mode]] if t == "gnome-screenshot" else [t, *FLAGS[t][mode], str(path)]
        try:
            _sys.run(argv, timeout=timeout)
        except _sys.SysError as e:
            errors.append(f"{t}: {e}")
            continue
        if path.exists() and path.stat().st_size > 0:
            return f"saved screenshot to {path}"
        errors.append(f"{t}: no file was written" + (" (selection cancelled?)" if mode == "area" else ""))
    return "error: screenshot failed (" + "; ".join(errors)[:200] + ")"
