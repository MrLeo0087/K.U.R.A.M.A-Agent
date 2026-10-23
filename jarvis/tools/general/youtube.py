"""youtube: play the first YouTube video for a query, open search results, or control the YouTube
browser tab (pause/next/fullscreen via wmctrl + xdotool keys k, shift+n, f). Safe."""
from __future__ import annotations

import re
import time
from typing import Literal
from urllib.parse import quote_plus

from jarvis.core import config
from jarvis.core.registry import tool
from jarvis.tools.general import _sys, open_url

RESULTS = "https://www.youtube.com/results?search_query={q}"
KEYS = {"pause": "k", "next": "shift+n", "fullscreen": "f"}
_VID = re.compile(r'"videoId":"([\w-]{11})"')


def _ddg_video(query: str) -> str | None:
    try:
        from ddgs import DDGS  # lazy
        rows = DDGS(timeout=int(config.WEB_TIMEOUT_S)).videos(f"{query} youtube", max_results=8) or []
    except Exception:
        return None
    for r in rows:
        url = r.get("content") or r.get("embed_url") or ""
        if re.search(r"youtube\.com/watch\?v=|youtu\.be/", url):
            return url
    return None


def _scrape(query: str) -> str | None:
    try:
        from jarvis.tools.general import _web
        r = _web.client().get(RESULTS.format(q=quote_plus(query)))
        m = _VID.search(r.text)
    except Exception:
        return None
    return f"https://www.youtube.com/watch?v={m.group(1)}" if m else None


def first_video(query: str) -> str | None:
    return _ddg_video(query) or _scrape(query)


def youtube_window() -> str | None:
    out = _sys.run(["wmctrl", "-l"], timeout=4)
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and "youtube" in parts[3].lower():
            return parts[0]
    return None


@tool(group="media", safety="safe", description="Play a YouTube video for a query, search YouTube, or pause/next/fullscreen the YouTube tab.")
def youtube(query: str = "", action: Literal["play", "search", "pause", "next", "fullscreen"] = "play") -> str:
    """YouTube.

    Args:
        query: What to play or search (for play/search).
        action: play (first video), search (results page), pause (toggle), next, or fullscreen.
    """
    if action in KEYS:
        try:
            win = youtube_window()
            if not win:
                return "error: no YouTube window is open"
            _sys.run(["wmctrl", "-i", "-a", win], timeout=4)
            time.sleep(0.3)
            _sys.run(["xdotool", "key", "--clearmodifiers", KEYS[action]], timeout=4)
        except _sys.SysError as e:
            return f"error: {e}"
        return {"pause": "Toggled play/pause on YouTube.", "next": "Next video on YouTube.",
                "fullscreen": "Toggled YouTube full screen."}[action]
    query = query.strip()
    if not query:
        open_url._open("https://www.youtube.com")
        return "Opened YouTube."
    url = first_video(query) if action == "play" else None
    try:
        open_url._open(url or RESULTS.format(q=quote_plus(query)))
    except RuntimeError as e:
        return f"error: {e}"
    return f"Playing {query} on YouTube." if url else f"Opened YouTube results for {query}."
