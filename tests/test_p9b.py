"""P9b: time parsing, reminders/scheduled commands, scheduler worker, RAM-gated jobs, resume, fast path."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime

import pytest

from jarvis.core import config, jobs, reminders, store, when

NOW = datetime(2026, 10, 23, 14, 0)  # a Friday afternoon
NOW_TS = NOW.timestamp()


def at(*a) -> float:
    return datetime(*a).timestamp()


@pytest.mark.parametrize("text,expect,repeat", [
    ("at 5 pm", at(2026, 10, 23, 17, 0), "none"),
    ("in 20 minutes", at(2026, 10, 23, 14, 20), "none"),
    ("in half an hour", at(2026, 10, 23, 14, 30), "none"),
    ("in 2 hours", at(2026, 10, 23, 16, 0), "none"),
    ("tomorrow at 9", at(2026, 10, 24, 9, 0), "none"),
    ("at 17:30", at(2026, 10, 23, 17, 30), "none"),
    ("at 5", at(2026, 10, 23, 17, 0), "none"),
    ("at 9am", at(2026, 10, 24, 9, 0), "none"),
    ("tonight at 8", at(2026, 10, 23, 20, 0), "none"),
    ("on Monday at 7", at(2026, 10, 26, 7, 0), "none"),
    ("next friday", at(2026, 10, 30, 9, 0), "none"),
    ("day after tomorrow at 6 pm", at(2026, 10, 25, 18, 0), "none"),
    ("every day at 8am", at(2026, 10, 24, 8, 0), "daily"),
    ("every weekday at 9:30", at(2026, 10, 26, 9, 30), "weekdays"),
    ("every monday at 7am", at(2026, 10, 26, 7, 0), "weekly"),
    ("every 30 minutes", at(2026, 10, 23, 14, 30), "every 30 minutes"),
    ("hourly", at(2026, 10, 23, 15, 0), "hourly"),
    ("5 baje", at(2026, 10, 23, 17, 0), "none"),
    ("bholi 9 baje", at(2026, 10, 24, 9, 0), "none"),
    ("beluka 6 baje", at(2026, 10, 23, 18, 0), "none"),
    ("parsi bihana 7 baje", at(2026, 10, 25, 7, 0), "none"),
    ("10 minute pachi", at(2026, 10, 23, 14, 10), "none"),
    ("har din 8 baje", at(2026, 10, 24, 8, 0), "daily"),
])
def test_when_parse_table(text, expect, repeat):
    w = when.parse(text, NOW)
    assert w is not None, text
    assert (w.ts, w.repeat) == (expect, repeat), (text, datetime.fromtimestamp(w.ts))


@pytest.mark.parametrize("text", ["", "xyz", "call mom", "the meeting notes"])
def test_when_parse_rejects(text):
    assert when.parse(text, NOW) is None


def test_when_split_and_next_after():
    assert when.split("call mom at 5 pm", NOW)[:2] == ("call mom", "at 5 pm")
    assert when.split("at 6 pm to drink water", NOW)[:2] == ("drink water", "at 6 pm")
    assert when.split("check the oven in 10 minutes", NOW)[:2] == ("check the oven", "in 10 minutes")
    assert when.split("water the plants", NOW) is None
    fri9 = at(2026, 10, 23, 9, 30)
    assert when.next_after("weekdays", fri9, NOW_TS) == at(2026, 10, 26, 9, 30)  # skips the weekend
    assert when.next_after("daily", fri9, NOW_TS) == at(2026, 10, 24, 9, 30)
    assert when.next_after("none", fri9, NOW_TS) is None


def test_when_llm_fallback_used_only_when_regex_fails(monkeypatch):
    from jarvis.core import llm

    calls = []

    def fake(msgs, schema, **k):
        calls.append(1)
        return schema(datetime_iso="2026-12-25T10:00", repeat="none")
    monkeypatch.setattr(llm, "structured", fake)
    assert when.resolve("at 5 pm", NOW).source == "regex" and not calls
    w = when.resolve("on christmas morning", NOW)
    assert w.source == "llm" and w.ts == at(2026, 12, 25, 10, 0) and calls == [1]


@pytest.fixture
def sent(monkeypatch):
    out: list[tuple] = []
    monkeypatch.setattr(reminders.notify, "notify", lambda title, text="", **k: out.append((title, text, k)) or ["store"])
    return out


def test_reminder_fires_once(sent):
    msg = reminders.add("call mom", "in 1 minute", now=NOW_TS)
    assert "reminder #" in msg and "call mom" in msg
    assert reminders.run_due(NOW_TS + 30) == []
    assert reminders.run_due(NOW_TS + 61)[0]["action"] == "fired"
    assert reminders.run_due(NOW_TS + 120) == []
    assert len(sent) == 1 and sent[0][0].startswith("⏰ Reminder (") and sent[0][1].startswith("call mom")
    row = store.schedules_list(enabled_only=False)[0]
    assert row["enabled"] == 0 and row["note"] == "done"


def test_repeat_reschedules(sent):
    reminders.add("stand up", "every day at 8am", now=NOW_TS)
    first = at(2026, 10, 24, 8, 0)
    assert reminders.run_due(first + 5)[0]["action"] == "fired"
    row = store.schedules_list()[0]
    assert row["enabled"] == 1 and row["next_run"] == at(2026, 10, 25, 8, 0)
    assert "every day at 8:00 AM" in reminders.list_text(NOW_TS)


def test_missed_item_policy(sent):
    reminders.add("pay rent", "at 5 pm", now=NOW_TS)
    reminders.add("stretch", "at 4 pm", now=NOW_TS)
    out = reminders.run_due(at(2026, 10, 23, 17, 30))  # pay rent 30 min late: fires; stretch 1.5 h late: missed
    assert {o["action"] for o in out} == {"fired", "missed"}
    titles = [s[0] for s in sent]
    assert any(t.startswith("⏰ Reminder") for t in titles) and "Missed reminder" in titles
    assert "was off" in next(s[1] for s in sent if s[0] == "Missed reminder")
    notes = {r["text"]: r["note"] for r in store.schedules_list(enabled_only=False)}
    assert notes == {"pay rent": "done", "stretch": "missed"}


def test_heads_up_once_before_reminder(sent, monkeypatch):
    monkeypatch.setattr(reminders.config, "REMINDER_LEAD_S", 600.0)
    reminders.add("morning walk", "at 6 pm", now=NOW_TS)
    due = at(2026, 10, 23, 18, 0)
    assert reminders.heads_up(due - 900) == []  # 15 min before: too early
    sid = reminders.heads_up(due - 540)  # 9 min before
    assert len(sid) == 1 and sent[-1][0] == "🔔 In 9 min (6:00 PM)" and "morning walk" in sent[-1][1]
    assert reminders.heads_up(due - 300) == []  # only once
    reminders.add("tea", "in 5 minutes", now=NOW_TS)  # set inside the lead window: no heads-up
    assert reminders.heads_up(NOW_TS + 60) == []


def test_command_runs_with_confirm_denied(sent, monkeypatch):
    from jarvis.core import agent

    seen = {}

    class FakeAgent:
        def __init__(self, confirm=None, **k):
            seen["kwargs"] = k
            self.confirm = confirm

        def run(self, text, mode="text"):
            seen["mode"] = mode
            seen["allowed"] = self.confirm("Delete /tmp/x?")
            return "I could not delete it."
    monkeypatch.setattr(agent, "Agent", FakeAgent)
    assert "Scheduled #" in reminders.add("delete /tmp/x", "in 5 minutes", kind="command", now=NOW_TS)
    reminders.run_due(NOW_TS + 301)
    assert seen["allowed"] is False and seen["mode"] == "text" and seen["kwargs"]["persist"] is False
    title, text, _ = sent[0]
    assert title.startswith("Scheduled: delete") and "need your confirmation" in text


def test_command_uses_fast_path_first(sent, monkeypatch):
    from jarvis.core import agent

    monkeypatch.setattr(config, "FASTPATH", True)
    monkeypatch.setattr(agent, "Agent", lambda **k: pytest.fail("agent must not run"))
    reminders.add("what time is it", "in 1 minute", kind="command", now=NOW_TS)
    reminders.run_due(NOW_TS + 61)
    assert sent and sent[0][1].startswith("It's")


def test_cancel_and_tools(sent):
    from jarvis.core import registry, safety

    tools = registry.schemas_for(["schedule"])
    assert {t.name for t in tools} == {"add_reminder", "schedule_command", "schedules", "goals"}
    assert next(t for t in tools if t.name == "schedule_command").metadata["safety"] == "confirm"
    out = safety.execute("add_reminder", {"text": "call mom", "when": "tomorrow at 9"})
    assert out.ok and "tomorrow at 9:00 AM" in out.output
    assert "call mom" in safety.execute("list_schedules", {}).output
    assert "Cancelled" in safety.execute("cancel_schedule", {"item": "mom"}).output
    assert "no reminders" in reminders.list_text()
    assert "error" in reminders.add("x", "whenever you like", use_llm=False)


def test_scheduler_worker_tick(sent):
    from jarvis.workers.scheduler import Scheduler

    reminders.add("tea", "in 1 minute", now=NOW_TS)
    w = Scheduler(now=lambda: NOW_TS + 90)
    assert w.run_once() and w.fired == 1 and sent[0][1].startswith("tea")
    from jarvis.workers import supervisor
    assert "scheduler" in supervisor.WORKERS and "scheduler" in config.WORKERS_ENABLED


# --- RAM-aware jobs ---
def test_ram_gate_waits_then_runs(monkeypatch):
    monkeypatch.setattr(config, "JOB_RESOURCE_GATE", True)
    monkeypatch.setattr(config, "JOB_RECHECK_S", 0.01)
    monkeypatch.setattr(config, "JOB_MAX_WAIT_S", 30)
    free = threading.Event()
    monkeypatch.setattr(jobs, "resource_wait_reason", lambda: None if free.is_set() else "RAM")
    m = jobs.get_manager()
    job = m.submit("essay", "write", lambda ctx: "out.md")
    time.sleep(0.1)
    assert job.status == "queued" and "waiting for free RAM" in job.describe()
    assert "waiting for free RAM" in m.list(1)[0].describe()
    free.set()
    m.wait(job.id, timeout=5)
    assert job.status == "done"


def test_ram_gate_max_wait_runs_anyway(monkeypatch):
    monkeypatch.setattr(config, "JOB_RESOURCE_GATE", True)
    monkeypatch.setattr(config, "JOB_RECHECK_S", 0.01)
    monkeypatch.setattr(config, "JOB_MAX_WAIT_S", 0.05)
    monkeypatch.setattr(jobs, "resource_wait_reason", lambda: "RAM")
    m = jobs.get_manager()
    job = m.submit("essay", "write", lambda ctx: "out.md")
    m.wait(job.id, timeout=5)
    assert job.status == "done" and "started anyway" in job.progress


# --- resume ---
def test_resume_job_continues_sections(monkeypatch, tmp_path, sent):
    from jarvis.core import writer

    monkeypatch.setattr(jobs, "notify", lambda *a, **k: None)
    monkeypatch.setattr(writer.llm, "chat", lambda msgs, **k: f"body of {k['purpose'].split(':')[1]}")
    path = tmp_path / "doc.md"
    path.write_text("# Nepal\n\n## Intro\n\nfirst part\n\n", encoding="utf-8")
    jid = store.job_insert("nepal essay", "write", "essay about nepal", status="cancelled")
    store.job_update(jid, error=jobs.INTERRUPTED_QUIT)
    state = {"request": "essay about nepal", "lang": "en", "kind": "write", "title": "Nepal",
             "sections": ["Intro", "History", "Culture"], "done": 1, "path": str(path), "per": 50, "max_tok": 200}
    store.kv_set(f"{writer.RESUME_PREFIX}{jid}", json.dumps(state))
    monkeypatch.setattr("jarvis.core.notify.notify", lambda title, text="", **k: sent.append((title, text, k)))
    assert jobs.announce_interrupted() == 1 and f"resume job {jid}" in sent[-1][1]
    assert jobs.announce_interrupted() == 0  # once only
    from jarvis.core import safety

    out = safety.execute("resume_job", {"job": str(jid)}).output
    assert f"resuming job #{jid}" in out and "section 2/3" in out
    new_id = int(out.split("as job #")[1].split(":")[0])
    jobs.get_manager().wait(new_id, timeout=5)
    text = path.read_text(encoding="utf-8")
    assert text.count("## Intro") == 1 and "## History\n\nbody of section2" in text and "body of section3" in text
    assert "body of section1" not in text
    assert store.kv_prefix(writer.RESUME_PREFIX) == {}
    assert "can't be resumed" in jobs.resume(str(jid))


def test_writer_saves_resume_state(monkeypatch):
    from jarvis.core import writer

    monkeypatch.setattr(jobs, "notify", lambda *a, **k: None)
    monkeypatch.setattr(writer, "_outline", lambda ctx, r, n, l, k: writer.Outline(title="T", sections=["A", "B"]))
    states = []

    def chat(msgs, **k):
        states.append(json.loads(store.kv_get(f"{writer.RESUME_PREFIX}{jid}"))["done"])
        return "text"
    monkeypatch.setattr(writer.llm, "chat", chat)
    job = jobs.get_manager().submit("t", "write", lambda ctx: writer.run(ctx, "a 100 word essay", "en"))
    jid = job.id
    jobs.get_manager().wait(jid, timeout=5)
    assert job.status == "done" and states == [0, 1]
    assert store.kv_get(f"{writer.RESUME_PREFIX}{jid}") is None


# --- fast path ---
def test_fast_path_reminders(monkeypatch):
    from jarvis.core import fastpath

    monkeypatch.setattr(config, "FASTPATH", True)
    i = fastpath.match("remind me to call mom at 5 pm")
    assert (i.tool, i.args) == ("add_reminder", {"text": "call mom", "when": "at 5 pm"})
    i = fastpath.match("KURAMA, remind me in 10 minutes to check the oven")
    assert (i.tool, i.args) == ("add_reminder", {"text": "check the oven", "when": "in 10 minutes"})
    assert fastpath.match("what reminders do I have?").tool == "list_schedules"
    i = fastpath.match("cancel reminder 3")
    assert (i.tool, i.args) == ("cancel_schedule", {"item": "3"})
    assert fastpath.match("remind me about the meeting") is None  # no time: LLM path
    r = fastpath.try_answer("remind me to drink water tomorrow at 9")
    assert r and r.ok and "drink water" in r.answer
    assert store.schedules_list()[0]["text"] == "drink water"
