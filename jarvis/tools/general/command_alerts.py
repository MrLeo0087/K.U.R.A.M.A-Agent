"""command_alerts: tell me when long terminal commands finish (pip install, builds, scripts) (safe; turning it on
or off asks first because it edits ~/.bashrc)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import cmdalerts, safety
from jarvis.core.registry import tool


@tool(group="watch", safety="safe",
      description="Long-command alerts: when a terminal command runs longer than N minutes, say when it finishes "
                  "(done/failed, time taken; on the phone when the screen is locked). on, off or status.")
def command_alerts(action: Literal["status", "on", "off"] = "status", minutes: float = 0) -> str:
    """Long terminal command alerts.

    Args:
        action: on = install the small bash hook, off = remove it, status = is it on + the last commands.
        minutes: Only commands longer than this (default 2).
    """
    if action == "status":
        return cmdalerts.status()
    if action == "on":
        if not safety.ask("Add a small line to your ~/.bashrc so long terminal commands tell me when they finish?"):
            return "The user said no, so nothing was changed."
        return cmdalerts.install(minutes or None)
    if not cmdalerts.installed():
        return "Command alerts are already off."
    if not safety.ask("Remove KURAMA's command-alert line from your ~/.bashrc?"):
        return "The user said no, so they stay on."
    return cmdalerts.uninstall()
