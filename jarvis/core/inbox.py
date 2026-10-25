"""Message inbox for the laptop: WhatsApp Web, Facebook/Messenger, Instagram and email — newest and unread.

Sources (all on the laptop, 0 tokens, nothing leaves it):
  1. Desktop notifications. Brave/Chrome show a native notification for every new WhatsApp Web / Messenger /
     Instagram / Gmail message (when the site is open and allowed to notify). The msg_watch worker listens to them on
     the session D-Bus (dbus-monitor, read-only) and stores sender + text here (data/inbox.db, kept
     config.INBOX_KEEP_HOURS). Only these four kinds are kept; other apps' notifications are ignored.
  2. Unread counts from the browser tab titles ("(3) WhatsApp", "Inbox (12) - Gmail") via window titles and, when
     screen control is enabled, every tab (AT-SPI).
  3. Email over IMAP when GMAIL_USER + GMAIL_APP_PASSWORD (a Google app password) are in .env: real unread count
     and the newest unread senders/subjects even if no Gmail tab is open.
"""
from __future__ import annotations

import html
import logging
import re
import sqlite3
import threading
import time
from pathlib import Path

from jarvis.core import config

log = logging.getLogger(__name__)
SOURCES = ("whatsapp", "facebook", "instagram", "email")
LABEL = {"whatsapp": "WhatsApp", "facebook": "Facebook", "instagram": "Instagram", "email": "Email"}
_DOMAINS = (("web.whatsapp.com", "whatsapp"), ("whatsapp", "whatsapp"), ("messenger.com", "facebook"),
            ("facebook.com", "facebook"), ("instagram.com", "instagram"), ("mail.google.com", "email"),
            ("gmail", "email"), ("outlook.live.com", "email"), ("outlook.office", "email"), ("mail.yahoo", "email"),
            ("proton.me", "email"))
_MAIL_APPS = ("thunderbird", "evolution", "geary", "mailspring", "betterbird")
_lock = threading.Lock()


def _db() -> sqlite3.Connection:
    p = Path(config.DATA_DIR) / "inbox.db"
    c = sqlite3.connect(p, timeout=10)
    c.execute("CREATE TABLE IF NOT EXISTS msgs (id INTEGER PRIMARY KEY, ts REAL, source TEXT, sender TEXT, "
              "text TEXT, read INTEGER DEFAULT 0)")
    c.execute("CREATE INDEX IF NOT EXISTS msgs_ts ON msgs(ts)")
    return c


def classify(app: str, summary: str, body: str) -> tuple[str, str, str] | None:
    """(source, sender, text) for a notification from one of the four kinds, else None."""
    raw = f"{app}\n{body}".lower()
    src = next((s for d, s in _DOMAINS if d in raw), None)
    if not src and any(a in (app or "").lower() for a in _MAIL_APPS):
        src = "email"
    if not src:
        return None
    text = html.unescape(re.sub(r"<[^>]+>", "", body or ""))
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    lines = [ln for ln in lines if not re.fullmatch(r"(?:https?://)?(?:www\.)?[\w.-]+\.(?:com|me|net|org)/?\S*", ln)]
    sender = html.unescape(re.sub(r"<[^>]+>", "", summary or "")).strip()
    sender = re.sub(r"\s*[-|]\s*(?:WhatsApp|Messenger|Facebook|Instagram|Gmail)$", "", sender, flags=re.I)
    return src, sender[:80], " ".join(lines)[:500]


def add(source: str, sender: str, text: str, ts: float | None = None) -> bool:
    """Store one message; False for a duplicate of the same message in the last 10 s (D-Bus can relay twice)."""
    ts = ts or time.time()
    with _lock, _db() as c:
        dup = c.execute("SELECT 1 FROM msgs WHERE source=? AND sender=? AND text=? AND ts>?",
                        (source, sender, text, ts - 10)).fetchone()
        if dup:
            return False
        c.execute("INSERT INTO msgs(ts, source, sender, text) VALUES (?,?,?,?)", (ts, source, sender, text))
    return True


def prune() -> None:
    with _lock, _db() as c:
        c.execute("DELETE FROM msgs WHERE ts < ?", (time.time() - config.INBOX_KEEP_HOURS * 3600,))


def query(source: str = "all", sender: str = "", unread_only: bool = False, hours: float = 24,
          limit: int = 10) -> list[dict]:
    sql, args = "SELECT id, ts, source, sender, text, read FROM msgs WHERE ts > ?", [time.time() - hours * 3600]
    if source and source != "all":
        sql += " AND source = ?"
        args.append(source)
    if sender:
        sql += " AND LOWER(sender) LIKE ?"
        args.append(f"%{sender.lower()}%")
    if unread_only:
        sql += " AND read = 0"
    sql += " ORDER BY ts DESC LIMIT ?"
    args.append(limit)
    with _lock, _db() as c:
        rows = c.execute(sql, args).fetchall()
    return [dict(zip(("id", "ts", "source", "sender", "text", "read"), r)) for r in rows]


def mark_read(ids: list[int] | None = None, source: str = "all") -> int:
    with _lock, _db() as c:
        if ids:
            cur = c.execute(f"UPDATE msgs SET read=1 WHERE id IN ({','.join('?' * len(ids))})", ids)
        elif source and source != "all":
            cur = c.execute("UPDATE msgs SET read=1 WHERE read=0 AND source=?", (source,))
        else:
            cur = c.execute("UPDATE msgs SET read=1 WHERE read=0")
        return cur.rowcount


