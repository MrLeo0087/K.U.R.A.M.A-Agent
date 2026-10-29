"""memory: what KURAMA keeps for the user: remember / recall / forget facts, past conversations, saved links,
the reading list, the user's own documents, the workspace (safe dispatcher; forget still asks first)."""
from __future__ import annotations

from typing import Literal

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
    "read_later": Act("read_later", lambda a: {"action": "add", "url": a.get("url", "")}),
    "reading_list": Act("read_later", lambda a: {"action": "list"}),
    "ask_docs": Act("ask_knowledge", lambda a: {"question": a.get("text")}),
    "workspace": Act("read_workspace", lambda a: {"item": a.get("text", "")}),
}


@tool(group="core", safety="safe",
      description="Memory: remember a fact, recall what you know about the user, forget, past_chat (what we talked "
                  "about), save_link / get_link, read_later (save this link) / reading_list, ask_docs (the user's own "
                  "notes and code), workspace (read a result).")
def memory(action: Literal["remember", "recall", "forget", "past_chat", "save_link", "get_link", "read_later", "reading_list",
                           "ask_docs", "workspace"], text: str = "", url: str = "") -> str:
    """Memory.

    Args:
        action: What to do.
        text: The fact / the search words / the link name / the question.
        url: A link the user literally gave (never invent one).
    """
    return run(TABLE, {"action": action, "text": text, "url": url})
