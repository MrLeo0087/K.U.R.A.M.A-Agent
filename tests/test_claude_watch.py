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
    assert card.startswith("🤖 Claude Code is working (KURAMA)") and "Progress: 1 of 3 parts done" in card
    assert "Right now: add tests." in card and "ran the tests" in card and "changed x.py" in card
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "All done: the service works and the tests pass."}]}}) + "\n")
    ev("Stop", transcript_path=str(transcript))
    assert told[-1][0] == "✅ Claude Code finished" and "1 files changed" in told[-1][1]
    assert "All done: the service works" in told[-1][1]
    rep = cw.report()
    assert "Its plan:" in rep and "Files it changed:" in rep and "x.py" in rep and "What it did, in order:" in rep
    cw.turn_off()


def test_a_permission_question_waits_for_the_answer(told):
    cw.turn_on()
    out = ev("PermissionRequest", tool_name="Bash", tool_input={"command": "npm install"})
    qid = out["wait"]
    assert told[-1][0] == "❓ Claude Code needs your OK" and "installed something: npm install" in told[-1][1]
    assert cw.decision(qid) == "" and "Waiting" not in cw.status()
    assert cw.answer(True).startswith("Allowed: installed something: npm install")
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


def test_stop_reaches_claude_code_at_its_next_step(told, monkeypatch):
    monkeypatch.setattr(cw, "install_hooks", lambda: "")
    cw.turn_on()
    ev("UserPromptSubmit", prompt="a long task")
    assert cw.stop().startswith("Stopping Claude Code")
    out = ev("PreToolUse", tool_name="Bash", tool_input={"command": "pytest"})
    assert out == {"stop": "Stopped by the owner from KURAMA."} and told[-1][0] == "⏹ Claude Code stopped"
    assert "was stopped" in cw.status() and cw.stop() == "Claude Code isn't working on anything right now."
    cw.turn_off()


