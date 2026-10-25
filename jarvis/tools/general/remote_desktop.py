"""remote_desktop: start RustDesk remote control of the laptop and return the ID + password (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="system", safety="safe",
      description="Start remote desktop (RustDesk): turn on full remote control of the laptop and return the "
                  "connection ID and password, so the user can see and control the whole screen from their phone.")
def remote_desktop() -> str:
    """Start RustDesk and give the connection details."""
    from jarvis.core import remotedesk
    return remotedesk.status_text(remotedesk.start())
