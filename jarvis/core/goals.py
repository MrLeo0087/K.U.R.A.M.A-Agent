"""Goals = long tasks that last weeks or months (my list is for short to-dos).

A goal has a name, a start and an end date, and up to three rules:
  remind  countdown / progress messages at set times ('Exam: 29 days left (Tue, Nov 25).')
  ask     a daily check-in question ('What did you do on Thesis today?'); the answer goes into the log
  write   project goals keep a folder (~/Documents/KURAMA/goals/<name>/): log.md, daily/<date>.md, weekly/<week>.md,
          and report.md + report.pdf on request (the only part that uses the AI)

Everything lives in ONE Excel file (config.GOALS_FILE): tab 'Goals' (one row per goal, editable by hand) and tab
'Log' (one row per answer). Messages go out only between config.GOAL_HOURS (05:00-22:00), desktop + Telegram,
source 'goals'. The scheduler worker calls tick() every 15 s; everything except the report costs 0 tokens.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from jarvis.core import config, sheets, store

log = logging.getLogger("jarvis.goals")

HEAD = ["ID", "Name", "Kind", "Start", "End", "Remind", "Ask", "Ask at", "Weekly", "Folder", "Repo", "Status", "Note"]
WIDTHS = (5, 26, 10, 12, 12, 22, 44, 8, 8, 50, 40, 9, 30)
LOG_HEAD = ["Date", "Time", "Goal", "Entry", "From"]
LOG_WIDTHS = (12, 7, 26, 90, 10)
SOURCE = "goals"
FIRED_KEY = "goals_fired"      # {"date": "2026-10-26", "done": ["3:r:07:00", "3:a", ...]}
WAIT_KEY = "goals_waiting"     # {"id": 3, "ts": ...}: the last check-in question, waiting for an answer
DAY_KEY = "goals_day"          # the last day closed (skipped check-ins written)
CHECKIN = "Check-in: "         # title of a check-in message (a Telegram reply to it = the answer)
PROJECT_WORDS = r"project|thesis|course|semester|hackathon|startup|research|internship|dissertation|app|website"
DEFAULT_TIMES = {1: ["08:00"], 2: ["08:00", "20:00"], 3: ["07:00", "13:00", "20:00"], 4: ["07:00", "11:00", "15:00", "20:00"]}


# --- storage -------------------------------------------------------------------------------------------------------
def path() -> Path:
    return Path(config.GOALS_FILE).expanduser()


_cache: dict = {}  # (mtime, size) -> rows: the scheduler looks every 15 s, the file rarely changes


def _load() -> tuple[list[dict], list[dict]]:
    p = path()
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    if key is None or _cache.get("key") != key:
        _cache.update(key=key, goals=sheets.load(p, HEAD, "Goals"), logs=sheets.load(p, LOG_HEAD, "Log"))
    return [dict(x) for x in _cache["goals"]], [dict(x) for x in _cache["logs"]]


def _save(goals: list[dict], logs: list[dict]) -> None:
    sheets.save_book(path(), [("Goals", HEAD, goals, WIDTHS), ("Log", LOG_HEAD, logs, LOG_WIDTHS)])


def all_goals(status: str = "") -> list[dict]:
    if not path().exists():
        return []
    with sheets.locked(path()):
        g, _ = _load()
    return [x for x in g if not status or x["status"] == status]


def _logs() -> list[dict]:
    if not path().exists():
        return []
    with sheets.locked(path()):
        return _load()[1]


def _d(s: str) -> date | None:
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def _nice(d: date | None) -> str:
    return d.strftime("%a, %b %-d") + (f" {d.year}" if d.year != date.today().year else "") if d else "no end date"


def _slug(name: str) -> str:
    return re.sub(r"[^\w-]+", "-", name.strip().lower()).strip("-")[:40] or "goal"


def _hours_ok(t: datetime) -> bool:
    a, b = config.GOAL_HOURS
    return a <= t.hour < b


def _clamp(hm: str) -> str:
    """A message time inside the working hours (05:00-22:00)."""
    h, m = (int(x) for x in hm.split(":"))
    a, b = config.GOAL_HOURS
    if h < a:
        return f"{a:02d}:00"
    if h >= b:
        return f"{b - 1:02d}:30"
    return f"{h:02d}:{m:02d}"


# --- understanding loose words (0 tokens) ----------------------------------------------------------------------------
def times_in(text: str) -> list[str]:
    """'at 6 am and 9 pm' -> ['06:00', '21:00']; 'twice a day' -> ['08:00', '20:00']; [] = no times said."""
    from jarvis.core import when
    out = []
    for m in when._TIME.finditer(text or ""):
        h = m.group("h") or m.group("h2") or m.group("h3") or m.group("h4")
        mi = m.group("m") or m.group("m2") or m.group("m4") or "0"
        h, mi = int(h), int(mi)
        ap = (m.group("ap") or "").lower().replace(".", "")
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        if not m.group("ap") and m.group("h3") and h < 5:  # 'at 2' in a goal = 2 PM
            h += 12
        if 0 <= h < 24 and 0 <= mi < 60:
            out.append(_clamp(f"{h:02d}:{mi:02d}"))
    if out:
        return sorted(set(out))
    low = (text or "").lower()
    n = 0
    if re.search(r"\bonce\b|\bone\s+time\b|\b1\s+time\b", low):
        n = 1
    elif re.search(r"\btwice\b|\b(?:two|2)\s+times\b", low):
        n = 2
    elif re.search(r"\b(?:two|2)\s*(?:-|or|to)\s*(?:three|3)\s+times?\b|\b(?:three|3|thrice)\s+times\b|\bthrice\b", low):
        n = 3
    elif re.search(r"\b(?:four|4)\s+times\b", low):
        n = 4
    return DEFAULT_TIMES.get(n, [])


def end_in(text: str, today: date | None = None) -> date | None:
    """The end date said in text: 'in 30 days', 'for 6 months', '30 days later', 'on November 28', 'by Dec 5 2027'."""
    from jarvis.core import when
    today = today or date.today()
    low = (text or "").lower()
    nums = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
            "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "sixty": 60,
            "ninety": 90, "hundred": 100}
    if m := when._DATE.search(low):  # a calendar date wins ('on November 28, remind me twice a day')
        w = when.parse(m.group(0), now=datetime.combine(today, datetime.min.time()).replace(hour=12))
        if w:
            return datetime.fromtimestamp(w.ts).date()
    words = "|".join(nums)
    # 'in 30 days', 'for six months', 'takes 6 months', '30 days later', 'a 6-month project'; never 'twice a day'
    m = re.search(r"\b(?:in|after|within|for|next|takes?|lasts?|about|around)\s+(?:the\s+)?(?:next\s+)?(?P<n>\d{1,3}|" + words
                  + r")[\s-]*(?P<u>days?|weeks?|months?|years?)\b|\b(?P<n2>\d{1,3}|" + words + r")[\s-]*(?P<u2>days?|weeks?|months?|"
                  r"years?)\s+(?:later|from\s+now|left|away|long)\b|\b(?P<n3>\d{1,3})[\s-]*(?P<u3>days?|weeks?|months?|years?)\b", low)
    if m:
        n, u = next((m.group(a), m.group(b)) for a, b in (("n", "u"), ("n2", "u2"), ("n3", "u3")) if m.group(a))
        n = int(n) if n.isdigit() else nums[n]
        u = u[0]
        if u == "d":
            return today + timedelta(days=n)
        if u == "w":
            return today + timedelta(weeks=n)
        import calendar
        y, mo = divmod(today.month - 1 + n * (12 if u == "y" else 1), 12)
        yy, mm = today.year + y, mo + 1
        return date(yy, mm, min(today.day, calendar.monthrange(yy, mm)[1]))
    if re.search(r"\bnext\s+month\b", low):
        return end_in("in 1 month", today)
    if re.search(r"\bnext\s+year\b", low):
        return end_in("in 1 year", today)
    return None


def find(name: str, goals: list[dict] | None = None) -> dict | None:
    """The goal a loose name (or its ID) means: exact, then contains, then words; '' / 'the project' = the newest
    fitting one. Pass goals when the sheet is already locked (a second lock in the same process would wait forever)."""
    gs = [g for g in (all_goals() if goals is None else goals) if g["status"] != "done"]
    if not gs:
        return None
    if (name or "").strip().isdigit():
        return next((g for g in gs if g["id"] == name.strip()), None)
    n = re.sub(r"\b(?:my|the|this|that|our|goal|long\s+task|countdown)\b", " ", (name or "").lower())
    n = " ".join(n.split())
    for g in gs:
        if g["name"].lower() == n:
            return g
    if n:
        for g in gs:
            if n in g["name"].lower() or g["name"].lower() in n:
                return g
        words = set(re.findall(r"\w{3,}", n))
        best = max(gs, key=lambda g: len(words & set(re.findall(r"\w{3,}", g["name"].lower()))))
        if words & set(re.findall(r"\w{3,}", best["name"].lower())):
            return best
        if re.fullmatch(PROJECT_WORDS, n) or n in ("exam", "test"):
            same = [g for g in gs if (g["kind"] == "project") == bool(re.fullmatch(PROJECT_WORDS, n))]
            return same[-1] if same else None
        return None
    return gs[-1]


# --- add / change ----------------------------------------------------------------------------------------------------
def add(name: str, end: str = "", remind: str = "", ask: str = "", ask_at: str = "", kind: str = "",
        weekly: bool | None = None, repo: str = "", today: date | None = None) -> str:
    """A new goal. end: a date or words ('in 30 days', 'November 28'). remind: times / 'twice a day' / 'off'.
    ask: the daily question ('' = none; 'yes' = the default one). kind: countdown | project ('' = guess)."""
    today = today or date.today()
    name = " ".join((name or "").split()).strip(" .,:")[:60]
    if not name:
        return "What should I call this goal? For example: 'my physics exam is in 30 days'."
    name = name[0].upper() + name[1:]
    end_d = _d(end) or end_in(end, today) if end else None
    if end and not end_d:
        return f"I couldn't understand the end date '{end}'. Say it like 'in 30 days' or 'on November 28'."
    if end_d and end_d < today:
        return f"{_nice(end_d)} has already passed. Give me a date after today."
    kind = kind or ("project" if re.search(rf"\b(?:{PROJECT_WORDS})\b", name, re.I) or ask else "countdown")
    if ask in ("yes", "default", "daily"):
        ask = ""
        ask_default = True
    else:
        ask_default = False
    question = ask.strip() or (f"What did you do on {name} today?" if ask_default or kind == "project" else "")
    if remind.strip().lower() in ("off", "no", "none", "never"):
        times = []
    else:
        times = times_in(remind) or (DEFAULT_TIMES[3] if kind == "countdown" else DEFAULT_TIMES[1])
    at = (times_in(ask_at) or ["21:00"])[0] if question else ""
    with sheets.locked(path()):
        goals, logs = _load()
        same = next((g for g in goals if g["name"].lower() == name.lower() and g["status"] != "done"), None)
        if same:
            if end_d:
                same["end"] = end_d.isoformat()
            _save(goals, logs)
            return f"You already have '{same['name']}'. " + (f"I moved its end to {_nice(end_d)}." if end_d else
                                                             "Say what to change, e.g. 'move it to December 2'.")
        gid = max([int(g["id"]) for g in goals if g["id"].isdigit()] + [0]) + 1
        g = {"id": str(gid), "name": name, "kind": kind, "start": today.isoformat(),
             "end": end_d.isoformat() if end_d else "", "remind": ", ".join(times), "ask": question, "ask at": at,
             "weekly": "yes" if (weekly if weekly is not None else kind == "project") else "no", "folder": "",
             "repo": repo, "status": "active", "note": ""}
        if kind == "project":
            g["folder"] = str(_folder(g))
        goals.append(g)
        _save(goals, logs)
    touch(g["id"])
    return _added_text(g, today)


def _folder(g: dict) -> Path:
    f = Path(g.get("folder") or Path(config.GOALS_DIR).expanduser() / _slug(g["name"]))
    for sub in ("daily", "weekly"):
        (f / sub).mkdir(parents=True, exist_ok=True)
    lf = f / "log.md"
    if not lf.exists():
        lf.write_text(f"# {g['name']}: log\n\nStarted {g['start']}" + (f", ends {g['end']}" if g['end'] else "") + ".\n",
                      encoding="utf-8")
    return f


def _added_text(g: dict, today: date) -> str:
    end = _d(g["end"])
    parts = [f"Added the goal '{g['name']}'" + (f", ends {_nice(end)} ({(end - today).days} days)" if end else "") + "."]
    if g["remind"]:
        parts.append(f"I'll remind you at {_times_words(g['remind'])} every day.")
    if g["ask"]:
        parts.append(f"I'll ask you at {_times_words(g['ask at'])}: '{g['ask']}'")
    if g["folder"]:
        parts.append("Its folder: " + g["folder"].replace(str(Path.home()), "~") + ".")
    return " ".join(parts)


def _times_words(times: str) -> str:
    out = []
    for hm in [x.strip() for x in times.split(",") if x.strip()]:
        h, m = (int(x) for x in hm.split(":"))
        out.append(datetime(2000, 1, 1, h, m).strftime("%-I:%M %p").replace(":00 ", " "))
    return ", ".join(out[:-1]) + (" and " if len(out) > 1 else "") + out[-1] if out else "no time"


def edit(goal: str, name: str = "", end: str = "", remind: str = "", ask: str = "", ask_at: str = "",
         status: str = "", repo: str = "", today: date | None = None) -> str:
    """Change one goal. Empty = keep. remind/ask 'off' stops that rule. status: active|paused|done|delete."""
    today = today or date.today()
    with sheets.locked(path()):
        goals, logs = _load()
        target = _match(goals, goal)
        if not target:
            return _not_found(goal, goals)
        g, said = target, []
        if name.strip():
            g["name"] = name.strip()[:60]
            said.append(f"renamed to '{g['name']}'")
        if end.strip():
            d = _d(end) or end_in(end, today)
            if not d:
                return f"I couldn't understand the date '{end}'."
            g["end"] = d.isoformat()
            said.append(f"ends {_nice(d)}")
        if remind.strip():
            if re.fullmatch(r"\s*(?:off|stop|no|none|never)\s*", remind, re.I):
                g["remind"] = ""
                said.append("no more reminders")
            elif t := times_in(remind):
                g["remind"] = ", ".join(t)
                said.append(f"reminders at {_times_words(g['remind'])}")
        if ask.strip():
            if re.fullmatch(r"\s*(?:off|stop|no|none|never)\s*", ask, re.I):
                g["ask"], g["ask at"] = "", ""
                said.append("I won't ask about it any more")
            else:
                g["ask"] = f"What did you do on {g['name']} today?" if ask.strip().lower() in ("yes", "daily") else ask.strip()
                g["ask at"] = g["ask at"] or "21:00"
                said.append(f"I'll ask '{g['ask']}'")
        if ask_at.strip() and (t := times_in(ask_at)):
            g["ask at"] = t[0]
            g["ask"] = g["ask"] or f"What did you do on {g['name']} today?"
            said.append(f"check-in at {_times_words(t[0])}")
        if repo.strip():
            g["repo"] = repo.strip()
            said.append(f"linked to the git repo {Path(repo).name}")
        if status.strip():
            st = status.strip().lower()
            if st in ("delete", "remove"):
                goals.remove(g)
                _save(goals, logs)
                return f"Deleted the goal '{g['name']}' (its log and folder are kept)."
            if st in ("active", "paused", "done"):
                g["status"] = st
                said.append({"active": "running again", "paused": "paused (no messages)", "done": "marked done, messages stopped"}[st])
        if not said:
            return f"What should I change about '{g['name']}'? (date, reminder times, check-in question, pause, done)"
        _save(goals, logs)
    touch(g["id"])
    return f"{g['name']}: " + ", ".join(said) + "."


LAST_KEY = "goals_last"  # the goal the user just added/changed: 'no, it's actually 30 days' corrects it


def touch(gid: str) -> None:
    store.kv_set(LAST_KEY, json.dumps({"id": str(gid), "ts": time.time()}))


def last_touched(within_s: float = 900.0) -> dict | None:
    try:
        d = json.loads(store.kv_get(LAST_KEY) or "{}")
    except ValueError:
        return None
    if not d or time.time() - float(d.get("ts", 0)) > within_s:
        return None
    return find(str(d.get("id", "")))


def named_in(text: str) -> dict | None:
    """The goal whose name (or a main word of it, 4+ letters) appears in free text; the longest match wins."""
    low = (text or "").lower()
    best, score = None, 0
    for g in all_goals():
        if g["status"] == "done":
            continue
        n = g["name"].lower()
        s = len(n) + 100 if re.search(rf"\b{re.escape(n)}\b", low) else max(
            [len(w) for w in re.findall(r"\w{4,}", n) if re.search(rf"\b{re.escape(w)}s?\b", low)] + [0])
        if s > score:
            best, score = g, s
    return best


def _match(goals: list[dict], goal: str) -> dict | None:
    return find(goal, goals)


def _not_found(goal: str, goals: list[dict]) -> str:
    live = [g["name"] for g in goals if g["status"] != "done"]
    if not live:
        return "You don't have any goals yet. Say e.g. 'my exam is in 30 days, remind me every day'."
    return f"I couldn't find a goal called '{goal}'. Your goals: " + ", ".join(live) + "."


# --- the log ---------------------------------------------------------------------------------------------------------
def log_entry(goal: str, text: str, source: str = "chat", now: datetime | None = None) -> str:
    """Save one progress answer ('today I finished the login page')."""
    now = now or datetime.now()
    text = " ".join((text or "").split()).strip()
    if not text:
        return "What should I write in the log?"
    with sheets.locked(path()):
        goals, logs = _load()
        g = _match(goals, goal)
        if not g:
            return _not_found(goal, goals)
        logs.append({"date": now.date().isoformat(), "time": now.strftime("%H:%M"), "goal": g["name"], "entry": text[:2000],
                     "from": source})
        _save(goals, logs)
    _clear_wait(g["id"])
    if g["folder"]:
        _write_md(g, now.date(), logs)
    n = len([x for x in logs if x["goal"] == g["name"] and x["date"] == now.date().isoformat()])
    return f"Saved to {g['name']}'s log" + (f" ({n} notes today)." if n > 1 else ".")


def _write_md(g: dict, day: date, logs: list[dict]) -> None:
    """log.md (everything) + daily/<day>.md (that day, with the day's commits)."""
    try:
        f = _folder(g)
        mine = [x for x in logs if x["goal"] == g["name"]]
        lines = [f"# {g['name']}: log", ""]
        for d in sorted({x["date"] for x in mine}):
            lines.append(f"## {d}")
            lines += [f"- {x['time']} {x['entry']}" for x in mine if x["date"] == d]
            lines.append("")
        (f / "log.md").write_text("\n".join(lines), encoding="utf-8")
        (f / "daily" / f"{day.isoformat()}.md").write_text(day_text(g, day, logs, md=True), encoding="utf-8")
    except OSError as e:
        log.warning("goal folder write failed: %s", e)


def commits(repo: str, since: date, until: date | None = None, limit: int = 30) -> list[str]:
    """'abc123 subject' lines from the goal's git repo between two days ([] when no repo / not git)."""
    p = Path(repo or "").expanduser()
    if not repo or not (p / ".git").exists():
        return []
    argv = ["git", "-C", str(p), "log", f"--since={since.isoformat()} 00:00", "--format=%h %s", f"-{limit}"]
    if until:
        argv.insert(-2, f"--until={until.isoformat()} 23:59")
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=10).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return []


