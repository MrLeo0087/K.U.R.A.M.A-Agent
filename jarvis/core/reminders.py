"""P9b reminders and scheduled commands (SQLite `schedules`), shared by the schedule tools, the fast path
and the scheduler worker.

  - add(text, when_text, kind): parse the time (when.py regex, one fast-tier call as fallback), store it
  - run_due(now): fire everything due. Reminders -> notify() (desktop + Telegram + spoken when idle).
    Commands -> fast path first (zero tokens), else the agent in text mode with confirmations DENIED
    (confirm-level tools never run unattended; the notification says so). Items more than
    config.SCHEDULE_MISSED_GRACE_S late (laptop off/asleep) are not run: they are marked missed and
    the user is told. Repeating items are rescheduled to their next future occurrence.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime

from jarvis.core import config, notify, store, when

log = logging.getLogger("jarvis.reminders")

KINDS = ("reminder", "command", "alarm", "timer", "task")  # task = a due item from my list (to-do / read later)


def _task(text: str) -> tuple[str, str, str]:
    """'read: Title\nlink' / 'todo: Buy milk' (maybe after 'overdue: ') -> (kind, title, link)."""
    head, _, link = (text or "").removeprefix("overdue: ").partition("\n")
    kind, _, title = head.partition(": ")
    return (kind, title, link.strip()) if kind in ("read", "todo") else ("todo", head, link.strip())


def _dt(now: float | None) -> datetime:
    return datetime.fromtimestamp(now if now is not None else time.time())


def add(text: str, when_text: str, kind: str = "reminder", now: float | None = None,
        use_llm: bool = True) -> str:
    text = re.sub(r"^(?:to|that)\s+", "", " ".join((text or "").split()), flags=re.I).strip(" .")
    if not text:
        return "error: nothing to remind you about"
    kind = kind if kind in KINDS else "reminder"
    now_ts = now if now is not None else time.time()
    w = when.resolve(when_text or "", _dt(now_ts), use_llm=use_llm)
    if w is None:
        return (f"error: I couldn't understand the time {when_text!r} "
                "(try 'at 5 pm', 'in 20 minutes', 'tomorrow at 9', 'every weekday at 9:30')")
    if w.ts <= now_ts:
        return f"error: {when_text!r} is in the past"
    sid = store.schedule_add(text, kind, w.ts, w.repeat, created=now_ts)
    desc = w.describe(_dt(now_ts))
    if kind == "command":
        return (f"Scheduled #{sid} {desc}: \"{text}\". Steps that need your confirmation won't run "
                "unattended.")
    return f"Okay, {kind} #{sid} set for {desc}: {text}."


def _line(r: dict, now: float | None = None) -> str:
    desc = when.describe(r["next_run"], r.get("repeat") or "none", _dt(now))
    label = r.get("kind") if r.get("kind") in KINDS else "reminder"
    return f"#{r['id']} {label} {desc}: {r['text']}"


def list_text(now: float | None = None) -> str:
    rows = store.schedules_list(enabled_only=True, limit=20)
    if not rows:
        return "You have no reminders or scheduled commands."
    return "\n".join(_line(r, now) for r in rows)


def find(query: str | int) -> dict | None:
    q = str(query).strip().lower().lstrip("#")
    q = re.sub(r"^(?:reminder|schedule|number|no\.?)\s*#?", "", q).strip()
    if q.isdigit():
        return store.schedule_get(int(q))
    words = [w for w in re.findall(r"\w+", q) if w not in ("the", "a", "my", "to", "reminder", "about")]
    best, score = None, 0
    for r in store.schedules_list(enabled_only=True, limit=50):
        s = sum(1 for w in words if w in r["text"].lower())
        if s > score:
            best, score = r, s
    return best


def named(text: str) -> dict | None:
    """The pending reminder whose text clearly matches loose words ('the call mom one'); stricter than find()."""
    want = {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2} - {
        "the", "and", "for", "reminder", "remind", "about", "my", "one", "alarm", "timer"}
    best, score = None, 0.0
    for r in store.schedules_list(enabled_only=True, limit=50):
        if r.get("kind") == "command":
            continue
        have = {w for w in re.findall(r"[a-z0-9]+", r["text"].lower()) if len(w) > 2}
        s = len(want & have) / len(want) if want else 0
        if s > score:
            best, score = r, s
    return best if score >= 0.5 else None


def move(query: str | int, when_text: str) -> str:
    """A new time for a reminder / alarm ('move the call mom reminder to 6 pm')."""
    r = find(query) if str(query).strip().isdigit() else named(str(query))
    if r is None:
        return f"no reminder matches {query!r}"
    w = when.resolve(when_text, datetime.now(), use_llm=False)
    if w is None or w.ts <= time.time():
        return f"error: I couldn't use the time {when_text!r}" + (" (it's already past)" if w else "")
    store.schedule_update(r["id"], next_run=w.ts, enabled=1, note="")
    return f"Moved #{r['id']} ({r['text']}) to {when.describe(w.ts, r.get('repeat') or 'none')}."


def rename(query: str | int, new: str) -> str:
    r = find(query) if str(query).strip().isdigit() else named(str(query))
    if r is None:
        return f"no reminder matches {query!r}"
    store.schedule_update(r["id"], text=new.strip(" .'\"")[:200])
    return f"Renamed #{r['id']} to '{new.strip()}'."


def cancel(query: str | int) -> str:
    r = find(query)
    if r is None:
        return f"no reminder matches {query!r}"
    if not r.get("enabled"):
        return f"#{r['id']} is already {r.get('note') or 'finished'}: {r['text']}"
    store.schedule_update(r["id"], enabled=0, note="cancelled")
    return f"Cancelled #{r['id']}: {r['text']}"


# --- firing (scheduler worker) ---
def run_command(text: str) -> str:
    """Run a scheduled command unattended: fast path (zero tokens) else the agent, confirmations denied."""
    denied: list[str] = []

    def deny(prompt: str, *a, **k) -> bool:
        denied.append(str(prompt))
        return False

    answer = ""
    try:
        from jarvis.core import fastpath

        fr = fastpath.try_answer(text, confirm=deny)
        if fr is not None:
            answer = fr.answer
        else:
            from jarvis.core import agent

            bot = agent.Agent(confirm=deny, summarize_async=False, use_planner=False, persist=False,
                              channel="scheduler")
            answer = bot.run(text, mode="text")
    except Exception as e:  # a failing command must never take the worker down
        log.exception("scheduled command failed")
        answer = f"failed: {type(e).__name__}: {e}"
    if denied:
        answer = (f"{answer}\n(Not done: {len(denied)} step(s) need your confirmation and never run "
                  "unattended. Ask me directly to approve.)").strip()
    return str(answer)[:1500]


def _hm(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%I:%M %p").lstrip("0")


def fire(row: dict) -> list[str]:
    from jarvis.core import sound

    kind = row.get("kind")
    if kind == "command":
        result = run_command(row["text"])
        return notify.notify(f"Scheduled: {row['text'][:60]}", result, level="info", source="scheduler")
    if kind == "alarm":  # rings for a while, and reaches the phone too
        sound.play("alarm", config.ALARM_RINGS)
        return notify.notify(f"⏰ Alarm ({_hm(row['next_run'])})", row["text"], level="info", source="scheduler")
    if kind == "timer":  # a laptop thing: sound + desktop; the phone too only when asked ("...and tell me on Telegram")
        sound.play("timer", 3)
        return notify.notify("⏱️ Time's up", row["text"], level="info", source="timer",
                             telegram=True if row.get("note") == "phone" else None)
    if kind == "task":  # from my list: a link to read now, or a to-do to do now; later 'not done yet' once
        from jarvis.core import readlater
        k, title, link = _task(row["text"])
        n = readlater.is_open(k, title, link)
        if row["text"].startswith(readlater.OVERDUE):
            if not n:
                return []  # finished meanwhile: say nothing
            what = "You haven't read this yet" if k == "read" else "You haven't finished this yet"
            return notify.notify("⏳ Not done yet", f"{title}\n{link + chr(10) if link else ''}{what} (it was due "
                                 f"{_hm(row['next_run'] - config.TASK_OVERDUE_S)}). Say 'done {n}' when it's finished.",
                                 level="info", source="scheduler")
        sound.play("reminder", 2)
        if n and config.TASK_OVERDUE_S > 0:  # check back later: still open -> 'not done yet'
            store.schedule_add(readlater.OVERDUE + row["text"], "task", row["next_run"] + config.TASK_OVERDUE_S, "none")
        tail = f"\nSay 'done {n}' when it's finished." if n else ""
        if k == "read":
            return notify.notify("📖 Read it now", f"{title}\n{link}\nYou said you'd read this now.{tail}",
                                 level="info", source="scheduler")
        return notify.notify("✅ Do it now", f"{title}\nIt's time (from your to-do list).{tail}", level="info",
                             source="scheduler")
    sound.play("reminder", 2)
    return notify.notify(f"⏰ Reminder ({_hm(row['next_run'])})", f"{row['text']}\nIt's time, go do it now.",
                         level="info", source="scheduler")


def heads_up(now: float | None = None) -> list[int]:
    """Telegram/desktop heads-up config.REMINDER_LEAD_S before each reminder, once per occurrence (kept in
    `note` as lead:<due ts>). Skipped for reminders set closer than that to their time."""
    now = now if now is not None else time.time()
    lead, sent = config.REMINDER_LEAD_S, []
    if lead <= 0:
        return sent
    for r in store.schedules_list(enabled_only=True, limit=50):
        due = r.get("next_run") or 0
        if r.get("kind") not in ("reminder", "task") or not (now < due <= now + lead) or \
                r["text"].startswith("overdue: "):  # alarms/timers ring alone; a follow-up needs no heads-up
            continue
        mark = f"lead:{int(due)}"
        if r.get("note") == mark or due - (r.get("created") or 0) < lead + 60:
            continue
        store.schedule_update(r["id"], note=mark)  # first: never send it twice
        mins = max(1, round((due - now) / 60))
        if r.get("kind") == "task":
            k, title, link = _task(r["text"])
            what = (f"You saved this to read at {_hm(due)}:\n{title}\n{link}" if k == "read"
                    else f"On your to-do list for {_hm(due)}:\n{title}")
            notify.notify(f"🔔 In {mins} min ({_hm(due)})", f"{what}\nGet ready, I'll tell you again at {_hm(due)}.",
                          level="info", source="scheduler")
        else:
            notify.notify(f"🔔 In {mins} min ({_hm(due)})", f"{r['text']}\nGet ready: I'll remind you again at {_hm(due)}.",
                          level="info", source="scheduler")
        sent.append(r["id"])
    return sent


def run_due(now: float | None = None) -> list[dict]:
    """Fire (or mark missed) every due item. Returns [{id, action}] for logging/tests."""
    now = now if now is not None else time.time()
    done: list[dict] = []
    for r in store.schedules_due(now):
        late = now - (r["next_run"] or now)
        missed = late > config.SCHEDULE_MISSED_GRACE_S
        nxt = when.next_after(r.get("repeat") or "none", r["next_run"], now)
        # update first: a crash while firing must never fire it twice
        if nxt:
            store.schedule_update(r["id"], last_run=now, next_run=nxt, note="missed" if missed else "")
        else:
            store.schedule_update(r["id"], last_run=now, enabled=0, note="missed" if missed else "done")
        if missed:
            due = datetime.fromtimestamp(r["next_run"]).strftime("%a ") + _hm(r["next_run"])
            what = "reminder" if r.get("kind") != "command" else "scheduled command (not run)"
            notify.notify(f"Missed {what}", f"{r['text']} (was due {due}). I couldn't tell you on time because "
                          "the laptop or KURAMA was off then.", level="warning", source="scheduler")
            done.append({"id": r["id"], "action": "missed"})
            continue
        try:
            fire(r)
        except Exception:
            log.exception("schedule #%d failed to fire", r["id"])
        done.append({"id": r["id"], "action": "fired"})
    return done
