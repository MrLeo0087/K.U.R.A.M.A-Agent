"""To-do list: the tasks the user has to do (KURAMA's own SQLite table `todos`, 0 tokens).

A to-do is NOT a reminder: it never rings by itself. It has a title, an optional due date (with or without a time),
a priority (1 high, 2 normal, 3 low) and a tag, and it stays on the list until it is done or deleted. When the user
also wants an alert ("...and remind me Thursday at 6") a normal reminder is created and linked (reminder_id);
finishing or deleting the to-do cancels it. Reminders ("remind me to call mom at 5") live in the scheduler
(reminders.py) and the reading list in readlater.py: three separate lists.

Numbers ("done 2") always follow the list order: dated first (soonest, overdue on top), then undated; within the
same moment high priority first.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime

from jarvis.core import store

PRIORITY = {1: "high", 2: "normal", 3: "low"}
_HIGH = re.compile(r"\b(?:high|urgent|important|asap|top|critical)\b", re.I)
_LOW = re.compile(r"\b(?:low|someday|whenever|not\s+urgent|later)\b", re.I)
_HAS_TIME = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)|\bat\s+\d|\b\d{1,2}:\d{2}\b|\b(?:noon|midnight|morning|"
                       r"afternoon|evening|tonight|night)\b|\bin\s+\d+\s*(?:min|minute|hour|hr)", re.I)
MIGRATED_KEY = "todos_migrated_from_sheet"


def priority_of(word: str | int | None) -> int:
    if isinstance(word, int):
        return word if word in PRIORITY else 2
    w = (word or "").strip()
    return 1 if _HIGH.search(w) else 3 if _LOW.search(w) else 2


def parse_due(when_text: str, now: datetime | None = None) -> tuple[float, bool] | None:
    """('tomorrow' -> end of tomorrow, no time) / ('friday 5 pm' -> that moment, with time); None = not a date."""
    from jarvis.core import when
    text = (when_text or "").strip()
    if not text:
        return None
    now = now or datetime.now()
    w = when.resolve(re.sub(r"^(?:by|before|due|until|till)\s+", "", text, flags=re.I), now, use_llm=False)
    if w is None:
        return None
    if _HAS_TIME.search(text):
        return w.ts, True
    day = datetime.fromtimestamp(w.ts).replace(hour=23, minute=59, second=0, microsecond=0)
    return day.timestamp(), False


def _due_words(r: dict, now: datetime | None = None) -> str:
    if not r.get("due"):
        return ""
    now = now or datetime.now()
    d = datetime.fromtimestamp(r["due"])
    days = (d.date() - now.date()).days
    day = "today" if days == 0 else "tomorrow" if days == 1 else "yesterday" if days == -1 else \
        d.strftime("%A") if 1 < days < 7 else d.strftime("%d %b")
    when_ = f"{day} {d.strftime('%I:%M %p').lstrip('0')}" if r.get("due_time") else day
    late = (d < now) if r.get("due_time") else days < 0
    return f"overdue ({when_})" if late else f"due {when_}"


def _clean_title(text: str) -> str:
    t = " ".join((text or "").split()).strip(" .,;:")
    return t[:1].upper() + t[1:200] if t else ""


# --- reading the list ---
def items() -> list[dict]:
    """Open to-dos in list order (numbering starts at 1), each with its due text."""
    now = datetime.now()
    out = store.todos_open()
    for i, r in enumerate(out, 1):
        r["n"], r["due_text"], r["priority_name"] = i, _due_words(r, now), PRIORITY.get(r["priority"], "normal")
    return out


def _line(r: dict) -> str:
    flag = "❗ " if r["priority"] == 1 else ""
    extra = "".join(f"  {x}" for x in (f"#{r['tag']}" if r["tag"] else "", r["due_text"]) if x)
    bell = "  🔔" if r.get("reminder_id") else ""
    return f"{r['n']}. {flag}{r['title']}{extra}{bell}"


def show(tag: str = "", scope: str = "all") -> str:
    rows = items()
    tag = tag.strip().lstrip("#").lower()
    if tag:
        rows = [r for r in rows if r["tag"] == tag]
    if scope == "today":
        end = datetime.now().replace(hour=23, minute=59, second=59).timestamp()
        rows = [r for r in rows if r["due"] and r["due"] <= end]
    if not rows:
        what = f" tagged #{tag}" if tag else " for today" if scope == "today" else ""
        return f"Your to-do list is empty{what}. Say 'add <task> to my to-do list' (optionally 'by Friday', 'high priority')."
    head = f"✅ To-do ({len(rows)}{' today' if scope == 'today' else ''}{' #' + tag if tag else ''})"
    return "\n".join([head, *(_line(r) for r in rows), "Say 'done 2' when you finish one, or 'delete 2'."])


def find(ref: str | int) -> dict | None:
    """The open to-do meant by a number ('2', 'second') or loose words ('the report one')."""
    rows = items()
    s = str(ref).strip().lower()
    words = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "last": len(rows)}
    n = int(s) if s.isdigit() else words.get(re.sub(r"\s+(?:one|task|item|to-?do)$", "", s), 0)
    if n:
        return rows[n - 1] if 1 <= n <= len(rows) else None
    want = {w for w in re.findall(r"[a-z0-9]+", s) if len(w) > 2} - {"the", "and", "for", "task", "todo", "list", "my", "one"}
    best, score = None, 0.0
    for r in rows:
        have = {w for w in re.findall(r"[a-z0-9]+", r["title"].lower()) if len(w) > 2}
        sc = 1.0 if s and s in r["title"].lower() else (len(want & have) / len(want | have) if want and have else 0)
        if sc > score:
            best, score = r, sc
    return best if score >= 0.34 else None


# --- changing it ---
def _link_reminder(title: str, remind_text: str) -> tuple[int | None, str]:
    from jarvis.core import reminders
    out = reminders.add(f"To-do: {title}", remind_text)
    m = re.search(r"#(\d+)", out)
    return (int(m.group(1)), "") if m and not out.startswith("error") else (None, out)


PENDING_KEY = "todo_pending"  # 'add a task' with no task: the next short reply is the task


def pending() -> bool:
    try:
        d = json.loads(store.kv_get(PENDING_KEY) or "{}")
    except ValueError:
        return False
    return bool(d) and time.time() - float(d.get("ts", 0)) <= 180


def clear_pending() -> None:
    store.kv_delete(PENDING_KEY)


def add(text: str, when_text: str = "", tag: str = "", priority: str | int = "", remind_text: str = "") -> str:
    title = _clean_title(text)
    if not title:
        store.kv_set(PENDING_KEY, json.dumps({"ts": time.time()}))
        return "What should I add to your to-do list? (You can add a date: 'finish the report by Friday'.)"
    clear_pending()
    due = parse_due(when_text) if when_text else None
    if when_text and due is None:
        return f"I couldn't understand the date {when_text!r}. Try 'tomorrow', 'by Friday', 'Nov 28' or 'Friday 5 pm'."
    pr = priority_of(priority)
    tid = store.todo_add(title, tag.strip().lstrip("#").lower(), pr, due[0] if due else None, bool(due and due[1]))
    msg = f"Added to your to-do list: {title}" + (" (high priority)" if pr == 1 else "")
    if due:
        msg += f", {_due_words(store.todo_get(tid))}"
    if remind_text:
        rid, err = _link_reminder(title, remind_text)
        if rid:
            store.todo_update(tid, reminder_id=rid)
            msg += f". I'll remind you {_reminder_when(rid)}"
        else:
            msg += f". (No reminder: {err.removeprefix('error: ')})"
    return msg + "."


def _reminder_when(rid: int) -> str:
    from jarvis.core import when
    r = store.schedule_get(rid)
    return when.describe(r["next_run"], r.get("repeat") or "none") if r else "then"


def _unlink(r: dict) -> None:
    if r.get("reminder_id"):
        store.schedule_update(int(r["reminder_id"]), enabled=0, note="done")


def by_id(todo_id: int) -> dict | None:
    """The open to-do with this database id (UI buttons use ids, never list numbers)."""
    return next((r for r in items() if r["id"] == int(todo_id)), None)


def done(ref: str | int, r: dict | None = None) -> str:
    r = r or find(ref)
    if r is None:
        return f"I couldn't find {ref!r} in your to-do list.\n" + show()
    store.todo_update(r["id"], done_at=time.time())
    _unlink(r)
    left = len(store.todos_open())
    return f"✔ Done: {r['title']}. " + (f"{left} left." if left else "Your to-do list is empty now 🎉")


def remove(ref: str | int, r: dict | None = None) -> str:
    r = r or find(ref)
    if r is None:
        return f"I couldn't find {ref!r} in your to-do list."
    store.todo_delete(r["id"])
    _unlink(r)
    return f"Deleted from your to-do list: {r['title']}."


def edit(ref: str | int, title: str = "", when_text: str = "", tag: str = "", priority: str | int = "",
         remind_text: str = "") -> str:
    r = find(ref)
    if r is None:
        return f"I couldn't find {ref!r} in your to-do list."
    changes, said = {}, []
    if title.strip():
        changes["title"] = _clean_title(title)
        said.append(f"renamed to '{changes['title']}'")
    if when_text.strip():
        if when_text.strip().lower() in ("none", "no date", "remove", "clear"):
            changes.update(due=None, due_time=0)
            said.append("no due date")
        else:
            due = parse_due(when_text)
            if due is None:
                return f"I couldn't understand the date {when_text!r}."
            changes.update(due=due[0], due_time=int(due[1]))
            said.append(_due_words({"due": due[0], "due_time": due[1]}))
    if tag.strip():
        changes["tag"] = tag.strip().lstrip("#").lower()
        said.append(f"#{changes['tag']}")
    if str(priority).strip():
        changes["priority"] = priority_of(priority)
        said.append(f"{PRIORITY[changes['priority']]} priority")
    if remind_text.strip():
        _unlink(r)
        rid, err = _link_reminder(changes.get("title", r["title"]), remind_text)
        if rid:
            changes["reminder_id"] = rid
            said.append(f"reminder {_reminder_when(rid)}")
        else:
            return f"No reminder: {err.removeprefix('error: ')}"
    if not changes:
        return "What should I change: the name, the date, the tag or the priority?"
    store.todo_update(r["id"], **changes)
    return f"Updated '{r['title']}': " + ", ".join(said) + "."


def clear(done_only: bool = False) -> str:
    """Delete every open to-do (or only forget the finished ones)."""
    if done_only:
        n = store.todos_clear_done()
        return f"Cleared {n} finished to-do{'s' * (n != 1)}."
    rows = store.todos_open()
    for r in rows:
        store.todo_delete(r["id"])
        _unlink(r)
    return f"Deleted {len(rows)} to-do{'s' * (len(rows) != 1)}." if rows else "Your to-do list is already empty."


def finished_today() -> list[dict]:
    t0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    return store.todos_done_between(t0, t0 + 86400)


# --- moving the old to-dos out of the Excel 'My list' (once) ---
def migrate_from_sheet() -> int:
    """Copy the to-do rows of the old combined Excel list into this table (their 'task' alerts become linked
    reminders), then leave only the reading list in the sheet. Runs once; returns how many were moved."""
    if store.kv_get(MIGRATED_KEY):
        return 0
    from jarvis.core import readlater, sheets
    moved = 0
    try:
        p = readlater.path()
        if p.exists():
            with sheets.locked(p):
                rows = readlater._rows()
                keep = []
                for r in rows:
                    if r["type"] != "todo":
                        keep.append(r)
                        continue
                    due, has_time = None, False
                    if r.get("due"):
                        try:
                            due, has_time = datetime.strptime(r["due"], "%Y-%m-%d %H:%M").timestamp(), True
                        except ValueError:
                            pass
                    try:
                        created = datetime.strptime(r.get("saved") or "", "%Y-%m-%d %H:%M").timestamp()
                    except ValueError:
                        created = time.time()
                    tid = store.todo_add(_clean_title(r["title"]), (r.get("tag") or "").lower(), 2, due, has_time,
                                         r.get("note") or "", created)
                    rid = r.get("reminder") or ""
                    if rid.isdigit() and (s := store.schedule_get(int(rid))) and s.get("enabled"):
                        store.schedule_update(int(rid), kind="reminder", text=f"To-do: {_clean_title(r['title'])}")
                        store.todo_update(tid, reminder_id=int(rid))
                    moved += 1
                if moved:
                    readlater._save(keep)
        for s in store.schedules_list(enabled_only=True, limit=200):  # old 'not done yet' follow-ups of to-dos
            if s.get("kind") == "task" and s["text"].startswith(readlater.OVERDUE + "todo: "):
                store.schedule_update(s["id"], enabled=0, note="moved to the to-do list")
    finally:
        store.kv_set(MIGRATED_KEY, json.dumps({"t": time.time(), "moved": moved}))
    return moved


def ensure_migrated() -> None:
    try:
        migrate_from_sheet()
    except Exception:  # the old sheet is optional; never block the to-do list
        store.kv_set(MIGRATED_KEY, json.dumps({"t": time.time(), "moved": 0, "error": True}))


def summary_counts() -> dict:
    rows = items()
    end = (datetime.now().replace(hour=23, minute=59, second=59)).timestamp()
    return {"open": len(rows), "today": sum(1 for r in rows if r["due"] and r["due"] <= end),
            "overdue": sum(1 for r in rows if r["due_text"].startswith("overdue")), "high": sum(r["priority"] == 1 for r in rows)}



def day() -> str:
    """'What's on today?': today's to-dos (and undated ones), today's reminders/alarms, classes and long tasks."""
    from jarvis.core import when
    parts = [show()]
    end = datetime.now().replace(hour=23, minute=59, second=59).timestamp()
    rem = [s for s in store.schedules_list(enabled_only=True, limit=50)
           if s.get("kind") in ("reminder", "alarm", "timer", "task") and s.get("next_run") and s["next_run"] <= end]
    if rem:
        parts.append("⏰ Reminders today:\n" + "\n".join(f"• {when.describe(s['next_run'], s.get('repeat') or 'none')}: {s['text']}"
                                                     for s in rem))
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
