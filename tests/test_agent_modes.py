"""Plan 11-09 phase 6: KURAMA core + Coding and Study modes (each its own chat window and prompt line; 'back to
normal' leaves), the VS Code Coder panel removed (the extension only links the editor), 'clear' at 0 tokens."""
import json
from pathlib import Path

import pytest

from jarvis import agents
from jarvis.core import config, fastpath, semantic, store

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def kv(monkeypatch, tmp_path):
    d = {}
    monkeypatch.setattr(store, "kv_get", lambda k: d.get(k))
    monkeypatch.setattr(store, "kv_set", lambda k, v: d.__setitem__(k, v))
    monkeypatch.setattr(config, "AGENT_MARKER", str(tmp_path / "agent"))
    return d


@pytest.mark.parametrize("text,name", [("study mode", "study"), ("/study", "study"), ("start study mode", "study"),
                                       ("lets study", "study"), ("start coding agent", "coding"),
                                       ("back to normal", "general"), ("/normal", "general"),
                                       ("stop study mode", "general")])
def test_mode_commands(text, name):
    assert fastpath.agent_intent(text).args == {"name": name}


def test_study_mode_has_its_own_chat_and_prompt(kv):
    assert "Study mode on" in agents.switch("study") and agents.current() == "study"
    assert "tutor" in agents.prompt_line() and agents.spec().groups == ("study_mode",)  # its own tool only
    from jarvis.core.agent import Agent
    a = Agent.__new__(Agent)
    a.channel = "web"
    assert a._chat_channel() == "web:study"
    agents.switch("general")
    assert a._chat_channel() == "web"


def test_the_ui_has_the_study_switch():
    html = (ROOT / "frontend/index.html").read_text()
    js = (ROOT / "frontend/app.js").read_text()
    assert 'data-agent="study"' in html and '<option value="study"' in html
    assert '["coding", "study"].includes(n)' in js


def test_the_vscode_extension_has_no_coder_panel():
    pkg = json.loads((ROOT / "vscode_ext/package.json").read_text())
    assert "contributes" not in pkg and not (ROOT / "vscode_ext/coder.js").exists()
    assert 'require("./coder")' not in (ROOT / "vscode_ext/extension.js").read_text()


def test_clear_is_a_zero_token_chat_clear(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    monkeypatch.setattr(config, "SEMANTIC_ROUTER", True)
    if not semantic.ensure_ready(30):
        pytest.skip("meaning model not available")
    semantic._tables.clear()
    try:
        for t in ("clear", "clear the chat", "new chat"):
            it = fastpath.match(t)
            assert (it.tool, it.args) == ("reset_kurama", {"level": "chat"}), t
        assert fastpath.match("clear my ram").tool == "cleanup"
    finally:
        semantic._tables.clear()


def test_vscode_gets_whole_answers_and_coding_mode_is_detailed(monkeypatch):
    """11-07 (kept from the removed panel's tests): a request from VS Code gets the whole answer (VS Code has no
    workspace); coding mode = full answers."""
    from jarvis.core import assist, workspace
    long = "word " * 900
    monkeypatch.setattr(workspace, "SURFACE", "vscode")
    assert workspace.to_workspace("t", long)[0] == long
    assert assist.detailed()
    monkeypatch.setattr(workspace, "SURFACE", "")
    monkeypatch.setattr(agents, "current", lambda: "general")
    assert not assist.detailed()
