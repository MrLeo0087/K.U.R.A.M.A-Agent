"""internet_doctor: why the internet is slow or down (Wi-Fi, router, provider, DNS, web), speed test, reconnect,
switch DNS, and "tell me when it's back" (safe; changing the network asks first)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import netdoctor as nd
from jarvis.core import safety
from jarvis.core.registry import tool


@tool(group="system", safety="safe",
      description="Internet doctor: find why the internet is slow or not working (Wi-Fi, router, provider, DNS), "
                  "speed test, reconnect Wi-Fi, switch to public DNS, or tell the user when the internet is back.")
def internet_doctor(action: Literal["check", "speed", "reconnect", "fix_dns", "notify_when_back"] = "check") -> str:
    """Internet doctor.

    Args:
        action: check = find the broken link; speed = download speed test (~10 MB); reconnect = restart the Wi-Fi
            connection; fix_dns = use 1.1.1.1 / 8.8.8.8; notify_when_back = message the user when it works again.
    """
    if action == "speed":
        return nd.speed()
    if action == "notify_when_back":
        return nd.wait_for_internet()
    if action in ("reconnect", "fix_dns"):
        what = "Restart the Wi-Fi connection" if action == "reconnect" else "Switch this network to DNS 1.1.1.1 and 8.8.8.8"
        if not safety.ask(f"{what}? The connection drops for a few seconds."):
            return "The user said no, so nothing was changed."
        return nd.reconnect() if action == "reconnect" else nd.fix_dns()
    return nd.text(nd.diagnose())