def test_usage_reads_its_own_conversation_files(told, tmp_path, monkeypatch):
    acc = tmp_path / ".claude-x"
    (acc / "projects" / "p").mkdir(parents=True)
    import time as _t
    today = _t.strftime("%Y-%m-%d")
    rows = [{"timestamp": f"{today}T10:00:00Z", "message": {"model": "claude-opus-5-5", "usage": {
        "input_tokens": 1000, "output_tokens": 2500, "cache_read_input_tokens": 40000}}}] * 3
    (acc / "projects" / "p" / "s9.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    monkeypatch.setattr(cw, "settings_files", lambda: [acc / "settings.json"])
    monkeypatch.setattr(cw, "plan_limits", lambda: ["📊 Claude Code limits (your account)",
                                                    "5-hour window: ██░░░░░░░░ 23% used, 77% left · resets 6:54am"])
    out = cw.usage()
    assert out.startswith("📊 Claude Code limits") and "77% left" in out
    assert "Today: 1 conversations, 3 replies, 8k written, 123k read" in out and "claude-opus-5-5" in out


def test_plan_limits_from_claude_codes_own_usage(monkeypatch, tmp_path):
    import subprocess
    (tmp_path / ".claude-a" / "projects").mkdir(parents=True)
    monkeypatch.setattr(cw, "settings_files", lambda: [tmp_path / ".claude-a" / "settings.json"])
    monkeypatch.setattr(cw, "claude_binary", lambda: Path("/bin/true"))

    class R:
        stdout = json.dumps({"is_error": False, "result": "Current session: 23% used · resets Nov 6, 6:54am "
                             "(Asia/Kathmandu)\nCurrent week (all models): 58% used · resets Nov 9, 3:44pm (Asia/K)"})
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    rows = cw.plan_limits()
    assert rows[1] == "5-hour window: ██░░░░░░░░ 23% used, 77% left · resets Nov 6, 6:54am"
    assert rows[2] == "Weekly (all models): █████░░░░░ 58% used, 42% left · resets Nov 9, 3:44pm"


def test_say_goes_into_the_real_vscode_chat(told, monkeypatch):
    from jarvis.core import editor
    cw.turn_on()
    ev("UserPromptSubmit", prompt="build the thing")
    calls = []
    monkeypatch.setattr(editor, "states", lambda: [{"ext": 5, "root": "/home/leo/KURAMA", "workspace": "KURAMA",
                                                    "port": 1, "token": "t"}])
    monkeypatch.setattr(editor, "edit", lambda st, op, **kw: calls.append((op, kw)) or {"ok": True})
    monkeypatch.setattr(cw, "_press_enter", lambda ws: calls.append(("enter", ws)) or True)
    out = cw.say("Hello")
    assert out.startswith("Sent to your Claude Code chat (\"build the thing\")")  # the CURRENT conversation
    assert calls == [("claude_say", {"session": "s1", "text": "Hello", "current": True}), ("enter", "KURAMA")]
    monkeypatch.setattr(editor, "states", lambda: [])  # no KURAMA link: Claude Code's own vscode:// address
    used = []
    monkeypatch.setattr(cw, "_via_uri", lambda sid, text, cwd="": used.append((sid, text)) or "")
    assert cw.say("Hello").startswith("Sent to your Claude Code chat") and used == [("s1", "Hello")]
    monkeypatch.setattr(cw, "_via_uri", lambda sid, text, cwd="": None)  # VS Code not running: says so, no copies
    assert cw.say("Hello").startswith("VS Code isn't open on the laptop")
    cw.turn_off()


def test_go_opens_a_new_chat_and_say_starts_it(told, monkeypatch):
    from jarvis.core import editor
    calls = []
    monkeypatch.setattr(editor, "states", lambda: [{"ext": 6, "root": "/home/leo/KURAMA", "workspace": "KURAMA",
                                                    "port": 1, "token": "t"}])
    monkeypatch.setattr(editor, "edit", lambda st, op, **kw: calls.append((op, kw)) or {"ok": True})
    monkeypatch.setattr(cw, "_press_enter", lambda ws: calls.append(("enter", ws)) or True)
    assert cw.go().startswith("A new Claude Code chat is open in KURAMA") and cw.is_on()
    assert cw.say("build the login page").startswith("Started a new Claude Code chat in KURAMA")
    assert calls == [("claude_new", {}), ("claude_new", {"text": "build the login page"}), ("enter", "KURAMA")]
    cw.event({"hook_event_name": "UserPromptSubmit", "session_id": "new1", "cwd": "/home/leo/KURAMA",
              "prompt": "build the login page"})
    assert not cw._go and cw._current()["id"] == "new1"  # the new chat is the current one: say follows it
    cw.event({"hook_event_name": "Stop", "session_id": "new1", "cwd": "/home/leo/KURAMA",
              "last_assistant_message": "All done. " + "x" * 5000})
    assert told[-1][0] == "✅ Claude Code finished" and told[-1][1].endswith("x" * 5000)  # the WHOLE answer
    cw.turn_off()


def test_an_open_chat_gets_the_text_typed_in(told, monkeypatch):
    """An open conversation refuses a prompt ('Session is already open. Your prompt was not applied'): VS Code only
    focuses its box and KURAMA types the message there, then Enter."""
    from jarvis.core import editor
    cw.turn_on()
    ev("UserPromptSubmit", prompt="the open chat")
    calls = []
    monkeypatch.setattr(editor, "states", lambda: [{"ext": 8, "root": "/home/leo/KURAMA", "workspace": "KURAMA"}])
    monkeypatch.setattr(editor, "edit", lambda st, op, **kw: calls.append(op) or {"ok": True, "typed": False})
    monkeypatch.setattr(cw, "_type_text", lambda ws, text: calls.append(("type", text)) or True)
    monkeypatch.setattr(cw, "_press_enter", lambda ws: calls.append("enter") or True)
    assert cw.say("hi").startswith("Sent to your Claude Code chat")
    assert calls == ["claude_say", ("type", "hi"), "enter"]
    cw.turn_off()


def test_a_long_claude_say_is_one_request():
    """11-06: '/claude say I suggest one more thing .. treat the agent as a new project .. make it separate...'
    reached Claude Code as only 'I suggest one more thing' (the planner split it into tasks)."""
    from jarvis.core import planner
    msg = ("/claude say i suggest one more thing .. treat agent as whole new project .. make it separate folder and "
           "backend so that I can upgrade it later. Also open the folder and run the tests")
    assert planner.is_multi(msg) is False


def test_claude_codes_own_wakeups_are_not_the_owners_prompts():
    """11-06: a background task's notification reached the owner as "▶️ Claude Code started 📝 <task-notification>…",
    cut off. Those are ignored; the owner's prompt is shown whole."""
    from jarvis.core import claudewatch as cw
    assert cw._not_from_owner("<task-notification> <task-id>b1</task-id> ...")
    assert cw._not_from_owner("  <system-reminder>x")
    assert not cw._not_from_owner("fix the tests in jarvis/core")