def day_text(g: dict, day: date | None = None, logs: list[dict] | None = None, md: bool = False) -> str:
    """What happened on this goal on one day: the saved answers + the day's commits (0 tokens)."""
    day = day or date.today()
    logs = _logs() if logs is None else logs
    mine = [x for x in logs if x["goal"] == g["name"] and x["date"] == day.isoformat()]
    cm = commits(g["repo"], day, day)
    when_w = "today" if day == date.today() else day.strftime("%a %b %-d")
    if md:
        out = [f"# {g['name']}: {day.isoformat()}", ""] + [f"- {x['time']} {x['entry']}" for x in mine]
        if cm:
            out += ["", "## Commits"] + [f"- {c}" for c in cm]
        return "\n".join(out) + "\n"
    if not mine and not cm:
        return f"Nothing saved for {g['name']} {when_w} yet. Tell me '{g['name']} update: what you did'."
    out = [f"{g['name']} {when_w}{' so far' if day == date.today() else ''}:"]
    out += [f"• {x['entry']}" for x in mine]
    if cm:
        out.append(f"• {len(cm)} commit{'s' if len(cm) > 1 else ''}: " + "; ".join(c.split(" ", 1)[-1] for c in cm[:5]))
    return "\n".join(out)


def week_text(g: dict, today: date | None = None, logs: list[dict] | None = None) -> str:
    """The last 7 days of one goal: days answered, commits, one line per day (0 tokens)."""
    today = today or date.today()
    logs = _logs() if logs is None else logs
    start = today - timedelta(days=6)
    mine = [x for x in logs if x["goal"] == g["name"] and start.isoformat() <= x["date"] <= today.isoformat()
            and not x["entry"].startswith("(no answer")]
    cm = commits(g["repo"], start, today, limit=100)
    days = sorted({x["date"] for x in mine})
    out = [f"{g['name']}, last 7 days: notes on {len(days)} of 7 days" + (f", {len(cm)} commits" if g["repo"] else "") + "."]
    for d in days:
        es = [x["entry"] for x in mine if x["date"] == d]
        line = "; ".join(es)
        out.append(f"• {date.fromisoformat(d).strftime('%a')}: {line[:140] + ('…' if len(line) > 140 else '')}")
    return "\n".join(out)


