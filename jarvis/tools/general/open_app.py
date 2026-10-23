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
    _apps.launch(entry)
    return f"opened {entry['name']}"
