import json

from jarvis.core import config, store
from jarvis.tools.general import find_and_send as fs
from jarvis.tools.general import send_file_telegram as sft


def setup(monkeypatch, tmp_path, found):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "1")
    monkeypatch.setattr(config, "SHARE_ROOTS", (tmp_path,))
    sent = []
    monkeypatch.setattr(sft, "deliver", lambda p, caption="": sent.append(p.name) or f"Sent {p.name} to Telegram.")
    monkeypatch.setattr(fs, "search", lambda q: [p for p in found if q.lower() in p.name.lower()])
    return sent


def test_one_match_is_sent(monkeypatch, tmp_path):
    a = tmp_path / "naruto.jpg"
    a.write_bytes(b"x")
    sent = setup(monkeypatch, tmp_path, [a])
    assert fs.find_and_send("naruto.jpg") == "Sent naruto.jpg to Telegram." and sent == ["naruto.jpg"]


def test_several_matches_are_listed_then_picked(monkeypatch, tmp_path):
    files = []
    for n in ("naruto.png", "naruto2.jpg", "naruto.mp4"):
        (tmp_path / n).write_bytes(b"x")
        files.append(tmp_path / n)
    sent = setup(monkeypatch, tmp_path, files)
    out = fs.find_and_send("naruto")
    assert "I found 3 files" in out and "1. naruto.png" in out and "Reply with a number" in out and not sent
    assert fs.find_and_send(pick=2) == "Sent naruto2.jpg to Telegram."
    fs.find_and_send(pick=-1)
    assert sent == ["naruto2.jpg", "naruto.png", "naruto2.jpg", "naruto.mp4"]
    assert fs.find_and_send(pick=9).startswith("error")


def test_no_exact_match_suggests_similar(monkeypatch, tmp_path):
    v = tmp_path / "naruto.mp4"
    v.write_bytes(b"x")
    sent = setup(monkeypatch, tmp_path, [v])
    out = fs.find_and_send("naruto.jpg")
    assert out.startswith("No file named exactly naruto.jpg") and "naruto.mp4" in out and not sent
    assert json.loads(store.kv_get(fs.LAST_KEY))["paths"] == [str(v)]


def test_telegram_bot_number_reply_picks_from_list(monkeypatch, tmp_path):
    from jarvis.workers.telegram_bot import PICK, TelegramBot
    a = tmp_path / "a.pdf"
    a.write_bytes(b"x")
    sent = setup(monkeypatch, tmp_path, [a, a])
    fs.find_and_send("a.pdf")
    assert PICK.match("send 1") and PICK.match("2") and PICK.match("all") and not PICK.match("send me 2 jokes")
    assert TelegramBot.pick_found("1") == "Sent a.pdf to Telegram." and sent == ["a.pdf"]


def test_agent_knows_what_it_sent_and_resumes_telegram_chat(monkeypatch):
    import time

    from jarvis.core import agent, notify
    store.alert_add("Missed reminder", "go to the morning walk (was due Sat 6:00 AM)", "warning", "scheduler",
                    "desktop,telegram,store")
    store.alert_add("Quiet log", "never shown", "info", "x", "store")  # saved only: never reached the user
    line = notify.context_line("why didn't you tell me earlier?")
    assert "Missed reminder: go to the morning walk" in line and "Quiet log" not in line
    assert notify.context_line("what's 2+2") == ""  # unrelated turn: no extra tokens
    assert "Missed reminder" in notify.context_line("ok", channel="telegram")  # telegram right after one

    sid = store.session_start("telegram")
    store.add_message("user", "find naruto", session=sid)
    store.add_message("assistant", "I found 2 files", session=sid)
    store.session_touch(sid)
    a = agent.Agent(channel="telegram", summarize_async=False)
    a._begin_turn("send the first one")
    assert a.session_id == sid and [m.content for m in a.history] == ["find naruto", "I found 2 files"]
    assert time.time() - a._last_turn < 60