def status_text(g: dict, today: date | None = None) -> str:
    """'Thesis: day 12 of 30 (40%), 18 days left · 9 notes · last: ...'."""
    today = today or date.today()
    start, end = _d(g["start"]) or today, _d(g["end"])
    bits = []
    if end:
        left = (end - today).days
        total = max(1, (end - start).days)
        n = min(total, max(0, (today - start).days + 1))
        if g["kind"] == "project":
            bits.append(f"day {n} of {total} ({round(100 * n / total)}%), {max(0, left)} days left (ends {_nice(end)})")
        else:
            bits.append(_count_words(left, end))
    else:
        bits.append(f"day {(today - start).days + 1}, no end date")
    mine = [x for x in _logs() if x["goal"] == g["name"] and not x["entry"].startswith("(no answer")]
    if mine:
        bits.append(f"{len(mine)} notes, last on {mine[-1]['date']}: {mine[-1]['entry'][:80]}")
    if g["repo"] and (cm := commits(g["repo"], start, today, limit=500)):
        bits.append(f"{len(cm)} commits, last: {cm[0].split(' ', 1)[-1][:60]}")
    if g["status"] == "paused":
        bits.append("paused")
    return f"{g['name']}: " + " · ".join(bits) + "."


def _count_words(left: int, end: date) -> str:
    if left > 1:
        return f"{left} days left ({_nice(end)})"
    return "tomorrow" if left == 1 else "today" if left == 0 else f"ended {-left} days ago"


