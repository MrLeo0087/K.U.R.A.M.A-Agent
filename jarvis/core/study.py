"""Timetable and daily quiz.

Timetable: paste your class schedule once ("Mon 9:00-10:00 DSA Room 201", one class per line; anything else is
turned into that shape by one LLM call, ~1-2k tokens once). Then "what do I have tomorrow", "next class", and a
heads-up TIMETABLE_LEAD_MIN before each class on the desktop and phone (0 tokens).

Quiz: questions are made ONCE from your notes of a subject (~800 tokens per batch) and then asked again and again for
free with spaced repetition (Leitner boxes: a right answer waits longer before it comes back, a wrong one returns
tomorrow). "quiz me" asks; "show the answer" shows it; "I got it" / "I got it wrong" grades it.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta

from jarvis.core import config, notify, store

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_RE = r"(mon|tue|wed|thu|fri|sat|sun)[a-z]*"
LINE = re.compile(rf"^\s*{DAY_RE}\s*[,:\-]?\s*(\d{{1,2}})[:.](\d{{2}})\s*(am|pm)?\s*(?:-|to|–)\s*(\d{{1,2}})[:.](\d{{2}})"
                  rf"\s*(am|pm)?\s*[,:\-]?\s*(.+?)\s*$", re.I)


def _h(h: str, m: str, ampm: str | None) -> str:
    hh = int(h) % 12 + (12 if (ampm or "").lower() == "pm" else 0) if ampm else int(h)
    return f"{hh:02d}:{int(m):02d}"


def parse(text: str) -> list[dict]:
    out = []
    for ln in text.splitlines():
        if m := LINE.match(ln):
            rest = m.group(8)
            room = ""
            if r := re.search(r"\b(?:room|rm|hall|lab)\s*[\w-]+", rest, re.I):
                room, rest = r.group(0), (rest[: r.start()] + rest[r.end():]).strip(" ,-")
            out.append({"day": m.group(1).lower()[:3], "start": _h(m.group(2), m.group(3), m.group(4)),
                        "end": _h(m.group(5), m.group(6), m.group(7) or m.group(4)), "subject": rest.strip(" ,-"),
                        "room": room})
    return out


PROMPT = ("Turn this class timetable into lines of exactly this form, one class per line, nothing else:\n"
          "Mon 09:00-10:00 Subject Room X\nUse 24-hour times and 3-letter English day names.")


def set_timetable(text: str) -> str:
    classes = parse(text)
    if not classes:
        from jarvis.core import llm
        try:
            classes = parse(str(llm.chat([{"role": "system", "content": PROMPT}, {"role": "user", "content": text[:4000]}],
                                         tier="fast", purpose="timetable", max_tokens=1200, temperature=0)))
        except Exception as e:
            return f"error: I couldn't read that timetable ({type(e).__name__})"
    if not classes:
        return "error: I couldn't find any classes. Write one per line, like 'Mon 9:00-10:00 DSA Room 201'."
    store.kv_set("timetable", json.dumps(classes))
    days = sorted({c["day"] for c in classes}, key=DAYS.index)
    return f"Saved {len(classes)} classes ({', '.join(d.title() for d in days)}). I'll remind you " \
           f"{config.TIMETABLE_LEAD_MIN} min before each one."


def classes() -> list[dict]:
    return json.loads(store.kv_get("timetable") or "[]")


def day_list(when: datetime) -> list[dict]:
    d = DAYS[when.weekday()]
    return sorted((c for c in classes() if c["day"] == d), key=lambda c: c["start"])


def fmt(c: dict) -> str:
    return f"{c['start']}-{c['end']} {c['subject']}" + (f" ({c['room']})" if c.get("room") else "")


def show(which: str = "today", now: datetime | None = None) -> str:
    now = now or datetime.now()
    if not classes():
        return "No timetable yet. Paste it to me, one class per line like 'Mon 9:00-10:00 DSA Room 201'."
    if which == "week":
        return "\n".join(f"{d.title()}: " + "; ".join(fmt(c) for c in sorted(
            (c for c in classes() if c["day"] == d), key=lambda c: c["start"])) for d in DAYS
            if any(c["day"] == d for c in classes()))
    if which == "next":
        for k in range(8):
            day = now + timedelta(days=k)
            for c in day_list(day):
                start = datetime.combine(day.date(), datetime.strptime(c["start"], "%H:%M").time())
                if start > now:
                    mins = int((start - now).total_seconds() // 60)
                    when = f"in {mins} min" if mins < 120 else ("today" if k == 0 else day.strftime("%A")) + f" at {c['start']}"
                    return f"Next: {c['subject']} {when}" + (f", {c['room']}" if c.get("room") else "") + "."
        return "No upcoming classes."
    day = now + timedelta(days=1 if which == "tomorrow" else 0)
    todays = day_list(day)
    label = "Tomorrow" if which == "tomorrow" else "Today"
    return f"{label}: " + "; ".join(fmt(c) for c in todays) if todays else f"{label}: no classes."


def check_reminders(now: datetime | None = None) -> list[str]:
    """Scheduler tick: a heads-up TIMETABLE_LEAD_MIN before each class, once."""
    now = now or datetime.now()
    sent = []
    for c in day_list(now):
        start = datetime.combine(now.date(), datetime.strptime(c["start"], "%H:%M").time())
        mins = (start - now).total_seconds() / 60
        key = f"class:{now:%Y%m%d}:{c['start']}:{c['subject']}"
        if 0 < mins <= config.TIMETABLE_LEAD_MIN and not store.kv_get(key):
            store.kv_set(key, "1")
            notify.notify(f"{c['subject']} in {int(mins + 0.5)} min", fmt(c), level="info", source="scheduler")
            sent.append(c["subject"])
    return sent


# ---------------------------------------------------------------- quiz (Leitner boxes)
BOX_DAYS = [0, 1, 3, 7, 16, 35]  # days until a card in box N is asked again
QUIZ_PROMPT = ("From these study notes write {n} short exam-style questions with their answers, testing understanding "
               "(not trivia). Reply ONLY with a JSON list like [{{\"q\": \"...\", \"a\": \"...\"}}].")


def cards() -> list[dict]:
    return json.loads(store.kv_get("quiz_cards") or "[]")


def _save(cs: list[dict]) -> None:
    store.kv_set("quiz_cards", json.dumps(cs))


def make(subject: str, n: int = 6) -> str:
    from jarvis.core import llm, notes

    text = notes.show(subject, 30)
    if text.startswith("No "):
        return f"I need some {subject} notes first (say 'note for {subject}: ...')."
    try:
        reply = str(llm.chat([{"role": "system", "content": QUIZ_PROMPT.format(n=n)}, {"role": "user", "content": text[:6000]}],
                             tier="fast", purpose="quiz_make", max_tokens=1200, temperature=0.3))
        items = json.loads(reply[reply.find("["): reply.rfind("]") + 1])
    except Exception as e:
        return f"error: couldn't make questions right now ({type(e).__name__})"
    cs = cards()
    have = {c["q"].lower() for c in cs}
    new = [{"q": str(i["q"]).strip(), "a": str(i["a"]).strip(), "subject": subject or "General", "box": 0, "due": 0.0}
           for i in items if isinstance(i, dict) and i.get("q") and i.get("a") and str(i["q"]).lower() not in have]
    _save(cs + new)
    return f"Made {len(new)} {subject} questions. Say 'quiz me' whenever you like (they come back by themselves)."


def due(subject: str = "") -> list[dict]:
    now = time.time()
    return [c for c in cards() if c["due"] <= now and (not subject or c["subject"].lower() == subject.lower())]


def ask(subject: str = "") -> str:
    d = due(subject)
    if not d:
        total = len(cards())
        return "Nothing to review right now, nice!" if total else "No questions yet: say 'make a quiz from my DSA notes'."
    c = min(d, key=lambda c: (c["box"], c["due"]))
    store.kv_set("quiz_current", c["q"])
    return f"({c['subject']}, {len(d)} due) {c['q']}"


def answer() -> str:
    q = store.kv_get("quiz_current") or ""
    c = next((c for c in cards() if c["q"] == q), None)
    return f"Answer: {c['a']}\nDid you get it? Say 'I got it' or 'I got it wrong'." if c else "Say 'quiz me' first."


def grade(right: bool) -> str:
    q = store.kv_get("quiz_current") or ""
    cs = cards()
    c = next((c for c in cs if c["q"] == q), None)
    if c is None:
        return "Say 'quiz me' first."
    c["box"] = min(c["box"] + 1, len(BOX_DAYS) - 1) if right else 0
    c["due"] = time.time() + BOX_DAYS[c["box"]] * 86400 + (0 if right else 3600)
    _save(cs)
    store.kv_set("quiz_current", "")
    nxt = ask(c["subject"]) if due(c["subject"]) else "That's all for now."
    return ("Nice! I'll ask that again in " + f"{BOX_DAYS[c['box']]} days. " if right else
            "No problem, it comes back soon. ") + nxt


def stats() -> str:
    cs = cards()
    if not cs:
        return "No quiz questions yet."
    by = {}
    for c in cs:
        s = by.setdefault(c["subject"], [0, 0])
        s[0] += 1
        s[1] += c["box"] >= 3
    return "; ".join(f"{k}: {v[0]} questions, {v[1]} learned" for k, v in by.items()) + f". Due now: {len(due())}."
