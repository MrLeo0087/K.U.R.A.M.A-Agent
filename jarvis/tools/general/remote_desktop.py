"""remote_desktop: start RustDesk remote control of the laptop and point to Telegram for the password, or stop it (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="system", safety="safe",
      description="Remote desktop (RustDesk): the password is only given on Telegram after the PIN (this says how). "
                  "stop=true turns it off (the password stops working at once).")
def remote_desktop(stop: bool = False) -> str:
    """Start RustDesk and give the connection details, or stop it."""
    from jarvis.core import remotedesk
    if stop:
        return remotedesk.stop()
    return remotedesk.TELEGRAM_ONLY  # the password is only handed out by the Telegram bot, after the PIN
