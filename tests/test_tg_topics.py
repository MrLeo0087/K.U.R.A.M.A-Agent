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
    topic = [b for b in sent if b.get("chat_id") == -1001]  # 11-09: rings in the private chat + a silent topic copy
    assert topic and topic[0]["message_thread_id"] == 102 and topic[0].get("disable_notification") is True
    assert tgtopics.off().startswith("Sections off") and tgtopics.where("claude_code", "info") == (None, None)


def test_bot_main_loop_notes_the_group(monkeypatch):
    """A message in the group reaching the bot's normal loop is remembered for /topics setup (it was not)."""
    from jarvis.workers import telegram_bot
    seen = []
    monkeypatch.setattr(tgtopics, "note_group", seen.append)
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "42")
    bot = telegram_bot.TelegramBot()
    bot.handle({"message": {"chat": {"id": -1009, "type": "supergroup", "title": "KURAMA"}, "from": {"id": 42},
                            "text": "/start", "date": 0}})
    assert seen and seen[0]["id"] == -1009
    bot.handle({"message": {"chat": {"id": -1008, "type": "supergroup"}, "from": {"id": 7}, "text": "hi", "date": 0}})
    assert len(seen) == 1  # a stranger's message never makes a group yours



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
    assert made == ["⚙️ Jobs", "🖼️ Images", "🔗 Share"]  # no second Alerts / Claude Code / Other
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


def test_answers_are_also_filed_in_their_section(monkeypatch):
    """Asked in the private chat (or General): the answer stays there, and a copy goes to its section."""
    import json
    from jarvis.core import store
    from jarvis.workers import telegram_bot
    calls = _calls(monkeypatch)
    store.kv_set("tg_topics", json.dumps({"group": -1001, "threads": {"reminders": 5, "images": 9}}))
    assert tgtopics.section_for_tools(["get_time", "add_reminder"]) == "reminders"
    assert tgtopics.section_for_tools(["weather"]) is None
    bot = telegram_bot.TelegramBot()
    monkeypatch.setattr(store, "tools_since", lambda ts: ["add_reminder"])
    bot._file_copy({"message_id": 70}, ("42", None), [71], 0)
    copy = [b for m, b in calls if m == "copyMessages"][-1]
    assert copy == {"chat_id": -1001, "message_thread_id": 5, "from_chat_id": "42", "message_ids": [70, 71]}
    calls.clear()
    bot._file_copy({"message_id": 70}, (-1001, 5), [71], 0)  # asked in Reminders itself: no copy
    assert not calls
    notify._after_send("sendPhoto", {"chat_id": "42"}, {"message_id": 80})  # a picture in the private chat
    assert calls[-1] == ("copyMessages", {"chat_id": -1001, "message_thread_id": 9, "from_chat_id": "42",
                                          "message_ids": [80]})



def test_a_strangers_group_is_left(monkeypatch):
    from jarvis.workers import telegram_bot
    calls = _calls(monkeypatch)
    telegram_bot.TelegramBot()._note_group({"my_chat_member": {
        "chat": {"id": -1777, "type": "supergroup"}, "from": {"id": 666},
        "new_chat_member": {"status": "member"}}})
    assert ("leaveChat", {"chat_id": -1777}) in calls


def test_a_deleted_topic_is_forgotten_and_the_alert_still_arrives(monkeypatch):
    import json
    from jarvis.core import store
    sent = []

    def call(method, body=None, **kw):
        if body.get("message_thread_id") == 5:
            raise RuntimeError("telegram sendMessage failed: Bad Request: message thread not found")
        sent.append(body)
        return {"message_id": 1}
    monkeypatch.setattr(notify, "telegram_call", call)
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "42")
    store.kv_set("tg_topics", json.dumps({"group": -1001, "threads": {"reminders": 5, "alerts": 6}}))
    assert notify.send_long("Drink water", -1001, thread=5)
    assert sent[-1]["chat_id"] == "42"  # the private chat instead
    assert tgtopics.where("scheduler", "info") == (None, None) and tgtopics.where("guard", "warning") == (-1001, 6)


def test_a_picture_goes_where_it_was_asked_and_only_once(monkeypatch, tmp_path):
    """11-06: 'generate an image of Iron Man and send it to Telegram' from General: the job's own send-back and the
    asked send gave two photos, both in Images only. Now one photo, in General (and a copy in Images)."""
    from jarvis.tools.general import send_file_telegram as sft
    calls = _calls(monkeypatch)
    sft._just_sent.clear()
    pic = tmp_path / "ironman.jpg"
    from PIL import Image
    Image.new("RGB", (40, 40), "red").save(pic)
    with notify.replying_to((-1001, None)):  # asked in General
        first = sft.deliver(pic, auto=True)  # the job's own send-back
        second = sft.deliver(pic, "Here is the generated image.")  # the asked "send it to Telegram"
    assert "Already sent" in second and "Already sent" not in first
    photos = [b for m, b in calls if m == "sendPhoto"]
    assert len(photos) == 1


def test_an_alert_in_a_topic_rings_the_phone(monkeypatch):
    """11-06: 'Claude Code finished' came in its topic without a notification (the 🔔 mention wasn't enough, 11-09):
    it goes to the private chat, which rings; the topic keeps a silent copy. A plain alert keeps the mention."""
    import json
    from jarvis.core import store
    calls = _calls(monkeypatch)
    store.kv_set("tg_topics", json.dumps({"group": -1001, "threads": {"claude": 4}}))
    notify.reset()
    notify.notify("✅ Claude Code finished", "all done", source="claude_code", desktop=False, telegram=True)
    sent = [b for m, b in calls if m == "sendMessage"]
    assert str(sent[0]["chat_id"]) == "42" and "message_thread_id" not in sent[0]
    assert sent[1]["message_thread_id"] == 4 and sent[1].get("disable_notification") is True
