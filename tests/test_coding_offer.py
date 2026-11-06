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
