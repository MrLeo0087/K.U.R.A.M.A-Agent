"""Links = named links the user keeps ('this is the link for Claude Code, save it' -> later 'give me my Claude Code
link'). Excel ~/Documents/KURAMA/links.xlsx (Name, Link, Title, Site, Saved, Used), editable by hand.

Where the link comes from (the user never has to paste it): a URL in the message -> the highlighted link (or a
link's words: the href from the browser's HTML copy) -> the page open in the browser (its history file, by the window
title). No name given -> KURAMA asks 'what should I call it?' and the next short reply is the name (LINK_NAME_TTL_S).
Asking for a link that isn't saved falls through to the AI, which answers from its own knowledge. 0 tokens.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from jarvis.core import config, sheets, store

HEAD = ["Name", "Link", "Title", "Site", "Saved", "Used"]
WIDTHS = (24, 60, 50, 22, 17, 17)
PENDING_KEY = "links_pending"  # a found link waiting for its name: {"url", "title", "ts"}
URL = re.compile(r"https?://[^\s<>\"')\]]+|\b(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|io|ai|dev|app|np|in|co|me|"
                 r"edu|gov|so|gg|tv|ly)(?:/[^\s<>\"')\]]*)?", re.I)


def path() -> Path:
    return Path(config.LINKS_FILE).expanduser()


def _rows() -> list[dict]:
    return sheets.load(path(), HEAD)


def _save(rows: list[dict]) -> None:
    sheets.save(path(), HEAD, rows, "Links", WIDTHS)


def clean_name(name: str) -> str:
    n = " ".join((name or "").split()).strip(" .,!?:;\"'")
    n = re.sub(r"^(?:my|the|our|a|an)\s+", "", n, flags=re.I)
    n = re.sub(r"(?:'s)?\s+(?:link|url|page|site|website|address)$", "", n, flags=re.I)
    return n.strip(" .,\"'")[:60]


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9ऀ-ॿ]+", "", (s or "").lower())


def lookup(name: str) -> dict | None:
    """The saved link a loose name means: same name, then name inside / inside name, then the site or title."""
    k = _key(clean_name(name))
    if len(k) < 2 or not path().exists():
        return None
    rows = _rows()
    for test in (lambda r: _key(r["name"]) == k,
                 lambda r: k in _key(r["name"]) or (len(_key(r["name"])) >= 3 and _key(r["name"]) in k),
                 lambda r: k in _key(r["site"]) or (len(k) >= 4 and k in _key(r["title"]))):
        hits = [r for r in rows if test(r)]
        if hits:
            return hits[0]
    return None


def _norm_url(u: str) -> str:
    u = u.rstrip(".,;")
    return u if re.match(r"https?://", u, re.I) else "https://" + u


def find_link(url: str = "") -> tuple[str, str] | str:
    """(url, title) the user means, or a message saying what to do."""
    if url:
        return _norm_url(url), ""
    from jarvis.core import readlater, rewrite
    wid, _ = rewrite.target_window()
    title = rewrite._window_name(wid) if wid else ""
    g = rewrite.grab()
    sel = g.text if isinstance(g, rewrite.Grab) else ""
    if m := URL.search(sel):
        return _norm_url(m.group(0)), ""
    if sel and (found := readlater.selected_links()):
        return found[0]
    if page := readlater.current_page(title):
        return page
    return "I couldn't find a link. Select the link (or open the page in your browser) and say it again."


_ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
        "ninth": 9, "tenth": 10, "last": -1}


def position(text: str) -> int | None:
    """'2', '2nd', 'second', 'no 2', 'the second one' -> 2; 'last' -> -1; None when it isn't a position."""
    t = re.sub(r"\b(?:the|one|link|item|number|no|#)\b|[.#]", " ", (text or "").lower()).split()
    if len(t) != 1:
        return None
    if m := re.fullmatch(r"(\d{1,3})(?:st|nd|rd|th)?", t[0]):
        return int(m.group(1))
    return _ORD.get(t[0])


def _said() -> str:
    """What the user typed/said in this request ('' outside a tool call, e.g. tests calling run() directly)."""
    try:
        from jarvis.core import safety
        return str(safety.context().get("user_text") or "")
    except Exception:  # noqa: BLE001
        return ""


def _from_user(url: str, name: str) -> tuple[str, str]:
    """Only what the user gave in THIS request counts: the AI copied an old link and an old name from the chat
    ('save this link name notion' saved the site opened a turn before; 'save this link for whatsapp' was named
    'notion'). A link not in the message -> the open page / highlight; a name not in the message -> KURAMA asks."""
    said = _said()
    if not said:
        return url, name
    if url and _norm_url(url).split("://")[-1].removeprefix("www.").rstrip("/") not in said:
        url = ""
    if name and _key(clean_name(name)) not in _key(said):
        name = ""
    return url, name


