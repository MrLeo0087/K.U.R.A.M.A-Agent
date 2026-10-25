"""web_search: top web results (title, URL, one-line snippet). SearXNG first when config.SEARXNG_URL is
set and reachable, else DuckDuckGo via `ddgs` (lazy import). <= 800 chars, 10-min cache (safe)."""
from __future__ import annotations

import logging
import time

from jarvis.core import config
from jarvis.core.registry import tool
from jarvis.tools.general import _web

log = logging.getLogger("jarvis.tools.web_search")
SEARX_RETRY_S = 300  # after a SearXNG failure, use DuckDuckGo for this long
_searx_down_until = 0.0


def _searx(query: str, k: int) -> list[dict]:
    status, data = _web.get_json(f"{config.SEARXNG_URL}/search",
                                 params={"q": query, "format": "json", "safesearch": 1})
    if status != 200 or not isinstance(data, dict):
        raise RuntimeError(f"SearXNG HTTP {status}")
    return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
            for r in (data.get("results") or [])[:k]]


def _ddg(query: str, k: int) -> list[dict]:
    from ddgs import DDGS  # lazy: lxml + primp load only when searching

    rows = DDGS(timeout=int(config.WEB_TIMEOUT_S)).text(query, max_results=k) or []
    return [{"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in rows[:k]]


def search(query: str, k: int) -> tuple[str, list[dict]]:
    """(backend name, results). SearXNG when configured and up, DuckDuckGo otherwise."""
    global _searx_down_until
    if config.SEARXNG_URL and time.monotonic() >= _searx_down_until:
        try:
            rows = _searx(query, k)
            if rows:
                return "searxng", rows
        except Exception as e:
            log.warning("SearXNG unavailable, using DuckDuckGo: %s", e)
            _searx_down_until = time.monotonic() + SEARX_RETRY_S
    return "ddg", _ddg(query, k)


def format_results(rows: list[dict], limit: int | None = None) -> str:
    limit = limit or config.WEB_SEARCH_MAX_CHARS
    out: list[str] = []
    used = 0
    for i, r in enumerate(rows, 1):
        line = f"{i}. {_web.one_line(r['title'], 80)} - {r['url']}"
        if r.get("snippet"):
            line += "\n   " + _web.one_line(r["snippet"], 140)
        if used + len(line) + 1 > limit:
            if not out:
                out.append(line[:limit])
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)


@tool(group="web", safety="safe",
      description="Search the web for general info, people or facts: top results with title, URL and snippet. "
                  "NOT for scores, prices, rates or today's news (use live_search).")
def web_search(query: str, k: int = 5) -> str:
    """Search the web.

    Args:
        query: What to search for, e.g. "CarryMinati latest video".
        k: Number of results (1-8).
    """
    query = " ".join((query or "").split())
    if not query:
        return "error: say what to search for"
    k = max(1, min(int(k or 5), 8))
    key = (query.lower(), k)
    if (hit := _web.cache.get(("search", key))) is not None:
        return hit
    try:
        _backend, rows = search(query, k)
    except Exception as e:
        log.warning("web search failed: %s", e)
        return f"error: web search failed ({type(e).__name__}); try again in a moment"
    if not rows:
        return f"No web results for {query!r}."
    text = format_results(rows)
    _web.cache.set(("search", key), text)
    return text
