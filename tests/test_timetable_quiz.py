"""Timetable (parse, show, next, reminders) and quiz (made once, spaced repetition, 0-token moves)."""
import json
import time
from datetime import datetime

from jarvis.core import config, fastpath, llm, notes, registry, store, study

TT = """Mon 9:00-10:00 DSA Room 201
Mon 10:15-11:15 Machine Learning Lab 3
Tue 1:00 pm - 2:00 pm Physics, Hall B
Wed 09:00 to 10:30 Maths"""


def test_parse_show_next_and_reminders(monkeypatch):
    c = study.parse(TT)
    assert c[0] == {"day": "mon", "start": "09:00", "end": "10:00", "subject": "DSA", "room": "Room 201"}
    assert c[2]["start"] == "13:00" and c[2]["subject"] == "Physics" and c[2]["room"] == "Hall B"
    assert "Saved 4 classes (Mon, Tue, Wed)" in registry.call("timetable", {"action": "set", "text": TT}).output
    monday = datetime(2026, 10, 26, 8, 52)  # a Monday
    assert study.show("today", monday) == "Today: 09:00-10:00 DSA (Room 201); 10:15-11:15 Machine Learning (Lab 3)"
    assert study.show("tomorrow", monday).startswith("Tomorrow: 13:00-14:00 Physics")
    assert study.show("next", monday) == "Next: DSA in 8 min, Room 201."
    assert study.show("next", datetime(2026, 10, 26, 12, 0)).startswith("Next: Physics Tuesday at 13:00")
    assert "Wed: 09:00-10:30 Maths" in study.show("week")
    assert study.check_reminders(monday) == ["DSA"] and study.check_reminders(monday) == []  # once
    assert store.alerts_recent()[0]["title"] == "DSA in 8 min"


def test_timetable_llm_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "chat", lambda msgs, **k: calls.append(1) or "Thu 11:00-12:00 Chemistry Room 5")
    assert "Saved 1 classes" in study.set_timetable("Thursdays I have chemistry from 11 till noon in room 5")
    assert len(calls) == 1


def test_quiz_spaced_repetition(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "NOTES_DIR", str(tmp_path / "Notes"))
    assert "need some DSA notes" in study.make("DSA")
    notes.add("A heap is a complete binary tree; min-heap root is the smallest", "DSA")
    qs = [{"q": "What shape is a heap?", "a": "A complete binary tree"},
          {"q": "Where is the minimum in a min-heap?", "a": "At the root"}]
    calls = []
    monkeypatch.setattr(llm, "chat", lambda msgs, **k: calls.append(1) or "Sure:\n" + json.dumps(qs))
    assert registry.call("quiz", {"action": "make", "subject": "DSA"}).output.startswith("Made 2 DSA questions")
    assert study.make("DSA").startswith("Made 0")  # no duplicates
    q = registry.call("quiz", {}).output
    assert q.startswith("(DSA, 2 due)")
    assert "Answer:" in registry.call("quiz", {"action": "answer"}).output
    out = registry.call("quiz", {"action": "right"}).output
    assert "again in 1 days" in out and "(DSA, 1 due)" in out
    out = registry.call("quiz", {"action": "wrong"}).output
    assert "comes back soon" in out and "That's all for now." in out
    assert study.ask() == "Nothing to review right now, nice!" and len(calls) == 2
    assert "2 questions" in study.stats()


def test_phrases(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    assert fastpath.match("what do i have tomorrow").args == {"action": "tomorrow"}
    assert fastpath.match("when is my next class").args == {"action": "next"}
    assert fastpath.match(TT).args == {"action": "set", "text": TT}
    assert fastpath.match("quiz me on DSA").args == {"action": "ask", "subject": "DSA"}
    assert fastpath.match("make a quiz from my physics notes").args == {"action": "make", "subject": "physics"}
    assert fastpath.match("show the answer") is None  # no quiz running: not hijacked
    store.kv_set("quiz_current", "x")
    assert fastpath.match("i got it wrong").args == {"action": "wrong"}