def show() -> str:
    gs = [g for g in all_goals() if g["status"] != "done"]
    if not gs:
        return "No goals yet. Say e.g. 'my exam is in 30 days, remind me every day' or 'I started a project that ends in 6 months, ask me every day'."
    return "🎯 Your goals:\n" + "\n".join(f"{i}. {status_text(g)}" for i, g in enumerate(gs, 1))


def overview() -> str:
    """Everything on the Work card in words: goals, my list (reminders / to-do / read later), the coding project."""
    parts = [show()]
    try:
        from jarvis.core import readlater
        rows = readlater.ordered()
        parts.append(readlater.show() if rows else "Your list (reminders, to-do, read later) is empty.")
    except Exception as e:
        log.debug("list for overview failed: %s", e)
    try:
        from jarvis.core import timemachine as tm
        parts.append(f"Coding project: {tm.resolve('').name}.")
    except Exception:
        pass
    return "\n\n".join(parts)


def cards(today: date | None = None) -> list[dict]:
    """Small dicts for the dashboard's Work card / sheet."""
    today = today or date.today()
    out, logs = [], _logs()
    for g in all_goals():
        if g["status"] == "done":
            continue
        start, end = _d(g["start"]) or today, _d(g["end"])
        total = max(1, (end - start).days) if end else 0
        done_days = min(total, max(0, (today - start).days)) if end else 0
        mine = [x for x in logs if x["goal"] == g["name"] and not x["entry"].startswith("(no answer")]
        out.append({"id": g["id"], "name": g["name"], "kind": g["kind"], "status": g["status"],
                    "end": g["end"], "end_nice": _nice(end) if end else "", "left": (end - today).days if end else None,
                    "day": (today - start).days + 1, "total": total, "progress": round(done_days / total, 3) if total else None,
                    "remind": g["remind"], "ask": g["ask"], "ask_at": g["ask at"], "folder": g["folder"], "repo": g["repo"],
                    "today": [x["entry"] for x in mine if x["date"] == today.isoformat()][:3],
                    "notes": len(mine), "last": mine[-1]["entry"][:120] if mine else ""})
    return out


