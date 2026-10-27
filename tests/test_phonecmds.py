from jarvis.core import fastpath, guard, phonecmds, reset, slash
from jarvis.workers import telegram_bot


def test_telegram_commands_exist_on_the_laptop():
    tg = {c for c, _ in telegram_bot.MENU} | {"video", "here", "history", "changepass", "unlock", "clear", "reset"}
    have = {n for c in slash.COMMANDS for n in (c.name, *c.aliases)}
    assert tg <= have, tg - have


def test_camera_to_workspace_and_phone_only(monkeypatch, tmp_path):
    from jarvis.core import config
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    pic = tmp_path / "g.jpg"
    pic.write_bytes(b"jpg")
    monkeypatch.setattr(guard, "photo", lambda: pic)
    assert "It's in the workspace" in phonecmds.run("camera") and list((tmp_path / "images").glob("*-camera.jpg"))
    assert "Telegram" in phonecmds.run("control") and "/lockscreen" in phonecmds.run("lock")
    monkeypatch.setattr(reset, "clear_recent", lambda agent=None: "cleared")
    assert "Send '/clear yes'" in phonecmds.run("clear") and phonecmds.run("clear", "yes") == "cleared"
    i = fastpath.match("/mute ram 20")
    assert i.tool == "_cmd" and i.args == {"cmd": "mute", "arg": "ram 20"}


def test_phone_location_from_telegram_and_other_log_fixes(monkeypatch):
    from jarvis.core import locationlog, store
    from jarvis.tools.general import find_my_phone as fmp
    opened = []
    monkeypatch.setattr(fmp, "_open", opened.append)
    assert fmp.find_my_phone(want="location").startswith("Opened Google Find My Device")  # nothing shared yet
    store.location_add("phone", 28.06254, 81.64485, 20, "shared", "Nepalgunj-06", None)
    out = fmp.find_my_phone(want="location")
    assert out.startswith("📍 Your phone was at Nepalgunj-06 (±20 m)") and "maps.google.com/?q=28.06254,81.64485" in out
    assert len(opened) == 1 and locationlog.phone_now()
    m = fastpath.match
    for s in ("Kurema, can you give me the location of my mobile phone?", "Give me the location that share in the telegram.",
              "middle version of my mobile phone, right?", "where is my phone"):
        assert m(s).args == {"phone": "android", "want": "location"}, s
    assert m("find my phone").args["want"] == "open"
    assert m("I don't know, what is the task running on 8080 port of my laptop?").args == {"action": "port", "target": "8080"}
    assert m("Can you change the language of the selected sentence into Nepali?").args["text"] == ""
    assert m("I am spending 20 rupees on the noodles and 50 rupees on the toffee").tool == "expenses"


def test_reply_questions_use_the_reply_tool(monkeypatch):
    m = fastpath.match
    for s in ("What should be the reply for his message now?", "What should reply I should give to my friend for this conversation?",
              "what should I reply to my friend", "suggest a good reply to this message"):
        i = m(s)
        assert i and i.tool == "text_assist" and i.args["action"] == "reply", s
    assert m("what should I write in my essay") is None
    from jarvis.core import assist, rewrite
    monkeypatch.setattr(rewrite, "grab", lambda: "nothing highlighted")
    monkeypatch.setattr(assist, "_screen_chat", lambda: "Friend: are you coming tonight?")
    seen = []
    monkeypatch.setattr(assist, "reply", lambda chat, req, lang: seen.append(chat) or "Yes, see you at 7!")
    monkeypatch.setattr(rewrite, "_xclip", lambda *a, **k: "")
    out = assist.run("reply", "what should I reply to my friend")
    assert seen == ["Friend: are you coming tonight?"] and out.startswith("Yes, see you at 7!")  # read from the open chat
