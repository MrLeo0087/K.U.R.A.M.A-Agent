"""install_app: install, remove or update apps (apt/snap/flatpak, auto-picked); Ubuntu asks the password (confirm)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="apps", safety="confirm",
      description="Install or uninstall any app (finds it in apt, snap or flatpak), search for one, or update all "
                  "apps. Ubuntu shows its own password popup on the laptop.")
def install_app(action: Literal["install", "remove", "search", "update"] = "install", name: str = "") -> str:
    """Manage installed apps.

    Args:
        action: install, remove (uninstall), search (show matches), update (everything).
        name: The app, e.g. 'obs', 'postman', 'vs code', 'vlc'.
    """
    from jarvis.core import installer
    if action == "update":
        return installer.update_all()
    if not name.strip():
        return "error: which app?"
    if action == "search":
        return installer.search(name)
    return installer.install(name, remove=action == "remove")
