"""night_light: GNOME Night Light on/off and colour temperature (1700-4700 K). Safe."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.general import _desk, _sys

T_MIN, T_MAX = 1700, 4700


def _schedule_note() -> str:
    if _desk.gs_get(_desk.COLOR, "night-light-schedule-automatic") == "true":
        return " (GNOME applies it from sunset to sunrise)"
    return ""


@tool(group="desktop", safety="safe", description="Turn Night Light (warm screen) on or off, or set its warmth in kelvin.")
def night_light(action: Literal["on", "off", "toggle", "status"] = "toggle", temperature: int | None = None) -> str:
    """Night Light.

    Args:
        action: on, off, toggle, or status.
        temperature: Optional warmth in kelvin, 1700 (very warm) to 4700 (mild).
    """
    if err := _desk.need_gsettings():
        return err
    now = _desk.gs_get(_desk.COLOR, "night-light-enabled") == "true"
    if action == "status" and temperature is None:
        k = _desk.gs_get(_desk.COLOR, "night-light-temperature") or "?"
        return f"Night Light is {'on' if now else 'off'} ({k} K)."
    try:
        want = True if action == "status" else _desk.target(action, now)
        parts = []
        if temperature is not None:
            k = _sys.clamp(temperature, T_MIN, T_MAX)
            _desk.gs_set(_desk.COLOR, "night-light-temperature", str(k))
            parts.append(f"{k} K")
        _desk.gs_set(_desk.COLOR, "night-light-enabled", "true" if want else "false")
    except (ValueError, _sys.SysError) as e:
        return f"error: {e}"
    if not want:
        return "Night Light is off."
    return f"Night Light is on{' at ' + parts[0] if parts else ''}{_schedule_note()}."
