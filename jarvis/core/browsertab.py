"""The tab open in the browser right now, told by KURAMA's tiny browser extension (browser_ext/, load it once in
Brave: brave://extensions -> Developer mode -> Load unpacked). "Save this link", "download this video",
"what is this page" use it; without the extension the browser's history is searched by window title instead
(readlater.current_page). Kept in the kv table, so every process (API, workers, Telegram) sees it. 0 tokens.
"""
from __future__ import annotations

import json
import time

from jarvis.core import config, store

KEY = "browser_tab"


def put(url: str, title: str = "", browser: str = "", tabs: list | None = None) -> None:
    """An empty url = the browser's last window closed (no tab open any more). tabs: every tab of that window
    [{i: position from 1, title, url}] (extension 1.3+; older versions send none)."""
    rows = [{"i": int(t.get("i") or 0), "title": str(t.get("title") or "")[:120], "url": str(t.get("url") or "")[:300]}
            for t in (tabs or []) if str(t.get("i") or "").isdigit()]
    store.kv_set(KEY, json.dumps({"url": url.strip(), "title": title.strip()[:300], "browser": browser[:30],
                                  "tabs": rows, "ts": time.time()}))


def tabs() -> list[dict]:
    """Every tab of the browser window in use ([] = no extension 1.3, or the browser is closed)."""
    try:
        d = json.loads(store.kv_get(KEY) or "{}")
    except ValueError:
        return []
    return d.get("tabs") or [] if d.get("url") else []


def find_tab(name: str) -> dict | None:
    """The tab a loose name means ('facebook', 'the github one', 'chat gpt'): its site or title, best match."""
    import difflib
    import re
    from urllib.parse import urlparse
    key = re.sub(r"[^a-z0-9]+", "", (name or "").lower())
    if len(key) < 2:
        return None
    best, best_score = None, 0.0
    for t in tabs():
        site = re.sub(r"^www\.", "", urlparse(t["url"]).netloc.lower())
        hay = [re.sub(r"[^a-z0-9]+", "", x) for x in (site.split(".")[0], site, t["title"].lower())]
        score = max([1.0 if key and key in h else difflib.SequenceMatcher(None, key, h[:len(key) + 4]).ratio()
                     for h in hay if h] or [0.0])
        if score > best_score:
            best, best_score = t, score
    return best if best_score >= 0.75 else None


def get(max_age_s: float | None = None) -> tuple[str, str] | None:
    """(url, title) of the open tab, or None (no extension, browser closed, or older than BROWSER_TAB_TTL_S)."""
    try:
        d = json.loads(store.kv_get(KEY) or "{}")
    except ValueError:
        return None
    age = max_age_s if max_age_s is not None else config.BROWSER_TAB_TTL_S
    if not d.get("url", "").startswith("http") or time.time() - float(d.get("ts") or 0) > age:
        return None
    return d["url"], d.get("title", "")


# the text highlighted on a page (browser_ext/selection.js), in memory only (private text is never written to disk)
_SEL: dict = {"text": "", "url": "", "title": "", "ts": 0.0, "editable": False, "paragraph": "", "heading": ""}
_PAGES: dict[str, str] = {}  # url -> the page's main text (extension 1.5, once per page; memory only, last few)


def put_selection(text: str, url: str = "", title: str = "", editable: bool = False, paragraph: str = "",
                  heading: str = "", page: str = "") -> None:
    _SEL.update(text=(text or "")[:8000], url=(url or "")[:2000], title=(title or "").strip()[:300], ts=time.time(),
                editable=bool(editable), paragraph=(paragraph or "")[:1500], heading=(heading or "")[:200])
    if page.strip() and url:
        _PAGES[url[:2000]] = page[:15000]
        while len(_PAGES) > 6:
            _PAGES.pop(next(iter(_PAGES)))


def selection_context() -> dict:
    """The highlight with its paragraph, heading, page title / URL and the page's text (Study mode)."""
    return {**_SEL, "page": _PAGES.get(_SEL.get("url") or "", "")}


def linked() -> bool:
    """The extension has reported a highlight since KURAMA started (so an empty one really means 'nothing')."""
    return _SEL["ts"] > 0


def editable() -> bool:
    """The highlighted page text is in a text box / editable area (a replacement can go there)."""
    return bool(_SEL.get("editable"))


def selection(window_title: str = "", max_age_s: float | None = None) -> str:
    """The text highlighted in the browser now ('' = nothing, too old, or that window shows another page)."""
    age = max_age_s if max_age_s is not None else config.SELECTION_MEMORY_S
    if not _SEL["text"].strip() or time.time() - _SEL["ts"] > age:
        return ""
    if window_title and _SEL["title"] and not window_title.startswith(_SEL["title"][:40]):
        return ""  # the browser window in front shows another tab than the one the text was highlighted in
    return _SEL["text"]


def browser_name() -> str:
    """'brave' / 'chromium' as the extension reported it ('' = unknown)."""
    try:
        return str(json.loads(store.kv_get(KEY) or "{}").get("browser") or "")
    except ValueError:
        return ""
