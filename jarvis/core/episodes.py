"""Episodic memory (P7): past chat sessions and messages, zero LLM tokens.

recall(spec): "last" (the previous session), "today" / "yesterday" / a weekday / "YYYY-MM-DD"
(that day's sessions), or free text (FTS5 over past messages + LIKE over session summaries).
Answers are short dated snippets capped at config.SESSION_RECALL_MAX_CHARS.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta

from jarvis.core import config, store

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_STOP = set("""a an and are as at be by can could did do does for from had has have how i if in into is it its
me my of on or our please show tell that the their them then there these this to was we were what when where
which who why will with would you your jarvis kurama okay ok yes no hi hello hey thanks thank just like
open give make get let set turn want need know about today yesterday now right also some more much very
what's it's i'm don't can't kya hai ho cha ma ko ki actually currently really something thing things
going gonna wanna sure sorry well good great fine need please""".split())
_LAST = {"last", "last time", "previous", "earlier", "before", "last session", ""}


def day_bounds(day: datetime) -> tuple[float, float]:
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def parse_day(spec: str, now: datetime | None = None) -> tuple[float, float, str] | None:
    """(start, end, label) for today/yesterday/weekday/ISO date (also 'this morning'), else None."""
    now = now or datetime.now()
    s = (spec or "").strip().lower()
    s = re.sub(r"^(?:on|from|of)\s+", "", s)
    if s in ("today", "this morning", "this evening", "tonight", "aaja", "aaj", "आज"):
        t0, t1 = day_bounds(now)
        return t0, t1, "today"
    if s in ("yesterday", "hijo", "kal", "हिजो", "कल"):
        t0, t1 = day_bounds(now - timedelta(days=1))
        return t0, t1, "yesterday"
    if (name := s.replace("last ", "")) in _WEEKDAYS:
        wd = _WEEKDAYS.index(name)
        back = (now.weekday() - wd) % 7 or 7
        d = now - timedelta(days=back)
        t0, t1 = day_bounds(d)
        return t0, t1, d.strftime("%A %d %b")
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s):
        try:
            d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
        t0, t1 = day_bounds(d)
        return t0, t1, d.strftime("%a %d %b")
    return None


def _when(ts: float) -> str:
    d = datetime.fromtimestamp(ts)
    if d.date() == datetime.now().date():
        return d.strftime("%H:%M")
    return d.strftime("%a %d %b %H:%M")


def _snip(text: str, n: int = 90) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[: n - 1] + "…"


def session_gist(sess: dict, n_msgs: int = 3) -> str:
    """The stored summary, or (zero-LLM) the first user messages of the session."""
    if (sess.get("summary") or "").strip():
        return _snip(sess["summary"], 220)
    msgs = store.session_messages(sess["id"], role="user", limit=n_msgs)
    if not msgs:
        return ""
    return "you asked: " + "; ".join(_snip(m["text"], 60) for m in msgs)


def keywords(texts: list[str], n: int = 5) -> list[str]:
    """Most frequent content words (zero-LLM topics)."""
    c: Counter[str] = Counter()
    for t in texts:
        words = set(re.findall(r"[a-zA-Zऀ-ॿ][\w'-]{2,}", (t or "").lower()))
        c.update(w for w in words if w not in _STOP and not w.isdigit())
    return [w for w, k in c.most_common(n) if k >= 1]


def topics(t0: float, t1: float, n: int = 5) -> list[str]:
    texts = [s.get("summary") or "" for s in store.sessions_between(t0, t1)]
    texts += [m["text"] for m in store.messages_between(t0, t1, role="user", limit=300)]
    return keywords(texts, n)


def _cap(text: str) -> str:
    limit = config.SESSION_RECALL_MAX_CHARS
    return text if len(text) <= limit else text[: limit - 1] + "…"


def recall(spec: str = "last", exclude_current: bool = True) -> str:
    spec = (spec or "last").strip()
    cur = store.current_session() if exclude_current else None
    low = spec.lower()
    if low in _LAST:
        sess = store.sessions_recent(1, exclude=cur)
        if not sess:
            return "I have no earlier conversations saved yet."
        s = sess[0]
        gist = session_gist(s) or "nothing worth noting"
        return _cap(f"Last time ({_when(s['start'])}, {s['turns']} turns): {gist}.")
    if day := parse_day(spec):
        t0, t1, label = day
        sessions = store.sessions_between(t0, t1)
        if sessions:
            parts = [f"{datetime.fromtimestamp(s['start']).strftime('%H:%M')} {session_gist(s)}" for s in sessions[-4:]]
            n = len(sessions)
            head = f"{label.capitalize()} we had {n} conversation{'s' if n != 1 else ''}"
            return _cap(head + ": " + " | ".join(parts) + ".")
        msgs = store.messages_between(t0, t1, role="user", limit=200)
        if not msgs:
            return f"We didn't talk {label}." if label in ("today", "yesterday") else f"We didn't talk on {label}."
        tops = keywords([m["text"] for m in msgs])
        return _cap(f"{label.capitalize()} you sent {len(msgs)} messages"
                    + (f" about {', '.join(tops)}" if tops else "") + ": "
                    + "; ".join(_snip(m["text"], 60) for m in msgs[-4:]) + ".")
    words = [w for w in re.findall(r"[\wऀ-ॿ]{2,}", low) if w not in _STOP]
    if not words:
        return recall("last", exclude_current)
    q = " OR ".join(f'"{w}"' for w in dict.fromkeys(words))
    hits = store.messages_search(q, limit=6)
    lines = [f"{_when(m['ts'])} {'you' if m['role'] == 'user' else 'me'}: {_snip(m['text'])}" for m in hits]
    for s in store.sessions_recent(30):
        summ = (s.get("summary") or "").lower()
        if summ and any(w in summ for w in words) and len(lines) < 8:
            lines.append(f"{_when(s['start'])} summary: {_snip(s['summary'], 120)}")
    if not lines:
        return f"I couldn't find anything about {spec!r} in our past conversations."
    return _cap("From our past chats: " + " | ".join(lines))