# --- messages (scheduler worker) ---------------------------------------------------------------------------------------
def reminder_text(g: dict, today: date) -> str:
    end = _d(g["end"])
    if g["kind"] == "project":
        start = _d(g["start"]) or today
        if not end:
            return f"📂 {g['name']}: day {(today - start).days + 1}."
        total, left = max(1, (end - start).days), (end - today).days
        if left == 0:
            return f"🏁 {g['name']} ends today. Say 'make the {g['name']} report' for the full report."
        return f"📂 {g['name']}: day {min(total, (today - start).days + 1)} of {total}, {left} days left."
    if not end:
        return f"📅 {g['name']}."
    left = (end - today).days
    if left > 7:
        return f"📅 {g['name']}: {left} days left ({_nice(end)})."
    if left > 1:
        return f"⏳ {g['name']}: only {left} days left ({_nice(end)})."
    if left == 1:
        return f"⏳ {g['name']} is tomorrow ({_nice(end)})."
    return f"🎯 {g['name']} is today. Good luck!"


def _fired() -> dict:
    try:
        return json.loads(store.kv_get(FIRED_KEY) or "{}")
    except ValueError:
        return {}


def _wait() -> dict:
    try:
        return json.loads(store.kv_get(WAIT_KEY) or "{}")
    except ValueError:
        return {}


