"""11-10 owner: "I cannot talk with it like a human, it doesn't understand what I'm talking about". From the traces:
'remove first one' right after the goals list went to the to-do list; 'remove drink water task' said "no such
task" (it was a goal); 'ring my mobile' opened a web page though the phone is paired; 'Peer My Phone' (pair,
misheard) "sent your phone to Telegram"; 'organize this folder' got a file; 'ask the Gmini' wasn't sent."""
import json
import time
from pathlib import Path

import pytest

from jarvis.core import config, fastpath, focus, semantic, store


@pytest.fixture
def meaning(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    monkeypatch.setattr(config, "SEMANTIC_ROUTER", True)
    if not semantic.ensure_ready(30):
        pytest.skip("meaning model not available")
    semantic._tables.clear()
    yield
    semantic._tables.clear()


def test_remove_first_one_after_the_goals_list_is_that_goal(meaning, monkeypatch):
    from jarvis.core import goals, workmem
    monkeypatch.setattr(workmem, "last_list", lambda within_s=300: "goals")
    monkeypatch.setattr(goals, "all_goals", lambda status="": [{"name": "Drink water", "status": "active"},
                                                             {"name": "Exam", "status": "active"}])
    it = fastpath.match("remove first one")
    assert (it.tool, it.args) == ("goals", {"action": "delete", "goal": "Drink water"})


def test_a_goal_named_in_a_todo_removal_is_removed_from_the_goals(monkeypatch):
    from jarvis.core import goals, todos
    from jarvis.tools.general import goals as gt
    monkeypatch.setattr(todos, "find", lambda ref: None)
    monkeypatch.setattr(goals, "find", lambda name: {"name": "Drink water"})
    monkeypatch.setattr(gt, "goals", lambda action, goal: f"{action} {goal}")
    assert todos.remove("drink water task") == "delete Drink water"


@pytest.mark.parametrize("text,tool,args", [
    ("Ring my mobile.", "phone_link", {"action": "ring"}),
    ("Peer My Phone", "phone_link", {"action": "pair"}),
    ("Can you ask the Gmini to explain this code?", "ask_ai", {"question": "Explain this code", "site": "gemini"}),
])
def test_traced_phrasings(meaning, text, tool, args):
    it = fastpath.match(text)
    assert it is not None and (it.tool, it.args) == (tool, args), text


def test_this_folder_is_a_folder(tmp_path, monkeypatch):
    f = tmp_path / "shot.png"
    f.write_bytes(b"x")
    monkeypatch.setattr(focus, "_refer", lambda text: f)
    assert focus.refer("this folder") == tmp_path and focus.refer("this") == f
