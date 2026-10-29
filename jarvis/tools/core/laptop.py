"""laptop: every switch and setting of the laptop in one tool (sound, screen, radios, power, health). Shutdown,
restart, sleep and log out still ask yes/no first (the specialised tools are 'confirm')."""
from __future__ import annotations

import re
from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.core._hub import Act, onoff, run


def _level(tool_name: str):
    """'up' / 'down' / 'mute' / '40' / '+10' / 'get' -> audio or brightness arguments."""
    def f(a: dict) -> tuple[str, dict]:
        v = str(a.get("value") or "get").lower().strip()
        n = re.search(r"\d+", v)
        if v in ("mute", "unmute", "toggle") and tool_name == "audio":
            return tool_name, {"action": v}
        if re.match(r"^(?:\+|up|increase|raise|more|louder|brighter)", v):
            return tool_name, {"action": "up", **({"step": int(n.group(0))} if n else {})}
        if re.match(r"^(?:-|down|decrease|lower|less|quieter|dimmer)", v):
            return tool_name, {"action": "down", **({"step": int(n.group(0))} if n else {})}
        if n:
            return tool_name, {"action": "set", "level": int(n.group(0))}
        return tool_name, {"action": "get"}
    return f


def _toggle(setting: str):
    return Act("laptop_toggle", lambda a: {"setting": setting, "state": onoff(a.get("value"), "status")})


TABLE = {
    "volume": _level("audio"), "brightness": _level("brightness"),
    "wifi": _toggle("wifi"), "bluetooth": _toggle("bluetooth"), "airplane": _toggle("airplane"),
    "power_mode": Act("laptop_toggle", lambda a: {"setting": "power_mode", "state": a.get("value", "status")}),
    "night_light": Act("night_light", lambda a: {"action": onoff(a.get("value"))}),
    "theme": Act("set_theme", lambda a: {"mode": a.get("value", "toggle")}),
    "dnd": Act("do_not_disturb", lambda a: {"action": onoff(a.get("value"))}),
    "wallpaper": Act("set_wallpaper", lambda a: {"mode": "set", "image": a["value"]} if a.get("value") not in (None, "next", "random", "current")
                     else {"mode": a.get("value", "next")}),
    "screenshot": Act("screenshot", lambda a: {"mode": a.get("value", "full")}),
    "screen_off": Act("laptop_toggle", lambda a: {"setting": "screen", "state": "off"}),
    "battery": Act("battery_status"),
    "health": Act("laptop_doctor", lambda a: {"action": "check"}),
    "free_ram": Act("laptop_doctor", lambda a: {"action": "free_ram"}),
    "internet": Act("internet_doctor", lambda a: {"action": a.get("value", "check")}),
    "clean_disk": Act("disk_cleaner", lambda a: {"action": a.get("value", "scan")}),
    "focus": Act("focus_mode", lambda a: {"minutes": int(re.search(r"\d+", a.get("value", "25")).group(0)) if re.search(r"\d+", a.get("value", "25")) else 25}),
    "lock": Act("lock_screen"),
    "sleep": Act("suspend_computer"),
    "shutdown": Act("power_off", lambda a: {"action": "shutdown"}),
    "restart": Act("power_off", lambda a: {"action": "restart"}),
    "logout": Act("power_off", lambda a: {"action": "logout"}),
}


@tool(group="core", safety="safe",
      description="Laptop settings and health: volume, brightness, wifi, bluetooth, airplane, power mode, night light, "
                  "theme, do-not-disturb, wallpaper, screenshot, screen off, battery, health (RAM/CPU/top apps), free RAM, "
                  "internet check, clean disk, focus session, lock, sleep, shutdown, restart, log out.")
def laptop(action: Literal["volume", "brightness", "wifi", "bluetooth", "airplane", "power_mode", "night_light", "theme",
                           "dnd", "wallpaper", "screenshot", "screen_off", "battery", "health", "free_ram", "internet",
                           "clean_disk", "focus", "lock", "sleep", "shutdown", "restart", "logout"],
           value: str = "") -> str:
    """Laptop control.

    Args:
        action: What to change or check.
        value: volume/brightness: up, down, +10, 40, mute, get; wifi/bluetooth/airplane/night_light/dnd: on, off,
            status; power_mode: saver, balanced, performance; theme: light, dark; wallpaper: next, random or an image
            path; screenshot: full, window, area; internet: check, speed, fix_dns; clean_disk: scan, clean; focus: minutes.
    """
    return run(TABLE, {"action": action, "value": value})