def _clear_wait(gid: str) -> None:
    if str(_wait().get("id", "")) == str(gid):
        store.kv_delete(WAIT_KEY)


def waiting(now: float | None = None) -> dict | None:
    """The goal whose check-in question is still open (asked < GOAL_ANSWER_S ago), or None."""
    w = _wait()
    if not w or (now or time.time()) - float(w.get("ts", 0)) > config.GOAL_ANSWER_S:
        return None
    return next((g for g in all_goals("active") if g["id"] == str(w.get("id"))), None)


def _send(title: str, text: str) -> None:
    from jarvis.core import notify
    notify.notify(title, text, level="info", source=SOURCE, telegram=True)


def tick(now: datetime | None = None) -> list[str]:
    """Send what is due now: countdown/progress reminders, check-in questions (+ one 'still waiting'), the weekly
    summary on Sunday evening, and close finished days and ended goals. Returns what it sent (for logs/tests)."""
    now = now or datetime.now()
    p = path()
    if not p.exists():
        return []
    today, sent = now.date(), []
    st = _fired()
    if st.get("date") != today.isoformat():
        st = {"date": today.isoformat(), "done": []}
    done = set(st["done"])
    _close_days(today)
    if not _hours_ok(now):
        return []
    hm = now.strftime("%H:%M")
    late = (now - timedelta(seconds=config.GOAL_LATE_S)).strftime("%H:%M")
    for g in all_goals("active"):
        end = _d(g["end"])
        if end and today > end:
            edit(g["id"], status="done", today=today)
            _send(f"Goal: {g['name']}", f"✅ {g['name']} has ended ({_nice(end)}). I stopped its messages."
                  + (f" Say 'make the {g['name']} report' for the full report." if g["folder"] else ""))
            sent.append(f"{g['id']}:ended")
            continue
        times = [x.strip() for x in g["remind"].split(",") if x.strip()]
        if end and (end - today).days == 0:
            times = times[:1]  # the big day: one message
        for t in times:
            key = f"{g['id']}:r:{t}"
            if key not in done and t <= hm:
                done.add(key)
                if t >= late:  # missed by more than an hour (laptop was off): skip it
                    _send(f"Goal: {g['name']}", reminder_text(g, today))
                    sent.append(key)
        if g["ask"] and g["ask at"]:
            key, again = f"{g['id']}:a", f"{g['id']}:a2"
            answered = any(x["goal"] == g["name"] and x["date"] == today.isoformat() for x in _logs())
            if key not in done and g["ask at"] <= hm:
                done.add(key)
                if not answered and g["ask at"] >= late:
                    _ask(g, g["ask"])
                    sent.append(key)
            elif key in done and again not in done and not answered:
                w = _wait()
                if str(w.get("id")) == g["id"] and time.time() - float(w.get("ts", 0)) >= config.GOAL_ASK_AGAIN_S:
                    done.add(again)
                    _ask(g, "Still waiting: " + g["ask"][0].lower() + g["ask"][1:])
                    sent.append(again)
        if g["weekly"] == "yes" and now.weekday() == 6 and hm >= config.GOAL_WEEKLY_AT and f"{g['id']}:w" not in done:
            done.add(f"{g['id']}:w")
            txt = week_text(g, today)
            if g["folder"]:
                try:
                    (_folder(g) / "weekly" / f"{today.strftime('%G-W%V')}.md").write_text(txt + "\n", encoding="utf-8")
                except OSError:
                    pass
            _send(f"Goal: {g['name']}", "📊 " + txt)
            sent.append(f"{g['id']}:w")
    st["done"] = sorted(done)
    store.kv_set(FIRED_KEY, json.dumps(st))
    return sent


