"""volume: get, set (0-100) or step the speaker volume via pactl on @DEFAULT_SINK@ (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import config
from jarvis.core.registry import tool
from jarvis.tools.general import _sys

SINK = "@DEFAULT_SINK@"


def get_level() -> int:
    n = _sys.pct(_sys.run(["pactl", "get-sink-volume", SINK]))
    if n is None:
        raise _sys.SysError("could not read the volume from pactl")
    return n


@tool(group="audio", safety="safe", description="Get, set (0-100) or step the speaker volume up/down.")
def volume(action: Literal["get", "set", "up", "down"] = "get", level: int | None = None, step: int = 0) -> str:
    """Speaker volume.

    Args:
        action: get, set (needs level), up or down (by step).
        level: Target volume 0-100 for action=set.
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
            new = _sys.clamp(level, 0, config.VOLUME_MAX)
        elif action in ("up", "down"):
            delta = abs(int(step or config.VOLUME_STEP))
            new = _sys.clamp(get_level() + (delta if action == "up" else -delta), 0, config.VOLUME_MAX)
        else:
            return f"error: unknown action {action!r}"
        _sys.run(["pactl", "set-sink-volume", SINK, f"{new}%"])
        if new > 0 and action != "down" and _sys.pactl_muted("sink"):
            _sys.pactl_mute("sink", "unmute")  # "volume up" while muted should be audible
        return f"volume {new}%"
    except _sys.SysError as e:
        return f"error: {e}"
