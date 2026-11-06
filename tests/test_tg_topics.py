"""Telegram sections: alerts sorted into topics of the owner's group (the Bot API is mocked)."""
from __future__ import annotations

from jarvis.core import config, notify, tgtopics


def test_setup_and_routing(monkeypatch):
    calls = []

    def call(method, body=None, **kw):
        calls.append((method, dict(body or {})))
        return {"message_thread_id": 100 + len(calls)} if method == "createForumTopic" else {"message_id": 1}
    monkeypatch.setattr(notify, "telegram_call", call)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "42")
    assert tgtopics.setup().startswith("I haven't seen your group yet")
    tgtopics.note_group({"type": "supergroup", "id": -1001, "title": "KURAMA", "is_forum": True})
    assert tgtopics.setup().startswith("Done: 'KURAMA' now has the sections")
    group, thread = tgtopics.where("claude_code", "info")
    assert group == -1001 and thread == 102  # the 2nd topic made: Claude Code
    assert tgtopics.section_for("resource_guard", "warning") == "alerts"
    assert tgtopics.section_for("scheduler", "info") == "reminders"
    assert tgtopics.section_for("kaggle", "info") == "jobs"
    assert tgtopics.section_for("images", "info") == "images"
    calls.clear()
    notify.notify("✅ Claude Code finished", "done", source="claude_code", desktop=False, telegram=True)
    sent = [b for m, b in calls if m == "sendMessage"]
    assert sent and sent[0]["chat_id"] == -1001 and sent[0]["message_thread_id"] == 102
    assert tgtopics.off().startswith("Sections off") and tgtopics.where("claude_code", "info") == (None, None)


def test_bot_main_loop_notes_the_group(monkeypatch):
    """A message in the group reaching the bot's normal loop is remembered for /topics setup (it was not)."""
    from jarvis.workers import telegram_bot
    seen = []
    monkeypatch.setattr(tgtopics, "note_group", seen.append)
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "42")
    bot = telegram_bot.TelegramBot()
    bot.handle({"message": {"chat": {"id": -1009, "type": "supergroup", "title": "KURAMA"}, "text": "/start",
                            "date": 0}})
    assert seen and seen[0]["id"] == -1009



def _calls(monkeypatch):
    calls = []

    def call(method, body=None, **kw):
        calls.append((method, dict(body or {})))
        return {"message_thread_id": 200 + len(calls)} if method == "createForumTopic" else \
            {"message_id": len(calls), "chat": {"id": (body or {}).get("chat_id")}}
    monkeypatch.setattr(notify, "telegram_call", call)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "42")
    return calls


def test_setup_again_adds_only_the_missing_sections(monkeypatch):
    import json
    from jarvis.core import store
    calls = _calls(monkeypatch)
    tgtopics.note_group({"type": "supergroup", "id": -1001, "title": "KURAMA", "is_forum": True})
    store.kv_set("tg_topics", json.dumps({"group": -1001, "title": "KURAMA",  # the old 4 sections
                                          "threads": {"alerts": 1, "claude": 2, "jobs": 3, "other": 4}}))
    assert tgtopics.setup().startswith("Done")
    made = [b["name"] for m, b in calls if m == "createForumTopic"]
    assert made == ["⚙️ Jobs", "🖼️ Images"]  # no second Alerts / Claude Code / Other
    assert tgtopics.where("scheduler", "info") == (-1001, 3)  # the old "Reminders & jobs" topic is Reminders now
    assert any(m == "editForumTopic" and b["name"] == "⏰ Reminders" for m, b in calls)


def test_owner_can_talk_in_a_topic_and_is_answered_there(monkeypatch):
    import json
    from jarvis.core import store
    from jarvis.workers import telegram_bot
    _calls(monkeypatch)
    store.kv_set("tg_topics", json.dumps({"group": -1001, "threads": {"claude": 7, "images": 9}}))
    bot = telegram_bot.TelegramBot()
    mine = {"chat": {"id": -1001, "type": "supergroup"}, "from": {"id": 42}, "message_thread_id": 7,
            "is_topic_message": True, "text": "hi", "date": 9e9}
    assert bot._own_message({"message": mine}) is mine
    assert bot._own_message({"message": {**mine, "from": {"id": 666}}}) is None  # someone else in the group
    assert bot._target(mine) == (-1001, 7)
    assert bot._target({**mine, "is_topic_message": False}) == (-1001, None)  # General
    notify.set_reply_target((-1001, 7))
    try:
        p = notify._route("sendMessage", {"chat_id": "42", "text": "hello"})
    finally:
        notify.set_reply_target(None)
    assert p["chat_id"] == -1001 and p["message_thread_id"] == 7
    assert notify._route("sendPhoto", {"chat_id": "42"}) == {"chat_id": -1001, "message_thread_id": 9}  # Images
    assert notify._route("sendMessage", {"chat_id": "42"}) == {"chat_id": "42"}  # a reply in the private chat


def test_clear_removes_old_alerts_from_telegram(monkeypatch):
    from jarvis.core import reset
    calls = _calls(monkeypatch)
    notify.reset()
    notify.notify("RAM is full", "92% used", level="warning", source="resource_guard", desktop=False, telegram=True)
    out = reset.clear_chat()
    assert "1 old alert removed" in out
    assert [b["message_ids"] for m, b in calls if m == "deleteMessages"] == [[1]]
    assert notify.delete_alerts() == 0  # forgotten once deleted
