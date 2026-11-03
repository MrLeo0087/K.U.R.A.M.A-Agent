"""open_app: launch an installed Ubuntu app by its spoken name (fuzzy .desktop match; safe)."""
from __future__ import annotations

from jarvis.core.registry import tool
from jarvis.tools.general import _apps, open_url


@tool(group="apps", safety="safe", description="Open/launch an installed desktop app by name (vs code, files, terminal, settings, firefox).")
def open_app(name: str) -> str:
    """Launch an app.

    Args:
        name: The app's name as spoken, e.g. "vs code", "files", "terminal", "calculator".
    """
    entry, score = _apps.find_app(name)
    url = open_url.resolve(name)
    if url and (entry is None or score < 100):  # "open youtube" reached the app tool: open the site
        open_url._open(url)
        return f"opened {url}"
    if entry is None or score < _apps.TOOL_MIN_SCORE:
        return f"error: no installed app matches {name!r}"
    ok, how = _apps.open_verified(entry)
    if not ok:
        return (f"error: {entry['name']} didn't open: no window appeared (tried {how}). It may still be starting, or "
                f"be broken: try it from the app menu")
    if how == "front":
        return f"{entry['name']} was already open: brought it to the front"
    return f"opened {entry['name']}"
