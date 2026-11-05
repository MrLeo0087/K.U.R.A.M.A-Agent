"""internet_doctor: why the internet is slow or down (Wi-Fi, router, provider, DNS, web), speed test, reconnect,
switch DNS, and "tell me when it's back" (safe; changing the network asks first)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import netdoctor as nd
from jarvis.core import safety
from jarvis.core.registry import tool


@tool(group="system", safety="safe",
      description="Internet doctor: find why the internet is slow or not working (Wi-Fi, router, provider, DNS), "
                  "speed test, or tell the user when it is back. Use reconnect / fix_dns ONLY when the check found "
                  "that problem or the user asks for it.")
def internet_doctor(action: Literal["check", "speed", "reconnect", "fix_dns", "notify_when_back"] = "check",
                    seconds: int = 0) -> str:
    """Internet doctor.

    Args:
        action: check = find the broken link; speed = speed test (download + upload); reconnect = restart the Wi-Fi
            connection; fix_dns = use 1.1.1.1 / 8.8.8.8; notify_when_back = message the user when it works again.
        seconds: For speed: the test length for THIS test only (0 = the saved setting).
    """
    if action == "speed":
        if seconds:
            from jarvis.core import usersettings
            n = max(5, min(int(seconds), 60))
            usersettings.note_once("speed test seconds", f"{n} seconds")  # "make it permanent" keeps it
            return nd.speed(n) + f" ({n} s test, this time only: say 'make it permanent' to keep {n} s.)"
        return nd.speed()
    if action == "notify_when_back":
        return nd.wait_for_internet()
    if action in ("reconnect", "fix_dns"):
        what = "Restart the Wi-Fi connection" if action == "reconnect" else "Switch this network to DNS 1.1.1.1 and 8.8.8.8"
        if not safety.ask(f"{what}? The connection drops for a few seconds."):
            return "The user said no, so nothing was changed."
        return nd.reconnect() if action == "reconnect" else nd.fix_dns()
    return nd.text(nd.diagnose())
