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
