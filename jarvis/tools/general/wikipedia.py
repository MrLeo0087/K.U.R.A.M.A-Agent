"""wikipedia: short summary of a person/topic from the free Wikipedia REST API, with MediaWiki
opensearch + full-text search fallbacks for fuzzy names ("Cariminati" -> CarryMinati). en/ne/hi (safe)."""
from __future__ import annotations

import logging
import re
from urllib.parse import quote

from jarvis.core.registry import tool
from jarvis.tools.general import _web

log = logging.getLogger("jarvis.tools.wikipedia")
MAX_CHARS = 700
_LANG = re.compile(r"^[a-z]{2,3}$")


def _hdr() -> dict:
    return {"User-Agent": _web.WIKI_AGENT}


def _summary(lang: str, title: str) -> dict | None:
    """REST page summary, or None (missing page, disambiguation or error status)."""
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title.replace(' ', '_'), safe='')}"
    status, data = _web.get_json(url, headers=_hdr())
    if status == 429:
        raise RuntimeError("Wikipedia is rate-limiting requests")
    if status != 200 or not isinstance(data, dict) or not data.get("extract"):
        return None
    if data.get("type") == "disambiguation":
        return None
    return {"title": data.get("title") or title, "extract": data["extract"],
            "url": ((data.get("content_urls") or {}).get("desktop") or {}).get("page", "")}


def _opensearch(lang: str, topic: str) -> str:
    status, data = _web.get_json(f"https://{lang}.wikipedia.org/w/api.php", headers=_hdr(), params={
        "action": "opensearch", "search": topic, "limit": 1, "namespace": 0, "format": "json"})
    if status == 200 and isinstance(data, list) and len(data) > 1 and data[1]:
        return data[1][0]
    return ""


def _fulltext(lang: str, topic: str) -> str:
    """Full-text search (handles misspellings opensearch's prefix match misses)."""
    status, data = _web.get_json(f"https://{lang}.wikipedia.org/w/api.php", headers=_hdr(), params={
        "action": "query", "list": "search", "srsearch": topic, "srlimit": 1, "srprop": "",
        "srinfo": "suggestion", "format": "json"})
    if status != 200 or not isinstance(data, dict):
        return ""
    q = data.get("query") or {}
    if q.get("search"):
        return q["search"][0].get("title", "")
    return (q.get("searchinfo") or {}).get("suggestion", "")


def lookup(topic: str, lang: str) -> dict | None:
    if page := _summary(lang, topic):
        return page
    for find in (_opensearch, _fulltext):
        title = find(lang, topic)
        if title and title.lower() != topic.lower() and (page := _summary(lang, title)):
            return page
    return None


def _clip(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= MAX_CHARS:
        return text
    cut = text[:MAX_CHARS]
    end = max(cut.rfind(". "), cut.rfind("। "))
    return cut[: end + 1] if end > 200 else cut.rstrip() + "…"


@tool(group="web", safety="safe",
      description="Wikipedia summary of a person, place or topic (fuzzy names ok); lang en, ne or hi.")
def wikipedia(topic: str, lang: str = "en") -> str:
    """Look a topic up on Wikipedia.

    Args:
        topic: Person, place or thing, e.g. "CarryMinati" or "Kathmandu".
        lang: Wikipedia language code: en, ne (Nepali) or hi (Hindi).
    """
    topic = " ".join((topic or "").split())
    lang = (lang or "en").strip().lower()
    if not topic:
        return "error: say what to look up"
    if not _LANG.match(lang):
        lang = "en"
    key = ("wiki", lang, topic.lower())
    if (hit := _web.cache.get(key)) is not None:
        return hit
    try:
        page = lookup(topic, lang)
        if page is None and lang != "en":
            page = lookup(topic, "en")
    except Exception as e:
        log.warning("wikipedia failed: %s", e)
        return f"error: Wikipedia unavailable ({e}); try web_search instead"
    if page is None:
        return f"No Wikipedia article found for {topic!r}; try web_search."
    text = f"{page['title']}: {_clip(page['extract'])}" + (f" ({page['url']})" if page["url"] else "")
    _web.cache.set(key, text)
    return text
