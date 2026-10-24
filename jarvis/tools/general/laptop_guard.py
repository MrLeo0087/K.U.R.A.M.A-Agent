"""laptop_guard: arm/disarm the anti-theft guard, see where the laptop is, take a webcam photo now (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import guard
from jarvis.core.registry import tool


@tool(group="power", safety="safe",
      description="Laptop guard (anti-theft): on/off; while on, a webcam photo + location goes to Telegram when "
                  "someone unlocks it, types a wrong password or wakes it. 'where' = where the laptop is now.")
def laptop_guard(action: Literal["status", "on", "off", "where", "photo"] = "status") -> str:
    """Laptop guard.

    Args:
        action: on / off / status, where = Wi-Fi + IP + rough location, photo = webcam photo to Telegram now.
    """
    if action in ("on", "off"):
        return guard.arm(action == "on")
    if action == "where":
        return guard.where()
    if action == "photo":
        guard.alert("Photo you asked for")
        return "Sent a webcam photo and the location to your Telegram." if guard.camera() else "No webcam found."
    return guard.status()
