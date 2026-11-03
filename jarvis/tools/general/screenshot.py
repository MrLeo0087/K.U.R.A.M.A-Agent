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


def new_path(folder: str = "") -> Path:
    d = Path(folder or config.SCREENSHOT_DIR).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"jarvis-{datetime.now():%Y%m%d-%H%M%S}.png"
    n = 1
    while p.exists():  # two shots in the same second
        p = d / f"jarvis-{datetime.now():%Y%m%d-%H%M%S}-{n}.png"
        n += 1
    return p


@tool(group="screen", safety="safe", description="Take a screenshot (full screen, active window, or a selected area), "
      "optionally saved into a given folder; returns the file path.")
def screenshot(mode: Literal["full", "window", "area"] = "full", folder: str = "") -> str:
    """Take a screenshot.

    Args:
        mode: full (whole screen), window (active window) or area (user drags a rectangle).
        folder: Where to save it when the user says so ('save it in the trip folder'); empty = ~/Pictures/Screenshots.
    """
    if mode not in ("full", "window", "area"):
        return f"error: unknown mode {mode!r}"
    if folder:  # 'take a screenshot and save it in that folder' had no way to say where (11-03): it claimed it did
        from jarvis.core.paths import smart_path
        found = smart_path(folder, want="dir")
        if found is None:
            return f"error: I couldn't find the folder {folder!r}"
        folder = str(found)
    tools = [t for t in config.SCREENSHOT_TOOLS if _sys.which(t)]
    if not tools:
        return "error: no screenshot tool found: sudo apt install gnome-screenshot (or scrot)"
    path = new_path(folder)
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