def _ask(g: dict, question: str) -> None:
    store.kv_set(WAIT_KEY, json.dumps({"id": g["id"], "ts": time.time()}))
    _send(CHECKIN + g["name"], f"{question}\nReply to this message (or just tell KURAMA) and I'll save it.")


def _close_days(today: date) -> None:
    """Once per day: a check-in day that got no answer is written as '(no answer)' in the log."""
    last = _d(store.kv_get(DAY_KEY) or "")
    store.kv_set(DAY_KEY, today.isoformat())
    if not last or last >= today:
        return
    with sheets.locked(path()):
        goals, logs = _load()
        changed = False
        for g in goals:
            if g["status"] != "active" or not g["ask"]:
                continue
            d = max(last, _d(g["start"]) or last)
            while d < today:
                if not any(x["goal"] == g["name"] and x["date"] == d.isoformat() for x in logs):
                    logs.append({"date": d.isoformat(), "time": "", "goal": g["name"], "entry": "(no answer)", "from": "kurama"})
                    changed = True
                d += timedelta(days=1)
        if changed:
            logs.sort(key=lambda x: (x["date"], x["time"]))
            _save(goals, logs)


def answer_quote(text: str, quoted: str) -> str | None:
    """A Telegram reply to a check-in message: save it to that goal's log (None = not a check-in)."""
    first = (quoted or "").strip().splitlines()[0] if (quoted or "").strip() else ""
    if not first.startswith(CHECKIN):
        return None
    return log_entry(first[len(CHECKIN):].strip(), text, source="telegram")


# --- the report (AI, background) ---------------------------------------------------------------------------------------
REPORT_PROMPT = ("You write a clear project report in Markdown from the owner's daily progress notes (and git commits). "
                 "Use headings, short paragraphs and bullet lists; group the work by theme; keep real facts only, never "
                 "invent work. Plain simple English.")


