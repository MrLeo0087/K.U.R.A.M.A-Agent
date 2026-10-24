"""find_my_phone: open Google Find My Device (or Find My iPhone) in the browser to locate/ring/lock the phone (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.general.open_url import _open

# Free, nothing to install: the phone reports its own location to the user's Google/Apple account.
PROVIDERS = {
    "android": ("https://www.google.com/android/find", "Google Find My Device"),
    "google": ("https://www.google.com/android/find", "Google Find My Device"),
    "iphone": ("https://www.icloud.com/find", "Find My iPhone"),
    "ios": ("https://www.icloud.com/find", "Find My iPhone"),
    "apple": ("https://www.icloud.com/find", "Find My iPhone"),
}


@tool(group="system", safety="safe",
      description="Find my phone: open Google Find My Device (Android) or Find My iPhone in the browser, to see the "
                  "phone's location on a map and ring, lock or erase it. Free, no app needed (sign in with the "
                  "phone's own account).")
def find_my_phone(phone: Literal["android", "iphone"] = "android") -> str:
    """Open the right find-my-phone page in the browser.

    Args:
        phone: android (Google Find My Device) or iphone (Find My iPhone).
    """
    url, name = PROVIDERS.get(phone.lower().strip(), PROVIDERS["android"])
    _open(url)
    return (f"Opened {name}. Sign in with the account on the phone to see it on the map, ring it, lock it or "
            f"erase it.")
