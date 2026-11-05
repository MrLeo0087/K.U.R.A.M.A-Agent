"""The Claude Code watch: off = nothing kept; events -> Telegram messages + status / report cards; a permission
question waits for /claude yes|no; the hook is added to Claude Code's settings once (all mocked: no Telegram)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from jarvis.core import claudewatch as cw


@pytest.fixture(autouse=True)
def _private(monkeypatch, tmp_path):  # never the real watch flag / state file
    from jarvis.core import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    (tmp_path / "data").mkdir()


@pytest.fixture
def told(monkeypatch):
    sent = []
    monkeypatch.setattr(cw, "_tell", lambda title, text: sent.append((title, text)))
    monkeypatch.setattr(cw, "install_hooks", lambda: "")
    monkeypatch.setattr(cw, "_start_stuck_check", lambda: None)
    cw._sessions.clear()
    cw._questions.clear()
    return sent


def ev(name, **kw):
    return cw.event({"hook_event_name": name, "session_id": "s1", "cwd": "/home/leo/KURAMA", **kw})


def test_off_keeps_nothing(told):
    cw.turn_off()
    assert ev("UserPromptSubmit", prompt="build it") == {} and not cw._sessions and not told
    assert cw.status().startswith("I'm not watching Claude Code")


def test_a_task_from_start_to_finish(told, tmp_path):
    assert cw.turn_on().startswith("Watching Claude Code now")
    ev("UserPromptSubmit", prompt="add the Nepal documents service")
    assert told[-1][0] == "▶️ Claude Code started" and "add the Nepal documents" in told[-1][1]
    ev("PostToolUse", tool_name="TodoWrite", tool_input={"todos": [
        {"content": "write the module", "status": "completed"}, {"content": "add tests", "status": "in_progress"},
        {"content": "update docs", "status": "pending"}]})
    ev("PostToolUse", tool_name="Edit", tool_input={"file_path": "/home/leo/KURAMA/jarvis/core/x.py"})
    ev("PostToolUse", tool_name="Bash", tool_input={"command": "pytest -q tests/test_x.py"})
    card = cw.status()
    assert "🤖 Claude Code: working" in card and "To-do: 1 of 3 done" in card and "▶️ Now: add tests" in card
    assert "ran: pytest -q tests/test_x.py" in card and "edited x.py" in card
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "All done: the service works and the tests pass."}]}}) + "\n")
    ev("Stop", transcript_path=str(transcript))
    assert told[-1][0] == "✅ Claude Code finished" and "1 files changed" in told[-1][1]
    assert "All done: the service works" in told[-1][1]
    rep = cw.report()
    assert "📋 To-do list:" in rep and "📄 Files changed:" in rep and "x.py" in rep and "🧾 Steps:" in rep
    cw.turn_off()


def test_a_permission_question_waits_for_the_answer(told):
    cw.turn_on()
    out = ev("PermissionRequest", tool_name="Bash", tool_input={"command": "npm install"})
    qid = out["wait"]
    assert told[-1][0] == "❓ Claude Code needs your OK" and "ran: npm install" in told[-1][1]
    assert cw.decision(qid) == "" and "Waiting" not in cw.status()
    assert cw.answer(True).startswith("Allowed: ran: npm install")
    assert cw.decision(qid) == "allow" and cw.answer(False) == "Claude Code isn't waiting for an answer right now."
    cw.turn_off()


def test_hooks_are_added_once_with_a_backup(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude-acc2" / "projects").mkdir(parents=True)
    (home / ".claude-acc2" / "settings.json").write_text(json.dumps({"model": "opus"}))
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert "hooks added to .claude-acc2" in cw.install_hooks()
    data = json.loads((home / ".claude-acc2" / "settings.json").read_text())
    assert data["model"] == "opus" and set(cw.HOOK_EVENTS) <= set(data["hooks"])
    cmd = data["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert "claude_watch.on" in cmd and "claude_hook.py" in cmd  # does nothing unless the watch is on
    assert (home / ".claude-acc2" / "settings.json.kurama-backup").exists()
    assert cw.install_hooks() == ""  # never added twice


def test_the_api_route(told, monkeypatch):
    from fastapi.testclient import TestClient
    from jarvis.api.app import create_app
    from jarvis.api.settings import Settings
    cw.turn_on()
    c = TestClient(create_app(Settings(warm_on_start=False, allowed_hosts=["127.0.0.1", "localhost"])),
                   base_url="http://127.0.0.1:8000")
    r = c.post("/api/v1/claude/event", json={"hook_event_name": "PermissionRequest", "session_id": "s2",
                                              "tool_name": "Write", "tool_input": {"file_path": "/a/b.py"}}).json()
    assert r.get("wait") and r["wait_s"] > 0, r
    assert c.get(f"/api/v1/claude/decision?id={r['wait']}").json() == {"answer": ""}
    cw.answer(False)
    assert c.get(f"/api/v1/claude/decision?id={r['wait']}").json() == {"answer": "deny"}
    cw.turn_off()


def test_every_command_is_listed_everywhere():
    """A new slash command always shows in /list (laptop + Telegram) and in the chat box suggestions."""
    from jarvis.core import slash
    from jarvis.workers import telegram_bot as tb
    listed, cat = slash.help_text(), {c["cmd"] for c in slash.catalog()}
    for c in slash.COMMANDS:
        assert f"/{c.name}" in listed and c.name in cat, c.name
    for name, _ in tb.MENU:  # the phone menu's commands are explained in the phone's list
        assert f"/{name}" in tb.HELP or f"/{name}" in listed, name
    menu = [c for c, _ in tb.menu()]
    assert "aod" in menu and "claude" in menu and len(menu) <= 100
    assert time.time() > 0
