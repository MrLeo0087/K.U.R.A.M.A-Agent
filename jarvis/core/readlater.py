"""My list = reminders + to-dos + read later in ONE list, 0 tokens. To-dos and links live in a real Excel sheet
(~/Documents/KURAMA/read_later.xlsx); reminders stay in the scheduler table and are shown (and finished) here too.

Each row is a to-do ("add buy milk to my to-do list #shopping tomorrow 5 pm") or a link to read ("read this later
at 2 pm"). Optional tag and due time: a due item becomes a scheduler reminder (kind 'task': heads-up 10 min before,
then "do it now"); items without a time get an occasional random nudge (nudge(), at most NUDGE_PER_DAY a day,
NUDGE_HOURS only). Marking an item done REMOVES it from the sheet (and cancels its reminder).

"read this later" saves the highlighted link(s); with no link selected and a browser in front, it saves the page
that is open there (its URL comes from the browser's own history file, no key presses; any highlighted text on the
page is kept as a note). Titles come from that history too, else from the page's <title> (one small download).
Columns: Type (todo/read), Title, Link, Tag, Due, Saved, Note, Reminder (schedule id). Editable by hand.
"""
from __future__ import annotations

import json
import random
import re
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from jarvis.core import config, sheets, store

HEAD = ["Type", "Title", "Link", "Tag", "Due", "Saved", "Note", "Reminder"]
WIDTHS = (7, 50, 55, 14, 18, 17, 40, 9)
SHEET = "My list"
NUDGE_KEY = "todo_nudge"
OVERDUE = "overdue: "  # a follow-up schedule row: 'you haven't done this yet' (fired once, after the due time)
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


def _rows() -> list[dict]:
    rows = sheets.load(path(), HEAD + ["Status"])  # 'Status' only to drop rows an older version marked read
    out = []
    for r in rows:
        if r.pop("status", "").lower() == "read":
            continue
        r["type"] = r["type"] or ("read" if r["link"] else "todo")
        out.append(r)
    return out


def _save(rows: list[dict]) -> None:
    sheets.save(path(), HEAD, rows, SHEET, WIDTHS)


def _same(a: dict, b: dict) -> bool:
    return (a["type"], a["title"], a["link"], a["saved"]) == (b["type"], b["title"], b["link"], b["saved"])


def _schedule(r: dict, when_text: str) -> tuple[str, str]:
    """A due time -> a scheduler reminder (kind 'task'). Returns (due shown in the sheet, reminder id) or raises."""
    from jarvis.core import reminders, when
    w = when.resolve(when_text, datetime.now(), use_llm=False)
    if w is None:
        raise ValueError(f"I couldn't understand the time {when_text!r}")
    if w.ts <= time.time():
        raise ValueError(f"{when_text!r} is already past")
    body = f"read: {r['title']}\n{r['link']}" if r["type"] == "read" else f"todo: {r['title']}"
    sid = store.schedule_add(body, "task", w.ts, "none")
    return datetime.fromtimestamp(w.ts).strftime("%Y-%m-%d %H:%M"), str(sid)


def _due_words(due: str) -> str:
    from jarvis.core import when
    try:
        return when.describe(datetime.strptime(due, "%Y-%m-%d %H:%M").timestamp())
    except ValueError:
        return due


def _put(kind: str, title: str, link: str = "", tag: str = "", when_text: str = "", note: str = "") -> str:
    tag = tag.strip().lstrip("#").lower()
    with sheets.locked(path()):
        rows = _rows()
        if kind == "read" and any(r["link"] == link for r in rows):
            old = next(r for r in rows if r["link"] == link)
            if not when_text:
                return f"Already in your reading list: {old['title']}"
            rows = [r for r in rows if not _same(r, old)]  # same link with a time now: re-add it with the time
            _cancel(old)
        r = {"type": kind, "title": title, "link": link, "tag": tag, "due": "", "saved": f"{datetime.now():%Y-%m-%d %H:%M}",
             "note": note[:300], "reminder": ""}
        due = ""
        if when_text:
            try:
                r["due"], r["reminder"] = _schedule(r, when_text)
            except ValueError as e:
                return f"Not saved: {e}. Try 'in 2 hours', 'at 2 pm', 'tomorrow 2 pm' or 'November 28 5 pm'."
            due = f" I'll remind you {_due_words(r['due'])} (and 10 min before)."
        rows.insert(0, r)
        _save(rows)
    tagged = f" #{tag}" if tag else ""
    if kind == "read":
        return f"Saved for later: {title}{tagged}.{due}".replace("..", ".") if (due or tag) else f"Saved for later: {title}"
    return f"Added to your to-do list: {title}{tagged}.{due}"


