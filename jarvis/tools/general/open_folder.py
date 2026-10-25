"""open_folder: open a folder in the file manager by name (fuzzy), e.g. "open project1", "open my college project". Safe."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="apps", safety="safe",
      description="Open a folder in the file manager by name (fuzzy match anywhere on the laptop): "
                  "'open project1 in files', 'open my college project folder'.")
def open_folder(name: str) -> str:
    """Open a folder in the file manager.

    Args:
        name: The folder's name or part of it ("project1", "college project", "Tara/TARA"). Loose names work.
    """
    from jarvis.tools.general.open_url import _open
    from jarvis.tools.interactive.list_folder import _targets

    dirs, notes = _targets((name or "").strip())
    if not dirs:
        return notes[0] if notes else f"error: no folder like {name!r} found on your laptop"
    d = dirs[0]
    _open(str(d))  # xdg-open on a directory opens the default file manager there
    note = next((n for n in notes if not n.startswith("error")), "")
    return f"Opened “{d.name}” in your file manager ({d})." + (f" {note}" if note else "")
