"""Plan 11-09 phase 1 (Telegram solid): important alerts ring in the private chat (a silent copy in the topic),
Claude Code waiting for its own background task is not "finished", 'send <a KURAMA thing> to telegram' sends the
thing, one-tap buttons and Yes / No buttons, a phone request waits for its tool instead of becoming a job."""
import json

import pytest

from jarvis.core import claudewatch, config, fastpath, notify, safety, tgtopics


def test_an_important_alert_rings_in_the_private_chat_and_a_silent_copy_goes_to_its_topic(monkeypatch):
    sent = []
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "1:x")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(tgtopics, "where", lambda source, level, title="": (-100, 7))
    monkeypatch.setattr(notify, "telegram_call", lambda method, body, **k: sent.append(body) or {"message_id": 1})
    notify.notify("✅ Claude Code finished", "done", source="claude_code", telegram=True, desktop=False, save=False)
    private = [b for b in sent if str(b.get("chat_id")) == "42"]
    topic = [b for b in sent if b.get("message_thread_id") == 7]
    assert private and not private[0].get("disable_notification")
    assert topic and topic[0].get("disable_notification") is True


def _transcript(tmp_path, done: bool):
    rows = [
        {"message": {"content": [{"type": "tool_use", "id": "tu1", "name": "Bash",
                                  "input": {"command": "ffmpeg -i a.mp4 b.mp4", "description": "Render the video",
                                            "run_in_background": True}}]}},
        {"message": {"content": [{"type": "tool_result", "tool_use_id": "tu1",
                                  "content": "Command running in background with ID: bxyz1"}]}},
    ]
    if done:
        rows.append({"message": {"content": "<task-notification>\n<task-id>bxyz1</task-id>\n<status>completed</status>"
                                            "\n</task-notification>"}})
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows))
    return str(p)


def test_a_background_task_still_running_is_found(tmp_path):
    assert claudewatch.still_running(_transcript(tmp_path, done=False)) == ["Render the video"]
    assert claudewatch.still_running(_transcript(tmp_path, done=True)) == []


def test_claude_code_waiting_for_its_render_is_not_finished(tmp_path, monkeypatch):
    told = []
    monkeypatch.setattr(claudewatch, "is_on", lambda: True)
    monkeypatch.setattr(claudewatch, "_tell", lambda title, text: told.append(title))
    monkeypatch.setattr(claudewatch, "_save", lambda: None)
    claudewatch.event({"hook_event_name": "Stop", "session_id": "s1", "transcript_path": _transcript(tmp_path, False),
                       "last_assistant_message": "Waiting for the render to finish."})
    claudewatch.event({"hook_event_name": "Stop", "session_id": "s2", "transcript_path": _transcript(tmp_path, True)})
    assert told[0].startswith("⏳") and told[1].startswith("✅")


@pytest.mark.parametrize("text,cmd", [("send morning brief to telegram", "brief"),
                                      ("send my battery status to telegram", "battery"),
                                      ("send hello to telegram", None), ("send good night to my telegram", None)])
def test_a_kurama_thing_named_in_a_telegram_send_is_its_result_not_the_words(text, cmd):
    assert fastpath._command_named(text) == cmd


def test_buttons_send_their_commands_and_yes_no_taps_answer(monkeypatch):
    from jarvis.workers import telegram_bot as tb
    assert tb.BUTTONS["🔒 Lock"] == "/lockscreen" and tb.KEYBOARD["is_persistent"] is True
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(notify, "telegram_call", lambda method, body, **k: {})
    bot = tb.TelegramBot.__new__(tb.TelegramBot)
    assert bot._tapped({"callback_query": {"id": "q", "data": "yes", "from": {"id": 42}}}) == "yes"
    assert bot._tapped({"callback_query": {"id": "q", "data": "yes", "from": {"id": 7}}}) is None  # not the owner


def test_a_phone_request_waits_for_its_tool(monkeypatch):
    monkeypatch.setattr(safety, "_wait_for", lambda name: 3.0)

    class Reg:
        def call(self, name, args):
            return safety.ToolResult(True, "ok")
    monkeypatch.setattr(config, "TELEGRAM_TOOL_WAIT_S", 25.0)
    out = safety._call_or_background(Reg(), "claude_code", {}, {"jobs": [], "channel": "telegram"})
    assert out.ok and out.output == "ok"


def test_a_message_from_the_laptop_goes_to_the_private_chat_and_the_groups_general(monkeypatch):
    from jarvis.core import store
    from jarvis.tools.general import _tg
    from jarvis.tools.general.send_message_telegram import send_message_telegram
    sent = []
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "1:x")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(_tg, "ready", lambda: None)
    monkeypatch.setattr(notify, "telegram_call", lambda method, body, **k: sent.append(body) or {"message_id": 1})
    store.kv_set("tg_topics", json.dumps({"group": -1001, "threads": {"share": 9}}))
    assert send_message_telegram("hello").startswith("Sent")
    assert str(sent[0]["chat_id"]) == "42" and "disable_notification" not in sent[0]
    assert sent[1]["chat_id"] == -1001 and "message_thread_id" not in sent[1]  # General
    sent.clear()
    send_message_telegram("https://example.com")
    assert sent[1]["message_thread_id"] == 9  # a link: 🔗 Share