def add(url: str, title: str = "", note: str = "", tag: str = "", when_text: str = "") -> str:
    url = url.strip().rstrip(".,;")
    return _put("read", title or _title_for(url) or url, url, tag, when_text, note)


def add_todo(text: str, tag: str = "", when_text: str = "") -> str:
    text = " ".join((text or "").split()).strip(" .,")
    if not text:
        return "What should I add to your to-do list?"
    return _put("todo", text[:1].upper() + text[1:], "", tag, when_text)


def _reminders() -> list[dict]:
    """Reminders set with 'remind me to ...' (scheduler), as list rows."""
    out = []
    for r in store.schedules_list(enabled_only=True, limit=50):
        if r.get("kind") != "reminder":
            continue
        rep = (r.get("repeat") or "none")
        out.append({"type": "reminder", "title": r["text"], "link": "", "tag": "", "saved": "", "note": "",
                    "due": datetime.fromtimestamp(r["next_run"]).strftime("%Y-%m-%d %H:%M"),
                    "reminder": str(r["id"]), "repeat": "" if rep == "none" else rep})
    return out


def ordered(tag: str = "") -> list[dict]:
    """The numbering everyone uses: reminders, then to-dos, then reading; due ones soonest first, then newest."""
    tag = tag.strip().lstrip("#").lower()
    rows = [r for r in _rows() if not tag or r["tag"] == tag]
    key = lambda r: (r["due"] or "9999", "")  # noqa: E731
    todo = sorted([r for r in rows if r["type"] != "read"], key=key)
    read = sorted([r for r in rows if r["type"] == "read"], key=key)
    return ([] if tag else _reminders()) + todo + read


def is_open(kind: str, title: str, link: str = "") -> int:
    """Its number in the list if that to-do / link is still there (not done), else 0."""
    for i, r in enumerate(ordered(), 1):
        if r["type"] == kind and (r["link"] == link if kind == "read" and link else r["title"] == title):
            return i
    return 0


def unread() -> list[dict]:
    return [r for r in ordered() if r["type"] == "read"]


def _item(i: int, r: dict) -> str:
    extra = (f"  #{r['tag']}" if r["tag"] else "") + (f"  ⏰ {_due_words(r['due'])}" if r["due"] else "")
    if r["type"] == "reminder":
        return f"{i}. {r['title'][:90]}  ⏰ {_due_words(r['due'])}" + (f" (repeats {r['repeat']})" if r.get("repeat") else "")
    if r["type"] == "read":
        site = f" ({r['link'].split('/')[2].removeprefix('www.')})" if r["link"].count("/") >= 2 else ""
        return f"{i}. {r['title'][:80]}{site}{extra}\n    {r['link']}"
    return f"{i}. {r['title'][:90]}{extra}"


def show(limit: int = 20, tag: str = "", kind: str = "") -> str:
    rows = ordered(tag)
    want = ("reminder", "todo") if kind == "todo" else (kind,) if kind else ()  # 'to-do' = reminders + tasks
    if want and rows and not any(r["type"] in want for r in rows):
        return ("Nothing on your to-do list: no tasks or reminders." if kind == "todo" else "Nothing there.") + \
            " Say 'schedule reading the book at 11:45 pm' or 'add buy milk to my to-do list'."
    if not rows:
        return ("Your list is empty." + (f" Nothing tagged #{tag}." if tag else "")
                + " Say 'add <task> to my to-do list', 'remind me to ... at 5 pm' or select a link and say 'read this later'.")
    lines, n = [f"📋 Your list ({len(rows)})" + (f" #{tag.lstrip('#')}" if tag else "")], 0
    for label, typ in (("⏰ Reminders", "reminder"), ("✅ To-do", "todo"), ("📖 Read later", "read")):
        part = [r for r in rows if r["type"] == typ]
        if want and typ not in want:
            n += len(part)
            continue
        if part:
            lines.append(label)
            for r in part:
                n += 1
                if n <= limit:
                    lines.append(_item(n, r))
    if len(rows) > limit:
        lines.append(f"…and {len(rows) - limit} more in {path().name}.")
    lines.append("Say 'done <number>' when you finish one (it's removed), 'open <number>' for a link.")
    return "\n".join(lines)


