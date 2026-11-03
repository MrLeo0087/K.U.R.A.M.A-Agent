"""app_name: teach KURAMA a name for an app ("when I say browser, open Brave"); every open / close / focus uses it (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool
from jarvis.tools.general import _apps


@tool(group="apps", safety="safe", description="Remember a name for an app: when the user says NAME, open APP (e.g. browser = Brave).")
def app_name(name: str, app: str = "") -> str:
    """Name an app.

    Args:
        name: What the user will say, e.g. "browser", "my editor", "music app".
        app: The installed app it means, e.g. "brave". Empty = forget that name.
    """
    return _apps.teach(name, app)
