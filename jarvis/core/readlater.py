"""Read later: links saved to a real Excel sheet (~/Documents/KURAMA/read_later.xlsx), 0 tokens.

"read this later" saves the highlighted link(s); with no link selected and a browser in front, it saves the page
that is open there (its URL comes from the browser's own history file, no key presses; any highlighted text on the
page is kept as a note). Titles come from that history too, else from the page's <title> (one small download).
Columns: Title, Link, Site, Saved, Status (unread/read), Note. The sheet can be edited by hand.
"""
from __future__ import annotations

import re
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from jarvis.core import config, sheets

HEAD = ["Title", "Link", "Site", "Saved", "Status", "Note"]
WIDTHS = (50, 60, 22, 18, 10, 40)
URL = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
_BROWSERS = {  # window-title suffix -> history files (Chromium family: History; Firefox: places.sqlite)
    "Brave": ["~/.config/BraveSoftware/Brave-Browser/*/History"],
    "Google Chrome": ["~/.config/google-chrome/*/History"],
    "Chromium": ["~/.config/chromium/*/History", "~/snap/chromium/common/chromium/*/History"],
    "Mozilla Firefox": ["~/.mozilla/firefox/*/places.sqlite", "~/snap/firefox/common/.mozilla/firefox/*/places.sqlite"],
}


def path() -> Path:
    return Path(config.READ_LATER_FILE).expanduser()


# --- the open page, from the browser's history -------------------------------------------------------------------
def _browser_of(title: str) -> tuple[str, str] | None:
    """('Brave', 'Page title') when the window title is a browser's ('Page title - Brave')."""
    for name in _BROWSERS:
        if title.endswith(f" - {name}") or title.endswith(f" — {name}"):
            return name, re.sub(rf"\s+[-—]\s+{re.escape(name)}$", "", title).strip()
    return None


def _history(name: str, limit: int = 300) -> list[tuple[str, str]]:
    """[(url, title)] newest first from the browser's history (a copy: the browser keeps it locked)."""
    out: list[tuple[str, str]] = []
    for pattern in _BROWSERS[name]:
        home_rel = pattern.replace("~/", "")
        for db in sorted(Path.home().glob(home_rel), key=lambda p: p.stat().st_mtime, reverse=True)[:2]:
            with tempfile.TemporaryDirectory() as d:
                copy = Path(d) / db.name
                shutil.copy2(db, copy)
                for extra in ("-wal", "-journal"):
                    if Path(str(db) + extra).exists():
                        shutil.copy2(str(db) + extra, str(copy) + extra)
                try:
                    con = sqlite3.connect(copy)
                    q = ("SELECT url, title FROM urls ORDER BY last_visit_time DESC LIMIT ?" if db.name == "History"
                         else "SELECT url, title FROM moz_places WHERE last_visit_date IS NOT NULL "
                              "ORDER BY last_visit_date DESC LIMIT ?")
                    out += [(u, t or "") for u, t in con.execute(q, (limit,))]
                    con.close()
                except sqlite3.Error:
                    continue
    return out


def current_page(window_title: str) -> tuple[str, str] | None:
    """(url, title) of the page open in the browser window with this title."""
    b = _browser_of(window_title)
    if not b:
        return None
    name, page = b
    hist = _history(name)
    for url, title in hist:  # the newest visit whose title is the window's
        if title and (title == page or title.strip() == page.strip()):
            return url, title
    return None


def _title_for(url: str) -> str:
    for name in _BROWSERS:
        try:
            for u, t in _history(name, 2000):
                if u == url and t:
                    return t
        except OSError:
            continue
    try:
        import httpx
        with httpx.stream("GET", url, timeout=6, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}) as r:
            body = b""
            for chunk in r.iter_bytes():
                body += chunk
                if len(body) > 120_000 or b"</title>" in body.lower():
                    break
        m = re.search(rb"<title[^>]*>(.*?)</title>", body, re.I | re.S)
        if m:
            import html
            return html.unescape(m.group(1).decode("utf-8", "replace")).strip()[:200]
    except Exception:  # noqa: BLE001 - offline / blocked: the link itself is enough
        pass
    return ""


