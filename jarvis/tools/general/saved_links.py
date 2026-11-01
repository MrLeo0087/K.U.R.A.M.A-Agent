"""saved_links: named links the user keeps and asks for later ('give me my Facebook link') (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="links", safety="safe", description="Saved links by name (Excel): save the highlighted link / open page "
      "under a name, give or open a saved link by name, list, rename, delete.")
def saved_links(action: Literal["save", "name", "cancel", "get", "open", "list", "rename", "delete"] = "get",
                name: str = "", url: str = "", new_name: str = "") -> str:
    """Saved links.

    Args:
        action: save (the highlighted link or the page open in the browser), name (the name for the link just found),
            cancel, get (the link, copied), open, list, rename, delete.
        name: the link's name, e.g. 'Facebook', 'Claude Code'.
        url: ONLY a link the user literally gave; never invent one (empty = highlighted link / open page).
        new_name: rename only.
    """
    from jarvis.core import links

    return links.run(action, name, url, new_name)
