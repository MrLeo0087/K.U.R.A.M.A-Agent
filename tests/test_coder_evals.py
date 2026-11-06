"""The coding agent's routing, on the owner's real sentences (coder/evals/routing.py). 0 tokens."""
from __future__ import annotations

import pytest

from coder.evals import routing
from jarvis.core import config, fastpath, semantic


@pytest.fixture
def coding(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    monkeypatch.setattr(config, "SEMANTIC_ROUTER", True)
    semantic._tables.clear()
    if not semantic.ensure_ready(30):
        pytest.skip("meaning model not available")
    from jarvis import agents
    monkeypatch.setattr(agents, "current", lambda: "coding")
    from jarvis.agents.coding import terminal
    monkeypatch.setattr(terminal, "last", lambda *a, **k: None)  # no crash in the terminal
    yield
    semantic._tables.clear()


@pytest.mark.parametrize("sentence,action", routing.CODING_MODE)
def test_real_sentences_reach_the_right_action(coding, sentence, action):
    it = fastpath.agent_coding_intent(sentence)
    got = it.args.get("action") if it is not None else None
    assert got == action, f"{sentence!r} -> {got}, expected {action}"