# --- the sheet -----------------------------------------------------------------------------------------------------
def _site(url: str) -> str:
    return urlparse(url).netloc.removeprefix("www.")


def add(url: str, title: str = "", note: str = "") -> str:
    url = url.strip().rstrip(".,;")
    with sheets.locked(path()) as p:
        rows = sheets.load(p, HEAD)
        if any(r["link"] == url for r in rows):
            return f"Already in your reading list: {title or url}"
        title = title or _title_for(url) or url
        rows.insert(0, {"title": title, "link": url, "site": _site(url), "saved": f"{datetime.now():%Y-%m-%d %H:%M}",
                        "status": "unread", "note": note[:300]})
        sheets.save(p, HEAD, rows, "Read later", WIDTHS)
    return f"Saved for later: {title}"


def unread() -> list[dict]:
    return [r for r in sheets.load(path(), HEAD) if r["status"].lower() != "read"]


def show(limit: int = 15) -> str:
    rows = unread()
    if not rows:
        return "Your reading list is empty. Select a link (or open a page) and say 'read this later'."
    lines = [f"{i}. {r['title'][:90]} ({r['site']}, {r['saved'][:10]})" for i, r in enumerate(rows[:limit], 1)]
    more = f"\n…and {len(rows) - limit} more in {path().name}." if len(rows) > limit else ""
    return f"Reading list ({len(rows)} unread):\n" + "\n".join(lines) + more


def _pick(n: int) -> dict | None:
    rows = unread()
    return rows[n - 1] if 1 <= n <= len(rows) else None


def _set_status(link: str, status: str | None) -> None:
    with sheets.locked(path()) as p:
        rows = sheets.load(p, HEAD)
        rows = [r for r in rows if r["link"] != link] if status is None else \
            [{**r, "status": status} if r["link"] == link else r for r in rows]
        sheets.save(p, HEAD, rows, "Read later", WIDTHS)


def open_item(n: int = 1) -> str:
    r = _pick(n)
    if r is None:
        return f"There's no item {n} in your reading list." if unread() else "Your reading list is empty."
    from jarvis.tools.general import open_url
    open_url._open(r["link"])
    _set_status(r["link"], "read")
    return f"Opened: {r['title']} (marked as read)."


def mark_read(n: int) -> str:
    r = _pick(n)
    if r is None:
        return f"There's no item {n} in your reading list."
    _set_status(r["link"], "read")
    return f"Marked as read: {r['title']}"


def remove(n: int) -> str:
    r = _pick(n)
    if r is None:
        return f"There's no item {n} in your reading list."
    _set_status(r["link"], None)
    return f"Removed: {r['title']}"


def save_this() -> str:
    """'read this later': the highlighted link(s), else the page open in the browser (+ the highlighted text)."""
    from jarvis.core import rewrite
    wid, _ = rewrite.target_window()
    title = rewrite._window_name(wid) if wid else ""
    g = rewrite.grab()
    sel = g.text if isinstance(g, rewrite.Grab) else ""
    links = list(dict.fromkeys(u.rstrip(".,;") for u in URL.findall(sel)))
    if links:
        return "\n".join(add(u) for u in links[:10])
    page = current_page(title)
    if page:
        return add(page[0], page[1], note=sel.strip())
    if _browser_of(title):
        return "I couldn't find this page's link in the browser history yet. Select the link (or the address bar) and say it again."
    return "Select a link (or open the page in your browser) and say 'read this later' again."


def run(action: str = "add", url: str = "", n: int = 0) -> str:
    if action == "add":
        return add(url) if url.strip() else save_this()
    if action == "open":
        return open_item(n or 1)
    if action == "read":
        return mark_read(n or 1)
    if action == "remove":
        return remove(n or 1)
    return show()
