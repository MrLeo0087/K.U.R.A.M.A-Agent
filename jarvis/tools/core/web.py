"""web: answers from the internet: live results (sports, news, prices, today's facts), search, read a web page or
the page open in the browser, Wikipedia, watch a page for a word (safe dispatcher)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.core._hub import Act, run

TABLE = {
    "live": Act("live_search", lambda a: {"query": a.get("query"), "kind": a.get("kind", "auto")}),
    "search": Act("web_search", lambda a: {"query": a.get("query")}),
    "read": Act("read_webpage", lambda a: {"url": a.get("url") or a.get("query")}),
    "this_page": Act("page_summary", lambda a: {"action": "summary"}),
    "wiki": Act("wikipedia", lambda a: {"topic": a.get("query")}),
    "watch": Act("web_watch", lambda a: {"action": "add", "url": a.get("url"), "word": a.get("query", "")}),
}


@tool(group="core", safety="safe",
      description="Internet answers: live (match results, news, scores, prices, anything recent), search, read a web "
                  "page, this_page (summarize what the open browser page says; saving its link is memory save_link), wiki, "
                  "watch a page for a word.")
def web(action: Literal["live", "search", "read", "this_page", "wiki", "watch"], query: str = "", url: str = "",
        kind: Literal["auto", "sports", "news", "answer"] = "auto") -> str:
    """Web.

    Args:
        action: live, search, read, this_page (a summary of the open page, never to save it), wiki, watch.
        query: What to look up (or the word to watch for).
        url: The page to read or watch.
        kind: live: sports, news, answer or auto.
    """
    return run(TABLE, {"action": action, "query": query, "url": url, "kind": kind})
