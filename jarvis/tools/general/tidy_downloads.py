"""tidy_downloads: sort ~/Downloads into Documents/Images/Videos/... folders, duplicates to the Trash (safe; moving
asks first; preview never changes anything)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import automation, safety, store
from jarvis.core.registry import tool


@tool(group="automation", safety="safe",
      description="Tidy the Downloads folder: preview or sort files into Documents/Images/Videos/Audio/Archives/Code/"
                  "Data/Installers (screenshots apart, exact duplicates to Trash); auto_on sorts daily.")
def tidy_downloads(action: Literal["preview", "run", "auto_on", "auto_off", "installers"] = "preview") -> str:
    """Downloads sorter.

    Args:
        action: preview = what would move; run = do it (asks); auto_on / auto_off = sort by itself once a day;
            installers = move installers not used for a month to the Trash (asks).
    """
    if action == "installers":
        olds = automation.old_installers()
        if not olds:
            return "No old installers in Downloads."
        if not safety.ask(f"Move {len(olds)} old installer(s) to the Trash? " + ", ".join(f.name for f in olds[:8])):
            return "The user said no, so nothing was moved."
        return automation.trash_old_installers()
    if action == "preview":
        return automation.sort_preview()
    if action == "auto_off":
        store.kv_set("sort_auto", "0")
        return "Daily Downloads sorting is off."
    if not safety.ask(automation.sort_preview().replace("Say 'sort my downloads' to do it.", "Go ahead?")
                      + (" (and every day from now on)" if action == "auto_on" else "")):
        return "The user said no, so nothing was moved."
    if action == "auto_on":
        store.kv_set("sort_auto", "1")
    return automation.sort_run()
