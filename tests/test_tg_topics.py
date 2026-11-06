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
    assert tgtopics.section_for("scheduler", "info") == "jobs"
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
