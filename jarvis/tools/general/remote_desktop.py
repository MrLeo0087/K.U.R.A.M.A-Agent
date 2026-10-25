"""remote_desktop: start RustDesk remote control of the laptop and return the ID + a short-lived password, or stop it (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="system", safety="safe",
      description="Start remote desktop (RustDesk): turn on full remote control of the laptop and return the "
                  "connection ID and a short-lived password, so the user can see and control the whole screen from their "
                  "phone. stop=true turns it off (the password stops working at once).")
def remote_desktop(stop: bool = False) -> str:
    """Start RustDesk and give the connection details, or stop it."""
    from jarvis.core import remotedesk
    if stop:
        return remotedesk.stop()
    return remotedesk.status_text(remotedesk.start())