def report(goal: str) -> str:
    """Start the formatted report (report.md + report.pdf in the goal's folder) as a background job."""
    g = find(goal)
    if not g:
        return _not_found(goal, all_goals())
    from jarvis.core import jobs
    j = jobs.get_manager().submit(f"report: {g['name']}", "report", lambda ctx: _make_report(ctx, g))
    return f"Writing the {g['name']} report in the background (job #{j.id})."


def _make_report(ctx, g: dict) -> str:
    from jarvis.core import convert, llm
    logs = [x for x in _logs() if x["goal"] == g["name"] and not x["entry"].startswith("(no answer")]
    if not logs:
        return f"» {g['name']} has no notes yet, so there's nothing to report."
    start, today = _d(g["start"]) or date.today(), date.today()
    cm = commits(g["repo"], start, today, limit=400)
    # month by month so a 6-month log never overflows one call (Groq free tier ~8k tokens/min)
    months = sorted({x["date"][:7] for x in logs})
    sections = []
    for mo in months:
        ctx.check()
        notes = "\n".join(f"{x['date']}: {x['entry']}" for x in logs if x["date"].startswith(mo))[:6000]
        mc = [c for c in cm][:40] if len(months) == 1 else []
        user = f"Project: {g['name']}\nMonth: {mo}\nNotes:\n{notes}" + ("\nCommits:\n" + "\n".join(mc) if mc else "")
        ctx.progress(f"writing {mo}")
        sections.append(str(llm.chat([{"role": "system", "content": REPORT_PROMPT + " Write the section for this month "
                                       "only, starting with '## <Month name year>'."}, {"role": "user", "content": user}],
                                     tier="smart", purpose=ctx.purpose(f"report-{mo}"), max_tokens=1200,
                                     priority="background")).strip())
    ctx.check()
    overview = str(llm.chat([{"role": "system", "content": REPORT_PROMPT + " Write only '## Summary': 4-6 sentences on "
                              "what was achieved overall, then '## Next steps' with 3 bullets."},
                             {"role": "user", "content": "\n\n".join(s[:1500] for s in sections)[:7000]}],
                            tier="smart", purpose=ctx.purpose("report-summary"), max_tokens=500,
                            priority="background")).strip()
    days = len({x["date"] for x in logs})
    head = [f"# {g['name']}: report", "", f"| | |", "|---|---|", f"| Started | {g['start']} |",
            f"| Ends | {g['end'] or '-'} |", f"| Report made | {today.isoformat()} |", f"| Days with notes | {days} |"]
    if g["repo"]:
        head.append(f"| Commits | {len(cm)} |")
    md = "\n".join(head) + "\n\n" + overview + "\n\n" + "\n\n".join(sections) + "\n"
    f = _folder(g)
    (f / "report.md").write_text(md, encoding="utf-8")
    pdf = f / "report.pdf"
    try:
        convert.html_to_pdf(convert.md_to_html(md, f"{g['name']} report"), pdf)
    except Exception as e:
        log.warning("report pdf failed: %s", e)
        pdf = f / "report.md"
    ctx.set_output(pdf)
    return f"» The {g['name']} report is ready: {str(pdf).replace(str(Path.home()), '~')}"


# --- one entry point for the tool --------------------------------------------------------------------------------------
def run(action: str = "list", goal: str = "", name: str = "", end: str = "", remind: str = "", ask: str = "",
        ask_at: str = "", text: str = "", status: str = "", repo: str = "") -> str:
    if action == "add":
        return add(name or goal, end, remind, ask, ask_at)
    if action == "list":
        return show()
    if action == "edit":
        return edit(goal or name, name if goal else "", end, remind, ask, ask_at, status, repo)
    if action in ("pause", "resume", "done", "delete"):
        return edit(goal or name, status={"resume": "active", "pause": "paused"}.get(action, action))
    if action == "link":
        if not repo:
            from jarvis.core import timemachine as tm
            try:
                repo = str(tm.resolve(""))
            except tm.TMError:
                return "Which git folder? I don't know your current coding project."
        return edit(goal or name, repo=repo)
    if action == "log":
        g = find(goal or name) or waiting()
        return log_entry(g["id"], text) if g else _not_found(goal, all_goals())
    if action == "report":
        return report(goal or name)
    if action == "overview":
        return overview()
    if action == "postponed":
        g = find(goal or name)
        return (f"Okay. When is {g['name']} now? Say 'move {g['name']} to December 10', or 'delete the {g['name']} goal'."
                if g else _not_found(goal, all_goals()))
    g = find(goal or name)
    if not g:
        return _not_found(goal or name, all_goals())
    if action == "today":
        return day_text(g)
    if action == "week":
        return week_text(g)
    return status_text(g)
