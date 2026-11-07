"""Coding-agent work asked in General mode is offered to the coding agent; 'yes' switches it on and does it."""
from __future__ import annotations

import pytest

from jarvis.core import agent, config, nextstep, semantic


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr(config, "SEMANTIC_ROUTER", True)
    semantic._tables.clear()
    if not semantic.ensure_ready(30):
        pytest.skip("meaning model not available")
    yield
    semantic._tables.clear()


@pytest.mark.parametrize("text", [
    "In this folder in VS Code, I want create a rock paper scissor game in HTML, CSS and JavaScript with very good UI",
    "create an industry standard react project",
    "generate the requirement file for this project"])
def test_offered(model, monkeypatch, text):
    from jarvis import agents
    monkeypatch.setattr(agents, "current", lambda: "general")
    offers = []
    monkeypatch.setattr(nextstep, "offer", lambda c, line="": offers.append(c))
    assert "coding agent" in (agent.coding_job(text) or "")
    assert offers == [agent.CODING_OFFER + text]


@pytest.mark.parametrize("text", ["Can you upgrade the selected code and make it more advanced?",
                                  "How can I run this code?", "what is the weather in pokhara",
                                  "send this image to my telegram"])
def test_not_offered(model, monkeypatch, text):
    from jarvis import agents
    monkeypatch.setattr(agents, "current", lambda: "general")
    assert agent.coding_job(text) is None


def test_requirements_and_project_diagram_go_to_the_coding_agent(monkeypatch):
    from jarvis import agents
    from jarvis.core import fastpath
    from jarvis.core.fastpath import Intent
    monkeypatch.setattr(agents, "current", lambda: "general")
    offers = []
    monkeypatch.setattr(nextstep, "offer", lambda c, line="": offers.append(c))
    monkeypatch.setattr(fastpath, "match", lambda t: Intent("req", "generate_requirements", "devutils", {}))
    assert "coding agent" in agent.coding_only("make requirements.txt for this project")
    monkeypatch.setattr(fastpath, "match", lambda t: Intent("d", "make_diagram", "image", {"kind": "flow"}))
    assert agent.coding_only("flowchart: wake up, brush, study") is None  # a flowchart stays in General
    monkeypatch.setattr(agents, "current", lambda: "coding")
    monkeypatch.setattr(fastpath, "match", lambda t: Intent("req", "generate_requirements", "devutils", {}))
    assert agent.coding_only("make requirements.txt") is None  # the coding agent does it itself


def test_general_and_coding_keep_separate_chats(monkeypatch):
    """11-06: the coding agent's chat must not merge with the General chat (memory and tools stay shared)."""
    from langchain_core.messages import AIMessage, HumanMessage

    from jarvis import agents
    from jarvis.core.agent import Agent
    a = Agent.__new__(Agent)
    a.__dict__.update(history=[HumanMessage(content="hi"), AIMessage(content="hello")], _overflow=[], summary="g",
                      session_id=1, channel="web")
    import threading
    a._lock = threading.Lock()
    mode = {"m": "general"}
    monkeypatch.setattr(agents, "current", lambda: mode["m"])
    a._switch_chat()
    mode["m"] = "coding"
    a._switch_chat()
    assert a.history == [] and a.session_id is None and a._chat_channel() == "web:coding"
    a.history = [HumanMessage(content="build a game")]
    mode["m"] = "general"
    a._switch_chat()
    assert [m.content for m in a.history] == ["hi", "hello"] and a.summary == "g" and a._chat_channel() == "web"


def test_a_clear_change_in_coding_mode_skips_the_ai(monkeypatch):
    """11-07: 'make the Reserve a Table button text white…' went through the AI (~6k tokens) just to pick the tool."""
    from jarvis.core import fastpath
    assert fastpath._CODE_CHANGE.match("make the Reserve a Table button text white so it is readable")
    assert fastpath._CODE_CHANGE.match("now move the score board to the right")
    assert not fastpath._CODE_CHANGE.match("what is the capital of nepal")


def test_yes_answers_the_coding_agents_question_in_any_mode(monkeypatch):
    """The agent asked 'Should I remove TODO.md?': a bare yes goes to it, even in general mode (traces 11-07)."""
    from jarvis import agents
    from jarvis.core import fastpath
    from coder.agent import loop
    monkeypatch.setattr(agents, "current", lambda: "general")
    monkeypatch.setattr(loop, "waiting", lambda: {"goal": "clean", "root": "/tmp", "t": 0})
    it = fastpath.agent_coding_intent("yes")
    assert it is not None and it.args == {"action": "yes"}
    monkeypatch.setattr(loop, "waiting", lambda: None)
    assert fastpath.agent_coding_intent("yes") is None
