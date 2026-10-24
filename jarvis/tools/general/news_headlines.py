"""news_headlines: top headlines from Google News RSS (free, no key; cached 15 min) (safe)."""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from urllib.parse import quote

from jarvis.core import config
from jarvis.core.registry import tool

_cache: dict[str, tuple[float, str]] = {}


def fetch_rss(url: str) -> str:
    """Download the feed (patched in tests: no network)."""
    import httpx
    r = httpx.get(url, timeout=config.HTTP_TIMEOUT_S, follow_redirects=True,
                  headers={"User-Agent": config.WEB_USER_AGENT})
    r.raise_for_status()
    return r.text


@tool(group="daily", safety="safe", max_chars=1200,
      description="Latest news headlines: Nepal, world, or any topic (e.g. 'cricket', 'AI', 'technology').")
def news_headlines(topic: str = "", count: int = 5) -> str:
    """News headlines.

    Args:
        topic: Empty = top news in Nepal; "world" = world news; anything else = news about that topic.
        count: How many headlines (1-10).
    """
    topic = (topic or "").strip()
    count = max(1, min(int(count or 5), 10))
    if not topic:
        url = "https://news.google.com/rss/search?q=Nepal&hl=en-NP&gl=NP&ceid=NP:en"
    elif topic.lower() == "world":
        url = "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en"
    else:
        url = f"https://news.google.com/rss/search?q={quote(topic)}&hl=en-US&gl=US&ceid=US:en"
    key = f"{url}|{count}"
    if (hit := _cache.get(key)) and time.time() - hit[0] < 900:
        return hit[1]
    try:
        root = ET.fromstring(fetch_rss(url))
    except Exception as e:
        return f"error: couldn't load the news ({type(e).__name__})"
    items = root.findall("./channel/item")[:count]
    if not items:
        return f"no headlines found for {topic or 'Nepal'}"
    lines = []
    for it in items:
        title = (it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        lines.append(f"- {title}" + (f" ({src})" if src else ""))
    out = f"Headlines{' about ' + topic if topic else ' in Nepal'}:\n" + "\n".join(lines)
    _cache[key] = (time.time(), out)
    return out
