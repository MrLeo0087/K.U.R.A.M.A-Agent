"""auto_theme: turn automatic dark/light mode (sunset/sunrise or fixed times) on or off. Safe.
The switching itself is done by the auto_theme worker (python -m jarvis.workers).

No longer a tool of its own: the merged tool calls auto_theme() (old name kept as an alias)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from jarvis.core import config
from jarvis.tools.general import _autotheme as at


def _times() -> str:
    sunrise, sunset = at.times_for(datetime.now().date())
    src = "sunrise/sunset" if config.AUTO_THEME_SOURCE == "sun" else "fixed times"
    return f"light at {sunrise:%H:%M}, dark at {sunset:%H:%M} ({src})"


def auto_theme(action: Literal["on", "off", "status"] = "status") -> str:
    """Automatic dark/light mode.

    Args:
        action: on, off, or status.
    """
    if action == "status":
        return f"Auto theme is {'on: ' + _times() if at.enabled() else 'off'}."
    if action == "off":
        at.set_enabled(False)
        return "Auto theme is off; the theme stays as it is."
    at.set_enabled(True)
    out = at.check() or ""
    now = f" {out}" if out and not out.lower().startswith("error") else ""
    return f"Auto theme is on: {_times()}.{now} (needs the workers running: python -m jarvis.workers)"
