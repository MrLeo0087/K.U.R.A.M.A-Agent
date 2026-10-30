"""Morning brief (0 tokens): the first time I use the laptop each day (unlock, wake from sleep, or KURAMA's first
screen of the day) KURAMA says what matters today, in a few short spoken lines:
weather, today's to-dos/reminders, long-task countdowns, habits left, money (yesterday + month vs budget), bills due.

Delivered once per day after BRIEF_FROM_HOUR: spoken by the dashboard (GET /api/v1/brief, polled), and as a desktop
+ Telegram notification. 'morning brief' / '/brief' gives it again any time.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

from jarvis.core import config, store

log = logging.getLogger(__name__)
DONE_KEY = "brief_date"  # the day the brief was given
PENDING_KEY = "brief_pending"  # text waiting for the dashboard to speak it


def _safe(fn, default=""):
    try:
        return fn()
    except Exception as e:  # one broken part never kills the brief
        log.info("brief part skipped: %s", e)
        return default


def _hello(now: datetime) -> str:
    name = _safe(lambda: __import__("jarvis.core.profile", fromlist=["x"]).user_name(), "")
    import random
    part = random.choice(("Good morning", "Morning", "Rise and shine")) if 4 <= now.hour < 12 else \
        random.choice(("Good afternoon", "Hello")) if now.hour < 17 else random.choice(("Good evening", "Hello"))
    day = _safe(lambda: __import__("jarvis.core.nepdate", fromlist=["x"]).bs_phrase(now.date()), "") or \
        now.strftime("%A, %d %B")
    return f"{part}{' ' + name if name else ''}! Today is {day}."


def _weather() -> str:
    from jarvis.core import greeting
    return greeting.weather_line()


def _todo(now: datetime) -> str:
    """'You have 4 to-dos, 2 due today (1 overdue). First: Finish the report. 2 reminders today, first at 5 PM.'"""
    from jarvis.core import store, todos
    rows, c = todos.items(), todos.summary_counts()
    end = now.replace(hour=23, minute=59, second=59).timestamp()
    rem = sorted((s for s in store.schedules_list(enabled_only=True, limit=50)
                  if s.get("kind") in ("reminder", "alarm") and s.get("next_run") and s["next_run"] <= end),
                 key=lambda s: s["next_run"])
    out = []
    if rows:
        n = len(rows)
        out.append(f"You have {n} to-do{'s' if n != 1 else ''}" + (f", {c['today']} due today" if c["today"] else "")
                   + (f" ({c['overdue']} overdue)" if c["overdue"] else "") + f". First: {rows[0]['title']}.")
    if rem:
        at = datetime.fromtimestamp(rem[0]["next_run"]).strftime("%I:%M %p").lstrip("0")
        out.append(f"{len(rem)} reminder{'s' if len(rem) != 1 else ''} today, first at {at}: {rem[0]['text'][:60]}.")
    return " ".join(out)


def _goals(now: datetime) -> str:
    from jarvis.core import goals
    out = []
    for g in goals.all_goals():
        if g.get("status") != "active":
            continue
        end = goals._d(g.get("end", ""))
        if end:
            left = (end - now.date()).days
            if left >= 0:
                out.append(f"{g['name']} in {left} day{'s' if left != 1 else ''}" if left else f"{g['name']} is today")
    return ("Long tasks: " + ", ".join(out[:3]) + ".") if out else ""


def _habits(now: datetime) -> str:
    from jarvis.core import habits
    ov = habits.overview(now)
    if not ov:
        return ""
    left = [h["name"] for h in ov if not h["done"]]
    best = max(ov, key=lambda h: h["streak"])
    line = f"Habits today: {', '.join(left[:4])}." if left else "All habits done already!"
    if best["streak"] >= 2:
        line += f" {best['name']} streak: {best['streak']} days."
    return line


def _money(now: datetime) -> str:
    from jarvis.core import expenses as ex
    d = ex.dashboard(now)
    m, _b, _ = ex._book()
    if not m:
        return ""
    y = ex._sum(m, "yesterday", now.date())
    parts = []
    if y:
        parts.append(f"Yesterday you spent {ex.money(y)}")
    month = f"this month {ex.money(d['month'])}" + (f" of {ex.money(d['budget'])}" if d.get("budget") else "")
    parts.append(month)
    line = ", ".join(parts) + "."
    if d.get("bills_due"):
        line += f" Bill due: {', '.join(d['bills_due'])}."
    return line[0].upper() + line[1:]


def build(now: datetime | None = None) -> str:
    now = now or datetime.now()
    parts = [_hello(now)] + [_safe(lambda f=f: f(now) if f is not _weather else f())
                             for f in (_weather, _todo, _goals, _habits, _money)]
    return " ".join(p for p in parts if p)


def due(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    return now.hour >= config.BRIEF_FROM_HOUR and store.kv_get(DONE_KEY) != now.date().isoformat()


def deliver(reason: str, now: datetime | None = None) -> str | None:
    """Give today's brief once: queue it for the dashboard to speak + notify laptop and phone. None = already given."""
    now = now or datetime.now()
    if not config.BRIEF or not due(now):
        return None
    store.kv_set(DONE_KEY, now.date().isoformat())
    text = build(now)
    store.kv_set(PENDING_KEY, text)
    store.kv_set("brief_at", str(time.time()))
    log.info("morning brief (%s)", reason)
    try:
        from jarvis.core import notify
        notify.notify("☀️ Morning brief", text, source="brief")
    except Exception as e:
        log.info("brief notify failed: %s", e)
    return text


def take_pending(max_age_s: float = 3 * 3600) -> str:
    """For the dashboard: the queued brief (once), if it's fresh."""
    text = store.kv_get(PENDING_KEY) or ""
    if not text:
        return ""
    store.kv_set(PENDING_KEY, "")
    try:
        if time.time() - float(store.kv_get("brief_at") or 0) > max_age_s:
            return ""
    except ValueError:
        return ""
    return text


class Watch:
    """Unlock / wake detection for the worker: locked -> unlocked, or a clock jump (the laptop slept)."""

    def __init__(self) -> None:
        self.locked: bool | None = None
        self.last = time.time()

    def tick(self, locked: bool | None, now: float | None = None) -> str | None:
        now = now or time.time()
        woke = now - self.last > max(90.0, config.BRIEF_INTERVAL_S * 6)  # the tick was frozen: suspend/resume
        self.last = now
        was, self.locked = self.locked, locked if locked is not None else self.locked
        if was is True and locked is False:
            return "unlock"
        if was is None and locked is False:  # the first look after KURAMA started (a fresh boot / login): unlocked
            return "start"
        if woke and locked is not True:
            return "wake"
        return None
