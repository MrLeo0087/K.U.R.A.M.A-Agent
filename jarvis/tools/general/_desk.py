"""Shared GNOME helpers for the P9a desktop tools (not a tool): gsettings get/set through _sys.run (so
tests never touch the real settings), Do Not Disturb state and on/off/toggle resolution."""
from __future__ import annotations

from jarvis.tools.general import _sys

NOTIF = "org.gnome.desktop.notifications"
COLOR = "org.gnome.settings-daemon.plugins.color"
BG = "org.gnome.desktop.background"


def gs_get(schema: str, key: str) -> str | None:
    """Value without GVariant quotes/type prefix ('uint32 2700' -> '2700'), None when unreadable."""
    try:
        out = _sys.run(["gsettings", "get", schema, key], timeout=4).strip()
    except _sys.SysError:
        return None
    if out.startswith(("uint32 ", "int32 ", "uint64 ", "int64 ")):
        out = out.split(" ", 1)[1]
    return out.strip("'")


def gs_set(schema: str, key: str, value: str) -> None:
    _sys.run(["gsettings", "set", schema, key, str(value)], timeout=4)


def need_gsettings() -> str | None:
    return None if _sys.which("gsettings") else "error: gsettings not found (GNOME settings tool)"


def target(action: str, current: bool) -> bool:
    """on/off/toggle -> the wanted boolean state."""
    if action == "toggle":
        return not current
    if action in ("on", "off"):
        return action == "on"
    raise ValueError(f"unknown action {action!r}: use on, off, toggle or status")


def dnd_on() -> bool:
    return gs_get(NOTIF, "show-banners") == "false"


def set_dnd(on: bool) -> None:
    gs_set(NOTIF, "show-banners", "false" if on else "true")
