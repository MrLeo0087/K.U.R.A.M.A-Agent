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


def put(url: str, title: str = "", browser: str = "") -> None:
    """An empty url = the browser's last window closed (no tab open any more)."""
    store.kv_set(KEY, json.dumps({"url": url.strip(), "title": title.strip()[:300], "browser": browser[:30],
                                  "ts": time.time()}))


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
_SEL: dict = {"text": "", "url": "", "title": "", "ts": 0.0, "editable": False}


def put_selection(text: str, url: str = "", title: str = "", editable: bool = False) -> None:
    _SEL.update(text=(text or "")[:8000], url=(url or "")[:2000], title=(title or "").strip()[:300], ts=time.time(),
                editable=bool(editable))


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