def _pick(n: int, kind: str = "") -> dict | None:
    rows = ordered()
    if kind == "read":  # 'open 1' with only links in mind: count among the links if the number points at a to-do
        if 1 <= n <= len(rows) and rows[n - 1]["type"] != "read":
            reads = unread()
            return reads[n - 1] if 1 <= n <= len(reads) else None
    return rows[n - 1] if 1 <= n <= len(rows) else None


def _cancel(r: dict) -> None:
    """Stop its reminder (and any 'not done yet' follow-up)."""
    body = f"read: {r['title']}\n{r['link']}" if r["type"] == "read" else f"todo: {r['title']}"
    for s in store.schedules_list(enabled_only=True, limit=100):
        if s.get("kind") == "task" and s["text"] == OVERDUE + body:
            store.schedule_update(s["id"], enabled=0)
    if (r.get("reminder") or "").isdigit():
        try:
            store.schedule_update(int(r["reminder"]), enabled=0)
        except Exception:
            pass


def _drop(r: dict) -> None:
    if r["type"] == "reminder":
        _cancel_id(r)
        return
    with sheets.locked(path()):
        _save([x for x in _rows() if not _same(x, r)])
    _cancel(r)


def _cancel_id(r: dict) -> None:
    if (r.get("reminder") or "").isdigit():
        store.schedule_update(int(r["reminder"]), enabled=0)


def open_item(n: int = 1) -> str:
    r = _pick(n, "read")
    if r is None or r["type"] != "read":
        return f"There's no link {n} in your list." if _rows() else "Your list is empty."
    from jarvis.tools.general import open_url
    open_url._open(r["link"])
    _drop(r)
    return f"Opened: {r['title']} (done, removed from your list)."


def done(n: int) -> str:
    r = _pick(n)
    if r is None:
        return f"There's no item {n} in your list."
    _drop(r)
    left = len(ordered())
    what = "reminder cancelled" if r["type"] == "reminder" else "removed"
    return f"✔ Done: {r['title']} ({what}). {left} left." if left else f"✔ Done: {r['title']}. Your list is empty now 🎉"


mark_read = done


def remove(n: int) -> str:
    r = _pick(n)
    if r is None:
        return f"There's no item {n} in your list."
    _drop(r)
    return f"Removed: {r['title']}"


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 2 or w.isdigit()} - {
        "the", "and", "for", "from", "list", "todo", "task", "my"}


def find(text: str, kinds: tuple[str, ...] = ("reminder", "todo", "read")) -> dict | None:
    """The list item a loose title means ('the review 30 day study plan' -> 'Review 30-day exam plan')."""
    want = _words(text)
    if not want:
        return None
    best, score = None, 0.0
    for r in ordered():
        if r["type"] not in kinds:
            continue
        have = _words(r["title"].replace("-", " ").replace("‑", " "))
        if not have:
            continue
        s = len(want & have) / len(want | have)
        if text.lower().strip() in r["title"].lower():
            s = 1.0
        if s > score:
            best, score = r, s
    return best if score >= 0.34 else None


def remove_named(text: str) -> str:
    r = find(text)
    if r is None:
        return f"I couldn't find '{text}' in your list.\n" + show(kind="todo")
    _drop(r)
    return f"Removed: {r['title']}. " + (f"{len(ordered())} left." if ordered() else "Your list is empty now 🎉")


def reschedule(text: str, when_text: str) -> str:
    """'move reading the book to 1 am': a new time for a to-do or a reminder (the old alert is replaced)."""
    r = find(text, ("reminder", "todo", "read"))
    if r is None:
        return f"I couldn't find '{text}' in your list.\n" + show(kind="todo")
    from jarvis.core import when
    w = when.resolve(when_text, datetime.now(), use_llm=False)
    if w is None or w.ts <= time.time():
        return f"I couldn't use the time '{when_text}'" + (" (it's already past)." if w else ".")
    if r["type"] == "reminder":
        store.schedule_update(int(r["reminder"]), next_run=w.ts, enabled=1)
        return f"Reminder '{r['title']}' moved to {when.describe(w.ts)}."
    with sheets.locked(path()):
        rows = _rows()
        x = next((y for y in rows if _same(y, r)), None)
        if x is None:
            return f"I couldn't find '{text}' in your list."
        _cancel(x)
        x["due"], x["reminder"] = _schedule(x, when_text)
        _save(rows)
    return f"'{r['title']}' moved to {when.describe(w.ts)} (I'll remind you 10 min before)."


