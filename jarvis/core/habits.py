"""Daily habits with streaks (0 tokens): 'add a habit: drink water 8 glasses a day, remind me at 10 am',
'I drank 2 glasses of water', 'did exercise', 'my habits', 'delete the water habit'.

Excel ~/Documents/KURAMA/habits.xlsx (editable): Habits (Name, Target, Unit, Remind, Created), Log (Date, Habit, Count).
A day counts when the day's count reaches the target. Streak = days in a row up to today (today still open does not
break it). Reminder at the habit's time if today isn't done yet (05:00-22:00).
"""
from __future__ import annotations

import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from jarvis.core import config, sheets, store

HABIT_HEAD = ["Name", "Target", "Unit", "Remind", "Created"]
LOG_HEAD = ["Date", "Habit", "Count"]
_NUMW = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "a": 1, "an": 1}
UNITS = r"glass(?:es)?|cups?|liters?|litres?|pages?|minutes?|mins?|hours?|times?|km|kilometers?|steps|reps|chapters?|pushups?|push-ups?"
# verb forms people use to report a habit: 'drank water', 'did exercise', 'went for a walk'
_VERB = re.compile(r"\b(?:i\s+)?(?:just\s+|already\s+)?(?:did|done|finished|completed|had|drank|drink|read|went\s+for|"
                   r"took|meditated|walked|ran|studied|practiced|practised|wrote|exercised|slept)\b", re.I)


def _path() -> Path:
    return Path(config.HABITS_FILE).expanduser()


def _book() -> tuple[list[dict], list[dict]]:
    p = _path()
    return sheets.load(p, HABIT_HEAD, "Habits"), sheets.load(p, LOG_HEAD, "Log")


def _save(hs: list[dict], log: list[dict]) -> None:
    sheets.save_book(_path(), [("Habits", HABIT_HEAD, hs, (24, 8, 10, 10, 12)), ("Log", LOG_HEAD, log, (12, 24, 8))])
    store.kv_set("habits_changed", str(time.time()))


def _int(s: str, default: int = 1) -> int:
    try:
        return max(1, int(float(s)))
    except (TypeError, ValueError):
        return default


def names() -> list[str]:
    return [h["name"] for h in _book()[0] if h.get("name")]


def _key(s: str) -> str:
    s = re.sub(r"\b(?:my|the|habit|daily|every\s+day|a\s+day|per\s+day|today)\b", " ", s.lower())
    return " ".join(re.sub(r"[^\w\s]", " ", s).split())


def _stem(w: str) -> str:
    return re.sub(r"(?:ing|ed|es|s)$", "", w) if len(w) > 4 else w


def find(text: str) -> dict | None:
    """The habit a sentence talks about ('drank 2 glasses of water' -> 'drink water')."""
    hs, _ = _book()
    words = {_stem(w) for w in _key(text).split()}
    best, score = None, 0
    for h in hs:
        hw = {_stem(w) for w in _key(h["name"]).split()} - {"drink", "do", "read", "go", "for"}
        hw = hw or {_stem(w) for w in _key(h["name"]).split()}
        s = len(hw & words)
        if s > score:
            best, score = h, s
    return best


def add(name: str, target: int = 1, unit: str = "", remind: str = "") -> str:
    name = " ".join(name.strip(" .,:").split())
    if not name:
        return "What habit? Say for example 'add a habit: drink water 8 glasses a day'."
    hs, log = _book()
    hs = [h for h in hs if _key(h["name"]) != _key(name)]
    hs.append({"name": name, "target": str(target), "unit": unit, "remind": remind,
               "created": date.today().isoformat()})
    _save(hs, log)
    goal = f"{target} {unit} a day".strip() if target > 1 or unit else "every day"
    return f"New habit: {name} ({goal})" + (f", reminder at {remind}" if remind else "") + \
           f". When you do it, tell me (for example '{name} done')."


def parse_new(text: str) -> tuple[str, int, str, str]:
    """'drink water 8 glasses a day remind me at 10 am' -> ('drink water', 8, 'glasses', '10:00')."""
    t = text
    remind = ""
    if m := re.search(r",?\s*(?:and\s+)?remind\s+me(?:\s+(?:at|every\s+day\s+at|daily\s+at))?\s+(\d{1,2})(?::(\d\d))?\s*(am|pm)?\b.*$", t, re.I):
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
        h = h % 12 + (12 if ap == "pm" else 0) if ap else h
        remind = f"{h:02d}:{mi:02d}"
        t = t[:m.start()]
    target, unit = 1, ""
    if m := re.search(rf"\b(\d+|{'|'.join(_NUMW)})\s+({UNITS})\b", t, re.I):
        target = int(m.group(1)) if m.group(1).isdigit() else _NUMW[m.group(1).lower()]
        unit = m.group(2).lower()
        t = t[:m.start()] + t[m.end():]
    t = re.sub(r"\b(?:a|per|every|each)\s+day\b|\bdaily\b|\beveryday\b|\bof\b\s*$", " ", t, flags=re.I)
    return " ".join(t.split()).strip(" ,.:-"), target, unit, remind


