"""open_url: open a URL or a known site (youtube, google, github, gmail...) in the browser (safe)."""
from __future__ import annotations

import re
import shutil
import subprocess
from urllib.parse import quote

from jarvis.core.registry import tool

SITES = {
    "youtube": "https://www.youtube.com", "google": "https://www.google.com",
    "github": "https://github.com", "gmail": "https://mail.google.com", "mail": "https://mail.google.com",
    "chatgpt": "https://chatgpt.com", "claude": "https://claude.ai", "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com", "twitter": "https://x.com", "x": "https://x.com",
    "reddit": "https://www.reddit.com", "wikipedia": "https://www.wikipedia.org",
    "stackoverflow": "https://stackoverflow.com", "stack overflow": "https://stackoverflow.com",
    "linkedin": "https://www.linkedin.com", "netflix": "https://www.netflix.com",
    "spotify": "https://open.spotify.com", "whatsapp": "https://web.whatsapp.com",
    "maps": "https://maps.google.com", "google maps": "https://maps.google.com",
    "drive": "https://drive.google.com", "google drive": "https://drive.google.com",
    "groq": "https://console.groq.com", "amazon": "https://www.amazon.com",
    "colab": "https://colab.research.google.com", "google colab": "https://colab.research.google.com", "collab": "https://colab.research.google.com",
    "sofascore": "https://www.sofascore.com", "daraz": "https://www.daraz.com.np", "tiktok": "https://www.tiktok.com",
    "cricbuzz": "https://www.cricbuzz.com", "espn": "https://www.espn.com", "chess": "https://www.chess.com",
    "यूट्यूब": "https://www.youtube.com", "युट्युब": "https://www.youtube.com",
}


def resolve(target: str) -> str | None:
    t = target.strip().strip("\"'").rstrip("/.")
    key = re.sub(r"^(?:open\s+)?(?:the\s+)?", "", t.lower()).strip()
    key = re.sub(r"\s+(?:website|site|web\s*site|\.com)$", "", key)
    if key in SITES:
        return SITES[key]
    if re.match(r"^https?://\S+$", t, re.I):
        return t
    if re.match(r"^(?:www\.)?[\w-]+(?:\.[\w-]+)+(?:/\S*)?$", t):
        return "https://" + t
    if re.sub(r"[\s-]+", "", key) in SITES:  # "sofa score", "you tube"
        return SITES[re.sub(r"[\s-]+", "", key)]
    import difflib
    if close := difflib.get_close_matches(re.sub(r"[\s-]+", "", key), list(SITES), n=1, cutoff=0.82):
        return SITES[close[0]]  # "sofiscore" -> sofascore, "facebok" -> facebook
    return None


def find_site(target: str) -> str | None:
    """Any other site name ("hamro patro"): DuckDuckGo's "I'm feeling ducky" jumps straight to the top hit."""
    key = re.sub(r"\s+(?:website|site|web\s*site)$", "", target.strip().strip("\"'").lower())
    if re.match(r"^[\w][\w .&'-]{1,40}$", key) and len(key.split()) <= 4:
        return "https://duckduckgo.com/?q=" + quote("\\" + key + " official site")
    return None


def _open(url: str) -> None:
    """Non-blocking xdg-open (patched in tests: never opens a real browser there)."""
    exe = shutil.which("xdg-open")
    if not exe:
        raise RuntimeError("xdg-open not found: install xdg-utils")
    subprocess.Popen([exe, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


@tool(group="browser", safety="safe", description="Open a website in the browser: a URL, a domain or ANY site name (unknown names are found automatically).")
def open_url(target: str) -> str:
    """Open a site in the default browser.

    Args:
        target: A URL, a domain (example.com) or just the site's name as the user said it (e.g. sofascore).
    """
    url = resolve(target) or find_site(target)
    if url is None:
        return f"error: don't know a website called {target!r}; give a URL or domain"
    _open(url)
    return f"opened {target if 'duckduckgo.com' in url else url}"
