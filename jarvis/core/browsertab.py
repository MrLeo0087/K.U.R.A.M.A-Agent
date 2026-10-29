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
