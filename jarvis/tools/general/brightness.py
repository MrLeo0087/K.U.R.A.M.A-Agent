"""brightness: get, set or step the screen backlight via brightnessctl (safe, no sudo)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import config
from jarvis.core.registry import tool
from jarvis.tools.general import _sys

PERMISSION_FIX = ("no permission to change brightness. Fix: run `sudo usermod -aG video $USER`, "
                  "then log out and back in (brightnessctl needs the video group)")


def get_level() -> int:
    out = _sys.run(["brightnessctl", "-c", "backlight", "-m"])  # intel_backlight,backlight,48000,50%,96000
    n = _sys.pct(out)
    if n is None:
        raise _sys.SysError("could not read the brightness from brightnessctl")
    return n


def _explain(e: Exception) -> str:
    msg = str(e)
    low = msg.lower()
    if "permission" in low or "denied" in low or "not permitted" in low:
        return PERMISSION_FIX
    if "no devices" in low or "device" in low and "not found" in low:
        return "no backlight device found (an external monitor is not controlled by brightnessctl)"
    return msg


@tool(group="display", safety="safe", description="Get, set (percent) or step the screen brightness up/down.")
def brightness(action: Literal["get", "set", "up", "down"] = "get", level: int | None = None, step: int = 0) -> str:
    """Screen brightness.

    Args:
        action: get, set (needs level), up or down (by step).
        level: Target brightness percent for action=set.
        step: Percent to change for up/down (default 10).
    """
    try:
        if action == "get" and level is not None:
            action = "set"
        if action == "get":
            return f"brightness {get_level()}%"
        if action == "set":
            if level is None:
                return "error: say which level (percent)"
            new = _sys.clamp(level, 1, 100)  # an explicit level is obeyed (never 0 = black)
        elif action in ("up", "down"):
            delta, cur = abs(int(step or config.BRIGHTNESS_STEP)), get_level()
            floor = min(config.BRIGHTNESS_MIN, cur)  # steps stop at the floor but never raise on "down"
            new = _sys.clamp(cur + (delta if action == "up" else -delta), max(floor, 1), 100)
        else:
            return f"error: unknown action {action!r}"
        _sys.run(["brightnessctl", "-c", "backlight", "-q", "set", f"{new}%"])
        return f"brightness {new}%"
    except _sys.SysError as e:
        return f"error: {_explain(e)}"
