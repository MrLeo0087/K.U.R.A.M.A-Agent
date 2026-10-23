"""Natural-language times for reminders/scheduled commands, parsed WITHOUT an LLM where possible.

    parse("tomorrow at 9", now)          -> When(ts, "none", ...)
    parse("every weekday at 9:30", now)  -> When(ts, "weekdays", ...)
    parse("bholi 9 baje", now)           -> tomorrow 09:00 (romanized Hindi/Nepali)

parse(text, strict=True) also demands that nothing but filler words is left over (the fast path uses it
to split "call mom at 5 pm" into what + when). resolve() falls back to ONE fast-tier structured call when
the regex parser fails. Repeats: none | daily | weekdays | weekly | hourly | "every N minutes".
All times are local (naive datetimes -> epoch seconds).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

log = logging.getLogger("jarvis.when")

REPEATS = ("none", "daily", "weekdays", "weekly", "hourly")
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_DAY_RX = r"(?P<dow>mon(?:day)?|tue(?:s|sday)?|wed(?:nesday)?|thu(?:rs|rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)"
DEFAULT_HOUR = 9  # a day without a time ("tomorrow") means 9 AM

# Romanized / Devanagari Hindi-Nepali -> English tokens (applied word-wise before parsing).
_HINE = [
    (r"बजे|बज्यो|baje|bajey|bajay|bajje|bajyo", "o'clock"),
    (r"भोलि|कल|bholi|kal", "tomorrow"),
    (r"पर्सि|परसों|parsi|parson|parso", "day after tomorrow"),
    (r"आज|aaja|aaj|aja", "today"),
    (r"बिहान|सुबह|bihana|bihan|subah|subha", "morning"),
    (r"बेलुका|साँझ|शाम|beluka|saanjh|sanjh|shaam|sham", "evening"),
    (r"दिउँसो|दोपहर|diuso|dopahar|dupahar", "afternoon"),
    (r"राति|रात|raati|rati|raat", "night"),
    (r"हरेक दिन|हर दिन|दैनिक|har din|harek din|roj|rojai|pratidin|dainik", "every day"),
    (r"मिनेट|मिनट|minat|minet", "minutes"),
    (r"घण्टा|घंटे|घंटा|ghanta|ghante|ghanta", "hours"),
    (r"पछि|बाद|pachi|pachhi|baad|mein|ma", "later"),
]
_HINE_RX = [(re.compile(rf"(?<![\w'])(?:{a})(?![\w'])", re.I), b) for a, b in _HINE]
_NUM_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "ten": 10,
              "fifteen": 15, "twenty": 20, "thirty": 30, "forty five": 45, "half an": 0.5, "half a": 0.5}
_UNIT_S = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800}

_FILLER = re.compile(r"^(?:\s|,|\b(?:at|on|in|the|of|by|from|starting|and|this|next|o'clock|later|around|"
                     r"about|for|ko|pe|ma|ki|exactly|sharp|every|day|me|to)\b)*$", re.I)


@dataclass
class When:
    ts: float  # first run (epoch seconds)
    repeat: str = "none"
    source: str = "regex"  # regex | llm

    def describe(self, now: datetime | None = None) -> str:
        return describe(self.ts, self.repeat, now)


# --- helpers ---
def _unit(u: str) -> int:
    u = u.lower().rstrip("s")
    u = {"min": "minute", "mins": "minute", "hr": "hour", "sec": "second", "h": "hour", "m": "minute"}.get(u, u)
    return _UNIT_S.get(u, 60)


def _num(s: str) -> float:
    s = s.strip().lower()
    if s in _NUM_WORDS:
        return _NUM_WORDS[s]
    try:
        return float(s)
    except ValueError:
        return 0


def _dow(s: str) -> int:
    s = s.lower()[:3]
    return [d[:3] for d in DAYS].index(s)


def norm_repeat(r: str | None) -> str:
    """Canonical repeat string, or "none" for anything unknown."""
    r = (r or "none").strip().lower()
    if r in REPEATS:
        return r
    m = re.match(r"^every (\d{1,4}) ?(?:minutes?|mins?|m)$", r)
    if m and int(m.group(1)) > 0:
        return f"every {int(m.group(1))} minutes"
    return {"day": "daily", "everyday": "daily", "weekday": "weekdays", "week": "weekly",
            "hour": "hourly"}.get(r, "none")


def repeat_minutes(repeat: str) -> int | None:
    m = re.match(r"^every (\d+) minutes$", repeat or "")
    return int(m.group(1)) if m else None


def next_after(repeat: str, prev_ts: float, now: float) -> float | None:
    """The next occurrence of a repeating item strictly after `now` (stepping from prev_ts), or None."""
    repeat = norm_repeat(repeat)
    if repeat == "none":
        return None
    t = datetime.fromtimestamp(prev_ts)
    mins = repeat_minutes(repeat)
    step = {"hourly": timedelta(hours=1), "daily": timedelta(days=1), "weekly": timedelta(days=7),
            "weekdays": timedelta(days=1)}.get(repeat, timedelta(minutes=mins or 60))
    if repeat in ("hourly",) or mins:  # jump straight past now
        n = max(1, int((now - prev_ts) // step.total_seconds()) + 1)
        t = t + step * n
    else:
        t = t + step
        while t.timestamp() <= now or (repeat == "weekdays" and t.weekday() >= 5):
            t = t + step
    return t.timestamp()


def describe(ts: float, repeat: str = "none", now: datetime | None = None) -> str:
    now = now or datetime.now()
    d = datetime.fromtimestamp(ts)
    hm = d.strftime("%I:%M %p").lstrip("0")
    if repeat == "daily":
        return f"every day at {hm}"
    if repeat == "weekdays":
        return f"every weekday at {hm}"
    if repeat == "weekly":
        return f"every {d.strftime('%A')} at {hm}"
    if repeat == "hourly":
        return f"every hour (next at {hm})"
    if repeat_minutes(repeat):
        return f"{repeat} (next at {hm})"
    days = (d.date() - now.date()).days
    day = {0: "today", 1: "tomorrow"}.get(days) or (d.strftime("%A") if 1 < days < 7 else d.strftime("%a %d %b"))
    return f"{day} at {hm}"


# --- regex parser ---
_REL = re.compile(r"\b(?:in|after)\s+(?P<n>\d+(?:\.\d+)?|an?|one|two|three|four|five|six|ten|fifteen|twenty|"
                  r"thirty|forty five|half an|half a)\s*(?P<u>seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?)\b"
                  r"|\b(?P<n2>\d+(?:\.\d+)?)\s*(?P<u2>minutes?|mins?|hours?|hrs?|days?)\s+later\b", re.I)
_EVERY_N = re.compile(r"\bevery\s+(?P<n>\d{1,4})\s*(?P<u>minutes?|mins?|hours?|hrs?)\b", re.I)
_HOURLY = re.compile(r"\b(?:every\s+hour|hourly)\b", re.I)
_WEEKDAYS = re.compile(r"\b(?:every\s+week\s?days?|on\s+weekdays|weekdays|every\s+working\s+day)\b", re.I)
_DAILY = re.compile(r"\b(?:every\s?day|daily|each\s+day|every\s+(?=morning|evening|night|afternoon))\b", re.I)
_EVERY_DOW = re.compile(r"\b(?:every|each)\s+" + _DAY_RX + r"s?\b", re.I)
_WEEKLY = re.compile(r"\b(?:every\s+week|weekly)\b", re.I)
_DAY_AFTER = re.compile(r"\bday\s+after\s+tomorrow\b", re.I)
_TOMORROW = re.compile(r"\b(?:tomorrow|tmrw|tomorow)\b", re.I)
_TODAY = re.compile(r"\btoday\b", re.I)
_TONIGHT = re.compile(r"\btonight\b", re.I)
_ON_DOW = re.compile(r"\b(?:on\s+|next\s+|this\s+|coming\s+)?" + _DAY_RX + r"\b", re.I)
_PART = re.compile(r"\b(?:in\s+the\s+|at\s+|this\s+)?(?P<p>morning|afternoon|evening|night)\b", re.I)
_NOON = re.compile(r"\b(?:at\s+)?(?P<w>noon|midday|midnight)\b", re.I)
_TIME = re.compile(
    r"\b(?:at\s+|@\s*|by\s+)?(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?\s*(?P<ap>a\.?m\.?|p\.?m\.?)(?![\w])"
    r"|\b(?:at\s+|@\s*|by\s+)?(?P<h2>\d{1,2})[:.](?P<m2>\d{2})\b"
    r"|\b(?:at\s+|@\s*)(?P<h3>\d{1,2})\b(?!\s*(?:minutes?|mins?|hours?|hrs?|days?|%))"
    r"|\b(?P<h4>\d{1,2})(?:[:.](?P<m4>\d{2}))?\s*o'clock\b", re.I)


def _hine(text: str) -> str:
    t = " " + " ".join((text or "").split()) + " "
    for rx, rep in _HINE_RX:
        t = rx.sub(rep, t)
    return t


def parse(text: str, now: datetime | None = None, strict: bool = False) -> When | None:
    """When for text, or None when no time was recognised (or, strict, when non-time words remain)."""
    now = (now or datetime.now()).replace(microsecond=0)
    t = _hine(text).lower()
    used: list[str] = []

    def take(rx: re.Pattern) -> re.Match | None:
        nonlocal t
        m = rx.search(t)
        if m:
            used.append(m.group(0))
            t = t[:m.start()] + " " + t[m.end():]
        return m

    # relative ("in 20 minutes", "20 minute pachi")
    if m := take(_REL):
        n, u = (m.group("n"), m.group("u")) if m.group("n") else (m.group("n2"), m.group("u2"))
        secs = _num(n) * _unit(u)
        if secs <= 0:
            return None
        if strict and not _FILLER.match(t):
            return None
        return When((now + timedelta(seconds=secs)).timestamp(), "none")

    repeat, dow = "none", None
    if m := take(_EVERY_N):
        mins = int(m.group("n")) * (60 if m.group("u").lower().startswith("h") else 1)
        if mins <= 0 or (strict and not _FILLER.match(t)):
            return None
        return When((now + timedelta(minutes=mins)).timestamp(), f"every {mins} minutes")
    if take(_HOURLY):
        if strict and not _FILLER.match(t):
            return None
        return When((now + timedelta(hours=1)).timestamp(), "hourly")
    if take(_WEEKDAYS):
        repeat = "weekdays"
    elif m := take(_EVERY_DOW):
        repeat, dow = "weekly", _dow(m.group("dow"))
    elif take(_WEEKLY):
        repeat = "weekly"
    elif take(_DAILY):
        repeat = "daily"

    day_offset: int | None = None
    if take(_DAY_AFTER):
        day_offset = 2
    elif take(_TOMORROW):
        day_offset = 1
    elif take(_TONIGHT):
        day_offset, used = 0, used + ["night"]
    elif take(_TODAY):
        day_offset = 0
    if dow is None and day_offset is None and (m := take(_ON_DOW)):
        dow = _dow(m.group("dow"))

    hour = minute = None
    ap = None
    if m := take(_NOON):
        hour, minute = (0 if m.group("w").lower() == "midnight" else 12), 0
    elif m := take(_TIME):
        g = m.groupdict()
        h = g["h"] or g["h2"] or g["h3"] or g["h4"]
        mm = g["m"] or g["m2"] or g["m4"] or "0"
        hour, minute = int(h), int(mm)
        if g["ap"]:
            ap = "pm" if g["ap"].lower().startswith("p") else "am"
        if hour > 23 or minute > 59 or (ap and not 1 <= hour <= 12):
            return None
    part = None
    if m := take(_PART):
        part = m.group("p").lower()
    if part is None and any("night" in u for u in used):
        part = "night"

    if hour is None and day_offset is None and dow is None and repeat == "none":
        return None
    if strict and not _FILLER.match(t):
        return None

    explicit = ap is not None or (hour is not None and (hour == 0 or hour > 12)) or part is not None
    if hour is None:
        hour, minute = {"morning": 8, "afternoon": 14, "evening": 18, "night": 21}.get(part or "", DEFAULT_HOUR), 0
    else:
        if ap == "pm" and hour < 12:
            hour += 12
        elif ap == "am" and hour == 12:
            hour = 0
        elif ap is None and part in ("afternoon", "evening", "night") and hour < 12:
            hour = hour + 12 if not (part == "night" and hour < 4) else hour
        elif ap is None and part == "morning" and hour == 12:
            hour = 0
    minute = minute or 0

    def at(d: datetime, h: int) -> datetime:
        return d.replace(hour=h, minute=minute, second=0)

    if day_offset is not None:
        base = now + timedelta(days=day_offset)
        if not explicit and 1 <= hour <= 6 and day_offset > 0:
            hour += 12  # "tomorrow at 5" -> 5 PM
        cand = at(base, hour)
        if day_offset == 0 and cand <= now and not explicit and hour < 12:
            cand = at(base, hour + 12)
        if cand <= now and day_offset == 0:
            return None if strict else When(cand.timestamp() + 86400, repeat)
    elif dow is not None:
        if not explicit and 1 <= hour <= 6:
            hour += 12
        ahead = (dow - now.weekday()) % 7
        cand = at(now + timedelta(days=ahead), hour)
        if cand <= now:
            cand += timedelta(days=7)
    else:  # time only (maybe with a repeat): the next occurrence
        cand = at(now, hour)
        if cand <= now and not explicit and hour < 12 and at(now, hour + 12) > now and repeat == "none":
            cand = at(now, hour + 12)
        if cand <= now:
            cand += timedelta(days=1)
    if repeat == "weekdays":
        while cand.weekday() >= 5:
            cand += timedelta(days=1)
    return When(cand.timestamp(), repeat)


def split(text: str, now: datetime | None = None) -> tuple[str, str, When] | None:
    """Split "call mom at 5 pm" / "at 5 pm to call mom" into (what, when_text, When), or None."""
    t = " ".join((text or "").split()).strip(" ,.")
    m = re.match(r"^(?P<when>.+?)\s+(?:to|that|about)\s+(?P<what>.+)$", t, re.I)
    if m and (w := parse(m.group("when"), now, strict=True)):
        return m.group("what").strip(" ,."), m.group("when"), w
    words = t.split()
    for i in range(1, len(words)):
        tail = " ".join(words[i:])
        if (w := parse(tail, now, strict=True)) is not None:
            what = re.sub(r"\s+(?:at|on|in|by)$", "", " ".join(words[:i]), flags=re.I).strip(" ,.")
            return (what, tail, w) if what else None
    return None


# --- LLM fallback (one fast-tier structured call) ---
def parse_llm(text: str, now: datetime | None = None) -> When | None:
    from pydantic import BaseModel, Field

    from jarvis.core import llm

    class _W(BaseModel):
        """A resolved local date-time and repeat rule."""
        datetime_iso: str = Field(description="first run, local time, YYYY-MM-DDTHH:MM")
        repeat: str = Field(default="none", description="none|daily|weekdays|weekly|hourly|every N minutes")

    now = now or datetime.now()
    msgs = [{"role": "system", "content": "Resolve the time phrase. Now: " + now.strftime("%A %Y-%m-%dT%H:%M")},
            {"role": "user", "content": text[:200]}]
    try:
        out = llm.structured(msgs, _W, tier="fast", purpose="when_parse", max_tokens=80)
        dt = datetime.fromisoformat(out.datetime_iso.strip()[:16])
    except Exception as e:
        log.info("when LLM fallback failed: %s", e)
        return None
    if dt <= now:
        return None
    return When(dt.timestamp(), norm_repeat(out.repeat), "llm")


def resolve(text: str, now: datetime | None = None, use_llm: bool = True) -> When | None:
    return parse(text, now) or (parse_llm(text, now) if use_llm else None)