def rename(text: str, new: str) -> str:
    r = find(text, ("reminder", "todo", "read"))
    if r is None:
        return f"I couldn't find '{text}' in your list."
    new = new.strip(" .'\"")[:200]
    if r["type"] == "reminder":
        store.schedule_update(int(r["reminder"]), text=new)
        return f"Renamed the reminder to '{new}'."
    with sheets.locked(path()):
        rows = _rows()
        x = next((y for y in rows if _same(y, r)), None)
        if x is None:
            return f"I couldn't find '{text}' in your list."
        when_text = x["due"]
        if when_text:
            _cancel(x)
        x["title"] = new
        if when_text:
            try:
                x["due"], x["reminder"] = _schedule(x, datetime.strptime(when_text, "%Y-%m-%d %H:%M").strftime("%B %d %I:%M %p"))
            except ValueError:
                x["due"], x["reminder"] = "", ""
        _save(rows)
    return f"Renamed '{r['title']}' to '{new}'."


def clear(kind: str = "todo") -> str:
    """'remove all my tasks': every to-do and reminder (kind 'todo'), or the reading list (kind 'read')."""
    kinds = ("reminder", "todo") if kind == "todo" else ("read",)
    gone = [r for r in ordered() if r["type"] in kinds]
    for r in gone:
        _drop(r)
    if not gone:
        return "Nothing to remove: your to-do list is already empty." if kind == "todo" else "Your reading list is already empty."
    return f"Removed {len(gone)}: " + ", ".join(r["title"][:40] for r in gone) + "."


def today() -> str:
    """'What's on today?': reminders + to-dos, today's classes, and the running long tasks, in one short answer."""
    parts = []
    rows = [r for r in ordered() if r["type"] in ("reminder", "todo")]
    parts.append(show(kind="todo") if rows else "✅ To-do: nothing yet.")
    try:
        from jarvis.core import study
        if study.classes():
            parts.append(study.show("today"))
    except Exception:
        pass
    try:
        from jarvis.core import goals
        live = [g for g in goals.all_goals() if g["status"] == "active"]
        if live:
            parts.append("📂 Long tasks:\n" + "\n".join(goals.status_text(g) for g in live))
    except Exception:
        pass
    return "\n\n".join(parts)


PENDING_KEY = "todo_pending"  # 'schedule a task' with no task/time: the next short reply fills it in


def ask_details(text: str = "") -> str:
    store.kv_set(PENDING_KEY, json.dumps({"ts": time.time(), "text": text}))
    return "What should I add, and when? For example: 'reading the book at 12:15 am'."


def pending() -> bool:
    try:
        d = json.loads(store.kv_get(PENDING_KEY) or "{}")
    except ValueError:
        return False
    return bool(d) and time.time() - float(d.get("ts", 0)) <= 180


def clear_pending() -> None:
    store.kv_delete(PENDING_KEY)


def nudge(now: float | None = None) -> str | None:
    """Now and then (random time, at most NUDGE_PER_DAY a day, NUDGE_HOURS only) remind the user of ONE open item
    that has no due time. Returns the message sent, or None. Cheap: a kv read until it's time."""
    now = now if now is not None else time.time()
    lt = time.localtime(now)
    day = time.strftime("%Y-%m-%d", lt)
    try:
        st = json.loads(store.kv_get(NUDGE_KEY, "{}") or "{}")
    except ValueError:
        st = {}
    if st.get("day") != day:
        st = {"day": day, "count": 0, "next": 0, "last": st.get("last", "")}
    lo, hi = config.NUDGE_HOURS
    if st["count"] >= config.NUDGE_PER_DAY or not lo <= lt.tm_hour < hi:
        return None
    if not st["next"]:  # pick today's random moment
        st["next"] = now + random.uniform(20 * 60, 4 * 3600)
        store.kv_set(NUDGE_KEY, json.dumps(st))
        return None
    if now < st["next"]:
        return None
    open_ = [r for r in ordered() if not r["due"]]
    st["next"] = now + random.uniform(3 * 3600, 6 * 3600)
    if not open_:
        store.kv_set(NUDGE_KEY, json.dumps(st))
        return None
    fresh = [r for r in open_ if r["title"] != st.get("last")] or open_
    r = random.choice(fresh)
    st["count"], st["last"] = st["count"] + 1, r["title"]
    store.kv_set(NUDGE_KEY, json.dumps(st))
    n = ordered().index(r) + 1
    try:
        age = (now - datetime.strptime(r["saved"], "%Y-%m-%d %H:%M").timestamp()) / 86400
    except ValueError:
        age = 0
    since = "today" if age < 1 else "yesterday" if age < 2 else f"{int(age)} days ago"
    if r["type"] == "read":
        title, body = "📖 Still want to read this?", f"{r['title']}\n{r['link']}\nYou saved it {since}. Got a few minutes?"
    else:
        title, body = "📌 From your to-do list", f"{r['title']}\nYou added it {since}. Can you do it now?"
    body += f"\n(Say 'done {n}' when it's finished.)"
    from jarvis.core import notify
    notify.notify(title, body, level="info", source="todo", telegram=True)
    return body


