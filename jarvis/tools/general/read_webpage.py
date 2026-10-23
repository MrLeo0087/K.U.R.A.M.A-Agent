"""read_webpage: fetch a public web page (6 s timeout, size cap) and return its readable text (safe)."""
from __future__ import annotations

import logging

from jarvis.core import config
from jarvis.core.registry import tool
from jarvis.tools.general import _web

log = logging.getLogger("jarvis.tools.read_webpage")
MAX_CHARS_CAP = 3000


def fetch(url: str) -> tuple[str, str]:
    """(content-type, decoded body). Stops reading past config.WEB_PAGE_MAX_BYTES."""
    with _web.client().stream("GET", url) as r:
        r.raise_for_status()
        ctype = r.headers.get("content-type", "").lower()
        buf = bytearray()
        for chunk in r.iter_bytes():
            buf += chunk
            if len(buf) >= config.WEB_PAGE_MAX_BYTES:
                break
        enc = r.charset_encoding or "utf-8"
    return ctype, bytes(buf).decode(enc, errors="replace")


@tool(group="web", safety="safe", max_chars=MAX_CHARS_CAP,
      description="Read a web page (URL) and return its main text, e.g. to summarize an article.")
def read_webpage(url: str, max_chars: int = 1500) -> str:
    """Read a web page.

    Args:
        url: Full page address, e.g. "https://example.com/article".
        max_chars: Maximum characters of text to return (200-3000).
    """
    url = (url or "").strip()
    if not url:
        return "error: give a URL"
    if "://" not in url:
        url = "https://" + url
    if not url.lower().startswith(("http://", "https://")):
        return "error: only http(s) pages can be read"
    if _web.is_private_host(url):
        return "error: local/private addresses are not read"
    limit = max(200, min(int(max_chars or 1500), MAX_CHARS_CAP))
    try:
        ctype, body = fetch(url)
    except Exception as e:
        log.warning("read_webpage %s failed: %s", url, e)
        return f"error: could not fetch the page ({type(e).__name__})"
    if "html" in ctype or body.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        title, text = _web.html_to_text(body)
    elif ctype.startswith("text/") or "json" in ctype or not ctype:
        title, text = "", body.strip()
    else:
        return f"error: not a text page ({ctype.split(';')[0]})"
    if not text:
        return "The page has no readable text."
    head = f"{title}\n" if title else ""
    out = head + text
    return out if len(out) <= limit else out[: limit - 1].rstrip() + "…"
