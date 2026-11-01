"""memory: what KURAMA keeps for the user: remember / recall / forget facts, past conversations, saved links,
the reading list, the user's own documents, the workspace (safe dispatcher; forget still asks first)."""
from __future__ import annotations

import re
from typing import Literal

from jarvis.core import links
from jarvis.core.registry import tool
from jarvis.tools.core._hub import Act, run

TABLE = {
    "remember": Act("remember", lambda a: {"text": a.get("text")}),
    "recall": Act("recall", lambda a: {"which": "search" if a.get("text") else "all", "query": a.get("text", "")}),
    "forget": Act("forget", lambda a: {"which": "all" if (a.get("text") or "").lower() in ("all", "everything") else "fact",
                                       "fact": a.get("text", "")}),
    "past_chat": Act("recall_session", lambda a: {"query": a.get("text", "")}),
    "save_link": Act("saved_links", lambda a: {"action": "save", "name": a.get("text", ""), "url": a.get("url", "")}),
    "get_link": Act("saved_links", lambda a: {"action": "get", "name": a.get("text", "")}),
    "open_link": Act("saved_links", lambda a: {"action": "open", "name": a.get("text", "")}),
    "list_links": Act("saved_links", lambda a: {"action": "list"}),
    "delete_link": Act("saved_links", lambda a: {"action": "delete", "name": a.get("text", "")}),
    "rename_link": Act("saved_links", lambda a: {"action": "rename", **_old_new(a.get("text", ""))}),
    "read_later": Act("read_later", lambda a: {"action": "add", "url": a.get("url", "")}),
    "reading_list": Act("read_later", lambda a: {"action": "list", "text": "read"}),
    "remove_read_later": lambda a: _rl_remove(a.get("text", "")),
    "ask_docs": Act("ask_knowledge", lambda a: {"question": a.get("text")}),
    "workspace": Act("read_workspace", lambda a: {"item": a.get("text", "")}),
}


def _old_new(text: str) -> dict:
    """'old » new' / 'old -> new' / 'old to new' -> saved_links rename args."""
    parts = re.split(r"\s*(?:»|->|=>|>)\s*|\s+to\s+", text.strip(), maxsplit=1)
    return {"name": parts[0], "new_name": parts[1] if len(parts) > 1 else ""}


def _rl_remove(text: str) -> tuple[str, dict]:
    """Reading list: an item number, 'all' (empty the reading list) or the item's words."""
    t = text.strip().lower()
    if t in ("all", "everything", "whole list", "the whole list"):
        return "read_later", {"action": "clear", "text": "read"}
    if (n := links.position(t)) is not None:
        return "read_later", {"action": "remove", "n": n}
    return "read_later", {"action": "remove", "text": text}


@tool(group="core", safety="safe",
      description="Memory: remember a fact, recall what you know about the user, forget a fact, past_chat (what we "
                  "talked about); the link store: save_link (save the open page's / highlighted link under a name: "
                  "url empty, KURAMA reads it), get_link, "
                  "open_link, list_links, delete_link, rename_link; read_later (save this page) / reading_list / "
                  "remove_read_later; ask_docs (the user's own notes and code), workspace (read a result).")
def memory(action: Literal["remember", "recall", "forget", "past_chat", "save_link", "get_link", "open_link", "list_links",
                           "delete_link", "rename_link", "read_later", "reading_list", "remove_read_later",
                           "ask_docs", "workspace"], text: str = "", url: str = "") -> str:
    """Memory.

    Args:
        action: What to do. Saved links are NOT facts: removing a link is delete_link, never forget.
        text: The fact / the search words / the question; for links the link name as the user said it
            (delete_link / remove_read_later: also a number like 2, or 'all'; rename_link: 'old » new').
        url: Only a link typed in the user's CURRENT message; otherwise empty (the page open in the browser is used).
    """
    return run(TABLE, {"action": action, "text": text, "url": url})