def check_in(text: str, now: datetime | None = None) -> str | None:
    """'I drank 2 glasses of water' -> +2 on the water habit; None when no habit matches."""
    h = find(text)
    if h is None:
        return None
    now = now or datetime.now()
    n = 1
    if m := re.search(rf"\b(\d+|{'|'.join(k for k in _NUMW if k not in ('a', 'an'))})\s*(?:{UNITS}|more)?\b", text, re.I):
        n = int(m.group(1)) if m.group(1).isdigit() else _NUMW[m.group(1).lower()]
    hs, log = _book()
    today = now.date().isoformat()
    log.append({"date": today, "habit": h["name"], "count": str(n)})
    _save(hs, log)
    target = _int(h.get("target"))
    done = _counts(log)[(today, h["name"])]
    st = streak(h["name"], log, now.date())
    if done >= target:
        return f"✅ {h['name']} done for today" + (f" ({done}/{target} {h.get('unit') or ''})".rstrip() if target > 1 else "") \
               + f". Streak: {st} day{'s' if st != 1 else ''} 🔥"
    return f"{h['name']}: {done}/{target} {h.get('unit') or ''} today, {target - done} to go.".replace("  ", " ")


def _counts(log: list[dict]) -> dict[tuple[str, str], int]:
    c: dict[tuple[str, str], int] = defaultdict(int)
    for r in log:
        c[(r.get("date", "")[:10], r.get("habit", ""))] += _int(r.get("count"))
    return c


def _done_days(name: str, log: list[dict], target: int) -> set[date]:
    out = set()
    for (d, hname), n in _counts(log).items():
        if hname == name and n >= target:
            try:
                out.add(date.fromisoformat(d))
            except ValueError:
                pass
    return out


def streak(name: str, log: list[dict] | None = None, today: date | None = None) -> int:
    hs, lg = _book() if log is None else ([], log)
    today = today or date.today()
    h = next((x for x in (hs or _book()[0]) if x["name"] == name), {"target": "1"})
    days = _done_days(name, lg, _int(h.get("target")))
    d = today if today in days else today - timedelta(days=1)  # today not done yet doesn't break it
    n = 0
    while d in days:
        n += 1
        d -= timedelta(days=1)
    return n


def best_streak(days: set[date]) -> int:
    best = run = 0
    prev = None
    for d in sorted(days):
        run = run + 1 if prev and d - prev == timedelta(days=1) else 1
        best, prev = max(best, run), d
    return best


def overview(now: datetime | None = None) -> list[dict]:
    """Per habit: today count/target, streak, best, last 7 days done flags (oldest first)."""
    today = (now or datetime.now()).date()
    hs, log = _book()
    counts = _counts(log)
    out = []
    for h in hs:
        target = _int(h.get("target"))
        days = _done_days(h["name"], log, target)
        out.append({"name": h["name"], "target": target, "unit": h.get("unit") or "", "remind": h.get("remind") or "",
                    "today": counts[(today.isoformat(), h["name"])], "done": today in days,
                    "streak": streak(h["name"], log, today), "best": best_streak(days),
                    "week": [today - timedelta(days=i) in days for i in range(6, -1, -1)]})
    return out


def status_text(now: datetime | None = None) -> str:
    ov = overview(now)
    if not ov:
        return "No habits yet. Say for example 'add a habit: drink water 8 glasses a day, remind me at 10 am'."
    lines = []
    for h in ov:
        week = "".join("●" if d else "○" for d in h["week"])
        prog = f"{h['today']}/{h['target']}" if h["target"] > 1 else ("done" if h["done"] else "not yet")
        lines.append(f"{'✅' if h['done'] else '⬜'} {h['name']}: {prog} today · 🔥 {h['streak']} (best {h['best']}) {week}")
    left = [h["name"] for h in ov if not h["done"]]
    return "Your habits:\n" + "\n".join(lines) + (f"\nStill to do today: {', '.join(left)}." if left else "\nAll done today! 🎉")


def delete(text: str) -> str:
    h = find(text)
    if h is None:
        return "Which habit? " + (", ".join(names()) or "You have no habits yet.")
    hs, log = _book()
    _save([x for x in hs if x["name"] != h["name"]], log)  # its log stays in the sheet
    return f"Stopped tracking {h['name']} (its history stays in habits.xlsx)."


def undo(text: str, now: datetime | None = None) -> str:
    """'I didn't do exercise' / 'undo water' -> remove today's last check-in."""
    h = find(text)
    if h is None:
        return "Which habit should I undo?"
    hs, log = _book()
    today = (now or datetime.now()).date().isoformat()
    for i in range(len(log) - 1, -1, -1):
        if log[i].get("habit") == h["name"] and log[i].get("date", "")[:10] == today:
            log.pop(i)
            _save(hs, log)
            return f"Removed today's last {h['name']} check-in."
    return f"No {h['name']} check-in today to remove."


def remind_due(now: datetime | None = None) -> int:
    """Scheduler tick: a habit's reminder time has passed today and it isn't done -> one nudge (05:00-22:00)."""
    from jarvis.core import notify
    now = now or datetime.now()
    if not 5 <= now.hour < 22:
        return 0
    sent = 0
    for h in overview(now):
        if not h["remind"] or h["done"] or now.strftime("%H:%M") < h["remind"]:
            continue
        key = f"habit_reminded:{h['name']}"
        if store.kv_get(key) == now.date().isoformat():
            continue
        store.kv_set(key, now.date().isoformat())
        st = f" Keep your {h['streak']}-day streak!" if h["streak"] else ""
        notify.notify("⏰ Habit", f"Time for {h['name']}" + (f" ({h['today']}/{h['target']} {h['unit']})" if h["target"] > 1 else "")
                      + f".{st} Say '{h['name']} done' when you've done it.", source="habits")
        sent += 1
    return sent