def selected_links() -> list[tuple[str, str]]:
    """[(url, text)] of the links inside what was just copied (browsers also put the selection on the clipboard as
    text/html, where every link keeps its href)."""
    import html
    import subprocess
    try:
        targets = subprocess.run(["xclip", "-selection", "clipboard", "-t", "TARGETS", "-o"], capture_output=True,
                                 timeout=3).stdout.decode(errors="replace")
        if "text/html" not in targets:
            return []
        page = subprocess.run(["xclip", "-selection", "clipboard", "-t", "text/html", "-o"], capture_output=True,
                              timeout=3).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired):
        return []
    out = []
    for href, inner in re.findall(r"<a\b[^>]*?href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", page, re.I | re.S):
        href = html.unescape(href)
        if href.startswith(("http://", "https://")):
            out.append((href, html.unescape(re.sub(r"<[^>]+>", "", inner)).strip()))
    return list(dict.fromkeys(out))[:10]


def save_this(tag: str = "", when_text: str = "") -> str:
    """'read this later': the highlighted link(s), else the page open in the browser (+ the highlighted text)."""
    from jarvis.core import rewrite
    wid, _ = rewrite.target_window()
    title = rewrite._window_name(wid) if wid else ""
    g = rewrite.grab()
    sel = g.text if isinstance(g, rewrite.Grab) else ""
    links = list(dict.fromkeys(u.rstrip(".,;") for u in URL.findall(sel)))
    if sel and not links:  # a link's words were selected ('Attention Is All You Need'): its address is in the HTML copy
        found = selected_links()
        if found:
            return "\n".join(add(u, t, tag=tag, when_text=when_text) for u, t in found)
    if links:
        return "\n".join(add(u, tag=tag, when_text=when_text) for u in links[:10])
    page = current_page(title)
    if page:
        return add(page[0], page[1], note=sel.strip(), tag=tag, when_text=when_text)
    if _browser_of(title):
        return "I couldn't find this page's link in the browser history yet. Select the link (or the address bar) and say it again."
    return "Select a link (or open the page in your browser) and say 'read this later' again."


def last() -> str:
    """'give me the read later link I gave you': the newest saved item, with its link (also copied)."""
    rows = [r for r in _rows() if r["type"] == "read"]
    if not rows:
        return "Your reading list is empty."
    r = rows[0]
    from jarvis.core import rewrite
    rewrite._xclip(["-selection", "clipboard"], r["link"])
    return f"{r['title']}\n{r['link']}\n(Copied. Saved {r['saved']}.)"


def _given(url: str) -> bool:
    """The AI may only pass a link the user really said/typed (it once invented https://example.com)."""
    from jarvis.core import safety
    said = (safety.context().get("user_text") or "")
    return bool(url) and (url.rstrip("/") in said or not said)


def run(action: str = "add", url: str = "", n: int = 0, text: str = "", tag: str = "", when: str = "") -> str:
    if action == "add":
        if url.strip() and _given(url.strip()):
            return add(url, tag=tag, when_text=when)
        return save_this(tag, when)
    if action == "todo":
        clear_pending()
        return add_todo(text, tag, when)
    if action == "last":
        return last()
    if action == "open":
        return open_item(n or 1)
    if action in ("done", "read"):
        return done(n or 1)
    if action == "remove":
        return remove_named(text) if text and not n else remove(n or 1)
    if action == "reschedule":
        return reschedule(text, when)
    if action == "rename":
        old, _, new = text.partition(" » ")
        return rename(old, new)
    if action == "clear":
        return clear(text or "todo")
    if action == "today":
        return today()
    if action == "ask":
        return ask_details(text)
    return show(tag=tag, kind={"todo": "todo", "read": "read", "reminder": "reminder"}.get(text, ""))