def save(name: str = "", url: str = "") -> str:
    url, name = _from_user(url, name)
    found = find_link(url)
    if isinstance(found, str):
        return found
    u, title = found
    name = clean_name(name)
    if not name or name.lower() in ("this", "that", "it", "link", "this link", "this page"):
        store.kv_set(PENDING_KEY, json.dumps({"url": u, "title": title, "ts": time.time()}))
        return f"Found {u}" + (f" ({title[:60]})" if title else "") + ". What should I call this link?"
    return _put(name, u, title)


def _put(name: str, u: str, title: str = "") -> str:
    store.kv_delete(PENDING_KEY)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    with sheets.locked(path()):
        rows = _rows()
        same = next((r for r in rows if _key(r["name"]) == _key(name)), None)
        if same:
            old = same["link"]
            same.update(link=u, title=title or same["title"], site=urlparse(u).netloc.removeprefix("www."), saved=now)
            _save(rows)
            return f"Updated '{same['name']}': {u}" + ("" if old == u else f" (was {old})")
        rows.append({"name": name, "link": u, "title": title, "site": urlparse(u).netloc.removeprefix("www."),
                     "saved": now, "used": ""})
        _save(rows)
    return f"Saved '{name}': {u}. Ask 'give me my {name} link' anytime."


def pending() -> dict | None:
    try:
        d = json.loads(store.kv_get(PENDING_KEY) or "{}")
    except ValueError:
        return None
    return d if d and time.time() - float(d.get("ts", 0)) <= config.LINK_NAME_TTL_S else None


def name_pending(name: str) -> str:
    p = pending()
    if not p:
        return "There's no link waiting for a name. Say 'save this link as <name>'."
    return _put(clean_name(name), p["url"], p.get("title", ""))


def cancel() -> str:
    store.kv_delete(PENDING_KEY)
    return "Okay, I didn't save it."


def get(name: str, open_it: bool = False) -> str:
    r = lookup(name)
    if not r:
        return f"I don't have a saved link called '{clean_name(name)}'. Say 'save this link as {clean_name(name)}' on its page."
    with sheets.locked(path()):
        rows = _rows()
        for x in rows:
            if x["name"] == r["name"]:
                x["used"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        _save(rows)
    if open_it:
        from jarvis.tools.general import open_url
        open_url._open(r["link"])
        return f"Opening {r['name']}: {r['link']}"
    try:
        from jarvis.core import rewrite
        rewrite._xclip(["-selection", "clipboard"], r["link"])
        copied = " (copied)"
    except Exception:
        copied = ""
    return f"{r['name']}: {r['link']}{copied}"


def show() -> str:
    rows = _rows() if path().exists() else []
    if not rows:
        return "No saved links yet. On a page, say 'save this link as Facebook'."
    return "🔗 Your links:\n" + "\n".join(f"{i}. {r['name']}: {r['link']}" for i, r in enumerate(rows, 1))


def _nth_row(name: str) -> dict | None:
    n = position(name)
    rows = _rows() if n is not None and path().exists() else []
    if not rows or not (-len(rows) <= (n - 1 if n > 0 else n) < len(rows)) or n == 0:
        return None
    return rows[n - 1 if n > 0 else n]


def clear() -> str:
    rows = _rows() if path().exists() else []
    if not rows:
        return "The link store is already empty."
    with sheets.locked(path()):
        import shutil
        shutil.copy2(path(), path().with_suffix(".backup.xlsx"))  # one undo copy, editable by hand
        _save([])
    return f"Removed all {len(rows)} links ({', '.join(r['name'] for r in rows)}). A copy is in {path().with_suffix('.backup.xlsx').name}."


def delete(name: str) -> str:
    if clean_name(name).lower() in ("all", "everything", "all links", "every link", "the whole list", "whole list"):
        return clear()
    r = _nth_row(name) or lookup(name)
    if not r:
        return f"No saved link called '{clean_name(name)}'."
    with sheets.locked(path()):
        _save([x for x in _rows() if x["name"] != r["name"]])
    return f"Removed the '{r['name']}' link."


def rename(name: str, new: str) -> str:
    r = _nth_row(name) or lookup(name)
    if not r:
        return f"No saved link called '{clean_name(name)}'."
    new = clean_name(new)
    with sheets.locked(path()):
        rows = _rows()
        for x in rows:
            if x["name"] == r["name"]:
                x["name"] = new
        _save(rows)
    return f"Renamed '{r['name']}' to '{new}'."


def run(action: str = "get", name: str = "", url: str = "", new_name: str = "") -> str:
    if action == "save":
        return save(name, url)
    if action == "name":
        return name_pending(name)
    if action == "cancel":
        return cancel()
    if action in ("get", "open"):
        return get(name, open_it=action == "open")
    if action == "delete":
        return delete(name)
    if action == "rename":
        return rename(name, new_name)
    return show()