# --- unread counts from tab titles ---
_TITLE = (("whatsapp", re.compile(r"^\((\d+)\)\s*WhatsApp", re.I)),
          ("facebook", re.compile(r"^\((\d+)\)\s*(?:Facebook|Messenger)", re.I)),
          ("instagram", re.compile(r"^\((\d+)\)\s*Instagram", re.I)),
          ("email", re.compile(r"Inbox\s*\((\d[\d,]*)\)", re.I)))


def tab_counts() -> dict[str, int]:
    """Unread counts read from browser tab/window titles (0 tokens)."""
    titles: list[str] = []
    try:
        import subprocess
        out = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=5).stdout
        titles += [ln.split(None, 3)[3] for ln in out.splitlines() if len(ln.split(None, 3)) == 4]
    except (OSError, Exception):  # noqa: BLE001
        pass
    try:  # every tab (not just the active one) when the browser exposes accessibility
        from jarvis.core import uiagent
        snap = uiagent.snapshot("brave")
        titles += [i["name"] for i in snap.get("items", []) if i["role"] == "page tab"]
    except Exception:  # noqa: BLE001 - no accessibility: window titles only
        pass
    counts: dict[str, int] = {}
    for t in titles:
        for src, rx in _TITLE:
            if m := rx.search(t):
                counts[src] = max(counts.get(src, 0), int(m.group(1).replace(",", "")))
    return counts


# --- email over IMAP (optional) ---
def imap_unread(limit: int = 5) -> dict | None:
    """{count, latest:[(from, subject)]} from Gmail over IMAP, or None when not configured / failing."""
    user, pw = config.GMAIL_USER, config.GMAIL_APP_PASSWORD
    if not (user and pw):
        return None
    import email
    import imaplib
    from email.header import decode_header, make_header
    try:
        m = imaplib.IMAP4_SSL(config.IMAP_HOST, timeout=15)
        m.login(user, pw)
        m.select("INBOX", readonly=True)  # readonly: never marks anything as read
        typ, data = m.search(None, "UNSEEN")
        ids = data[0].split() if typ == "OK" and data and data[0] else []
        latest = []
        for i in reversed(ids[-limit:]):
            typ, msg = m.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if typ != "OK" or not msg or not isinstance(msg[0], tuple):
                continue
            h = email.message_from_bytes(msg[0][1])
            frm = str(make_header(decode_header(h.get("From", ""))))
            frm = re.sub(r"\s*<[^>]+>", "", frm).strip('" ') or frm
            latest.append((frm[:60], str(make_header(decode_header(h.get("Subject", "")))).strip()[:90]))
        m.logout()
        return {"count": len(ids), "latest": latest}
    except Exception as e:  # noqa: BLE001 - wrong password / offline -> just no IMAP part
        log.warning("IMAP check failed: %s", e)
        return {"error": str(e)[:120]}


# --- text for the tool ---
def _ago(ts: float) -> str:
    s = time.time() - ts
    return "just now" if s < 60 else f"{int(s // 60)} min ago" if s < 3600 else f"{int(s // 3600)} h ago" \
        if s < 86400 else f"{int(s // 86400)} d ago"


def _fmt(rows: list[dict]) -> str:
    return "\n".join(f"{i}. [{LABEL[r['source']]}] {r['sender'] or '?'}: {r['text'] or '(no text)'} "
                     f"({_ago(r['ts'])})" for i, r in enumerate(rows, 1))


def report(source: str = "all", unread: bool = True, sender: str = "", hours: float = 24, limit: int = 10) -> str:
    """'Unread' = new since you last asked (then marked read); also live tab counts + IMAP unread email."""
    source = source if source in SOURCES else "all"
    rows = query(source, sender, unread_only=unread, hours=hours, limit=limit)
    parts = []
    counts = tab_counts()
    mail = imap_unread() if source in ("all", "email") else None
    if mail and "count" in mail:
        counts["email"] = mail["count"]
    shown = {k: v for k, v in counts.items() if v and (source == "all" or k == source)}
    if shown:
        parts.append("Unread now: " + ", ".join(f"{LABEL[k]} {v}" for k, v in shown.items()))
    if rows:
        head = ("New messages" if unread else "Latest messages") + (f" from {sender}" if sender else "") + ":"
        parts.append(head + "\n" + _fmt(rows))
        if unread:
            mark_read([r["id"] for r in rows])
    if mail and mail.get("latest") and not any(r["source"] == "email" for r in rows):
        parts.append("Unread email:\n" + "\n".join(f"- {f}: {s}" for f, s in mail["latest"]))
    if mail and "error" in mail:
        parts.append(f"(Email check failed: {mail['error']})")
    if not parts:
        what = LABEL.get(source, "messages") if source != "all" else "messages"
        return (f"No {'new ' if unread else ''}{what}{' from ' + sender if sender else ''} in the last "
                f"{int(hours)} h." + ("" if _watching() else " (The message watcher isn't running.)"))
    return "\n".join(parts)


def _watching() -> bool:
    from jarvis.core import store
    try:
        return time.time() - float(store.kv_get("msg_watch_alive") or 0) < 120
    except ValueError:
        return False
