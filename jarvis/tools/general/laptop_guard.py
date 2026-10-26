"""laptop_guard: arm/disarm the anti-theft guard, see where the laptop is, take a webcam photo now (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import guard
from jarvis.core.registry import tool


@tool(group="power", safety="safe",
      description="Laptop guard (anti-theft): on/off; while on, a webcam photo + location goes to Telegram when "
                  "someone unlocks it, types a wrong password or wakes it. 'where' = where the laptop is now.")
def laptop_guard(action: Literal["status", "on", "off", "where", "photo", "track_off"] = "status") -> str:
    """Laptop guard.

    Args:
        action: on / off / status, where = Wi-Fi + IP + rough location, photo = webcam photo to Telegram now,
            track_off = stop lost mode's location messages (the guard stays as it is).
    """
    if action == "track_off":
        from jarvis.core import locationlog
        return locationlog.set_lost("laptop", False)
    if action == "off":  # "stop tracking my laptop" also means: stop the lost-mode location messages
        from jarvis.core import locationlog
        out = guard.arm(False)
        return out + (" Lost mode is off too: no more location messages." if locationlog.lost_mode("laptop")
                      and not locationlog.set_lost("laptop", False).startswith("Lost mode was") else "")
    if action == "on":
        return guard.arm(True)
    if action == "where":
        return guard.where()
    if action == "photo":
        guard.alert("Photo you asked for")
        return "Sent a webcam photo and the location to your Telegram." if guard.camera() else "No webcam found."
    return guard.status()