def test_full_path_and_name_with_pick(monkeypatch, tmp_path):
    a = tmp_path / "basic_tool.py"
    a.write_bytes(b"x")
    sent = setup(monkeypatch, tmp_path, [a])
    assert fs.find_and_send(str(a), pick=-1) == "Sent basic_tool.py to Telegram."  # full path: sent directly
    assert fs.find_and_send("basic_tool.py", pick=-1) == "Sent basic_tool.py to Telegram."  # name + "all"
    assert fs.find_and_send("/wrong/dir/basic_tool.py") == "Sent basic_tool.py to Telegram."  # bad dir: by name
    assert sent == ["basic_tool.py"] * 3


def test_cross_channel_context():
    from jarvis.core import agent
    sid = store.session_start("")  # the laptop dashboard
    store.add_message("user", "find tool.py in my laptop", session=sid)
    store.add_message("assistant", "I found 8 tool.py files; the list is in your workspace.", session=sid)
    tg = agent.Agent(channel="telegram")
    line = tg._other_channel("send that file to me")
    assert "laptop dashboard" in line and "find tool.py" in line
    assert tg._other_channel("tell me a joke") == ""  # unrelated: no extra tokens
    assert agent.Agent()._other_channel("send that file") == ""  # nothing new on Telegram


def test_image_and_send_to_telegram_is_one_request(monkeypatch):
    from jarvis.core import fastpath, planner
    text = "can you generate an image of the hill in oil paint style and also send that image to telegram"
    assert not planner.is_multi(text)
    it = fastpath.image_intent(text)
    assert it.args == {"prompt": "the hill in oil paint style", "send_to_telegram": True}


def test_list_folder_numbers_files_for_picking(monkeypatch, tmp_path):
    from jarvis.tools.interactive.list_folder import list_folder
    d = tmp_path / "docs"
    (d / "sub").mkdir(parents=True)
    for n in ("a.pdf", "b.jpg"):
        (d / n).write_bytes(b"x")
    out = list_folder(str(d))
    assert "1 folders, 2 files" in out and "Folders: sub" in out and "1. " in out and "2. " in out
    sent = setup(monkeypatch, tmp_path, [])
    assert fs.find_and_send(pick=2).startswith("Sent ") and len(sent) == 1
    assert "a.pdf" in list_folder(str(d), pattern=".pdf") and "b.jpg" not in list_folder(str(d), ".pdf")


def test_phone_gets_only_what_matters(monkeypatch):
    from jarvis.core import notify
    assert notify.wants_phone("warning", "resource_guard") and notify.wants_phone("info", "scheduler")
    assert not notify.wants_phone("info", "jobs") and not notify.wants_phone("info", "focus")


def test_switch_phrases_accents_and_follow_ups(monkeypatch):
    import json
    import time

    from jarvis.core import config, fastpath, stt
    monkeypatch.setattr(config, "FASTPATH", True)
    m = lambda t: (lambda i: (i.tool, i.args) if i else None)(fastpath.match(stt.fix_text(t)))  # noqa: E731
    assert m("Tone of the Bluetooth") == ("laptop_toggle", {"setting": "bluetooth", "state": "off"})
    assert m("PON UP THE BLUETOOTH BRO") == ("laptop_toggle", {"setting": "bluetooth", "state": "on"})
    assert m("disable wifi") == ("laptop_toggle", {"setting": "wifi", "state": "off"})
    assert m("is bluetooth on or off?") == ("laptop_toggle", {"setting": "bluetooth", "state": "status"})
    assert m("then turn it off") is None  # nothing switched recently
    store.kv_set("last_switch", json.dumps({"device": "bluetooth", "t": time.time()}))
    assert m("Then turn off this.") == ("laptop_toggle", {"setting": "bluetooth", "state": "off"})
    assert m("switch off the laptop") == ("power_off", {"action": "shutdown"})
