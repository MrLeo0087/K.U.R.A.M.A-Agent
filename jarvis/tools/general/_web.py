"""Shared helpers for the web tools: one lazy httpx client, TTL cache, HTML -> text (lxml or stdlib)."""
from __future__ import annotations

import ipaddress
import re
import threading
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from jarvis.core import config
from jarvis.tools.general._geo import TTLCache

cache = TTLCache(config.WEB_CACHE_S)
_client: Any = None
_lock = threading.Lock()
# Wikimedia rejects generic agents (403); their etiquette asks for a descriptive one.
WIKI_AGENT = ("JarvisAssistant/1.0 (personal desktop assistant; "
              "https://www.mediawiki.org/wiki/API:Etiquette) httpx")


def client() -> Any:
    global _client
    with _lock:
        if _client is None:
            import httpx

            _client = httpx.Client(timeout=config.WEB_TIMEOUT_S, follow_redirects=True,
                                   headers={"User-Agent": config.WEB_USER_AGENT})
        return _client


def get_json(url: str, params: dict | None = None, headers: dict | None = None) -> tuple[int, Any]:
    """(status, parsed JSON or None). Network errors raise httpx.HTTPError."""
    r = client().get(url, params=params, headers=headers)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, None


def one_line(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def is_private_host(url: str) -> bool:
    """localhost / private / link-local IP literals (a page found online must not reach the LAN)."""
    host = (urlparse(url).hostname or "").lower()
    if host in ("localhost", "") or host.endswith(".local") or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


_DROP = ("script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside", "iframe",
         "template", "button")
_BR = "\ue000"  # block-break marker: private-use char (XML-safe for lxml, not regex whitespace)
_BLOCK = ("p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "pre")


class _Stdlib(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in _DROP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK:
            self.parts.append(_BR)

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def _tidy(text: str) -> str:
    """Source newlines are just spaces; only block-element breaks (_BR) become line breaks."""
    lines = (re.sub(r"\s+", " ", ln).strip() for ln in text.split(_BR))
    return "\n".join(ln for ln in lines if len(ln) > 1)


def html_to_text(html: str) -> tuple[str, str]:
    """(title, readable text). lxml when importable (lazy), else html.parser."""
    try:
        import lxml.html  # lazy: ~10 MB, only while a page is being read

        doc = lxml.html.fromstring(html)
        for el in doc.xpath("//" + " | //".join(_DROP)):
            el.drop_tree()
        title = (doc.findtext(".//title") or "").strip()
        for el in doc.iter(*_BLOCK):
            el.tail = _BR + (el.tail or "")
        root = next((found[0] for xp in ("//main", "//article", "//body") if (found := doc.xpath(xp))), doc)
        text = root.text_content()  # main content first; never the <head> (title text)
        return title, _tidy(text)
    except ImportError:
        pass
    except Exception:  # broken markup: fall through to the forgiving stdlib parser
        pass
    p = _Stdlib()
    p.feed(html)
    return p.title.strip(), _tidy("".join(p.parts))
