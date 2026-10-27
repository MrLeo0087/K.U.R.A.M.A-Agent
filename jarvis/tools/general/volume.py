"""volume: get, set (0-100) or step the speaker volume via pactl on @DEFAULT_SINK@ (safe).

No longer a tool of its own: the merged tool calls volume() (old name kept as an alias)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import config
from jarvis.tools.general import _sys

SINK = "@DEFAULT_SINK@"


def max_level() -> int:
    """150 when Ubuntu's Sound > Over-Amplification is on (the laptop can go past 100%), else config.VOLUME_MAX."""
    try:
        import subprocess
        out = subprocess.run(["gsettings", "get", "org.gnome.desktop.sound", "allow-volume-above-100-percent"],
                             capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, Exception):  # noqa: BLE001
        out = ""
    return max(config.VOLUME_MAX, 150) if out == "true" else config.VOLUME_MAX


def get_level() -> int:
    n = _sys.pct(_sys.run(["pactl", "get-sink-volume", SINK]))
    if n is None:
        raise _sys.SysError("could not read the volume from pactl")
    return n


def volume(action: Literal["get", "set", "up", "down"] = "get", level: int | None = None, step: int = 0) -> str:
    """Speaker volume.

    Args:
        action: get, set (needs level), up or down (by step).
        level: Target volume for action=set: 0-100, or up to 150 when Over-Amplification is on.
        step: Percent to change for up/down (default 10).
    """
    try:
        if action == "get" and level is not None:
            action = "set"
        if action == "get":
            muted = _sys.pactl_muted("sink")
            return f"volume {get_level()}%" + (" (muted)" if muted else "")
        if action == "set":
            if level is None:
                return "error: say which level (0-100)"
            top = max_level()
            if level > top:
                return (f"The most this laptop allows is {top}%. Turn on Settings > Sound > Over-Amplification to go up to "
                        f"150%." if top <= 100 else f"The most is {top}%.")
            new = _sys.clamp(level, 0, top)
        elif action in ("up", "down"):
            delta = abs(int(step or config.VOLUME_STEP))
            new = _sys.clamp(get_level() + (delta if action == "up" else -delta), 0, max_level())
        else:
            return f"error: unknown action {action!r}"
        _sys.run(["pactl", "set-sink-volume", SINK, f"{new}%"])
        if new > 0 and action != "down" and _sys.pactl_muted("sink"):
            _sys.pactl_mute("sink", "unmute")  # "volume up" while muted should be audible
        return f"volume {new}%"
    except _sys.SysError as e:
        return f"error: {e}"
