"""Phone bridge (files, voice notes, clipboard, screenshot) and laptop guard, with Telegram and devices faked."""
import time

import pytest

from jarvis.core import config, guard, phone, registry, store
from jarvis.workers import telegram_bot


@pytest.fixture
def bot(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr(config, "PHONE_INBOX", str(tmp_path / "Phone"))
    sent = []
    b = telegram_bot.TelegramBot()
    b.started = time.time()
    monkeypatch.setattr(b, "send", sent.append)
    return b, sent


def msg(**kw):
    return {"message": {"chat": {"id": 42}, "date": int(time.time()), **kw}}


def test_file_from_phone_is_saved_in_inbox_or_named_folder(bot, monkeypatch, tmp_path):
    b, sent = bot
    monkeypatch.setattr(phone, "download", lambda fid, max_mb=20.0: (b"%PDF data", "documents/f.pdf"))
    b.handle(msg(document={"file_id": "1", "file_name": "notes.pdf"}))
    assert (tmp_path / "Phone" / "notes.pdf").read_bytes() == b"%PDF data" and "Saved on your laptop" in sent[-1]
    b.handle(msg(document={"file_id": "1", "file_name": "notes.pdf"}))
    assert (tmp_path / "Phone" / "notes (1).pdf").exists()  # never overwrites
    target = tmp_path / "papers"
    target.mkdir()
    import jarvis.core.paths as paths
    monkeypatch.setattr(paths, "smart_path", lambda t, want="any": target if "papers" in t else None)
    b.handle(msg(photo=[{"file_id": "s"}, {"file_id": "big"}], caption="save to papers"))
    assert list(target.glob("photo-*.jpg")) and str(target) in sent[-1]


def test_voice_note_becomes_a_question(bot, monkeypatch):
    b, sent = bot
    monkeypatch.setattr(phone, "voice_text", lambda m: "what time is it")
    asked = []
    monkeypatch.setattr(b, "answer", lambda t: asked.append(t) or "It's 5 PM.")
    b.handle(msg(voice={"file_id": "v"}))
    assert sent == ["🎤 what time is it", "It's 5 PM."] and asked == ["what time is it"]


def test_clipboard_screen_guard_commands(bot, monkeypatch):
    b, _ = bot
    clip = {}
    monkeypatch.setattr(phone, "set_clipboard", lambda t: clip.setdefault("t", t) and "Copied to your laptop's clipboard.")
    monkeypatch.setattr(phone, "clipboard_text", lambda: "laptop text")
    monkeypatch.setattr(phone, "screenshot_to_phone", lambda: "Sent screen.png to Telegram.")
    assert b.answer("copy: pip install -r requirements.txt") == "Copied to your laptop's clipboard."
    assert clip["t"] == "pip install -r requirements.txt"
    assert b.answer("/clip") == "laptop text" and b.answer("send me the laptop clipboard") == "laptop text"
    assert b.answer("/screen") == b.answer("send me a screenshot of my laptop") == "Sent screen.png to Telegram."
    monkeypatch.setattr(guard, "camera", lambda: None)
    assert "guard is on" in b.answer("/guard on") and guard.armed()
    assert b.answer("/guard").startswith("Laptop guard is on")
    assert b.answer("/guard off").startswith("Laptop guard is off") and not guard.armed()


def test_guard_photographs_only_a_real_unlock(monkeypatch):
    # New behaviour: ONLY an unlock (locked -> unlocked) alerts. No password-journal reading (it gave false
    # "wrong password" alarms) and no wake guessing. Disarmed = nothing at all.
    alerts = []
    monkeypatch.setattr(guard, "alert", alerts.append)
    st: dict = {}
    states = iter([True, True, False])
    monkeypatch.setattr(guard, "locked", lambda: next(states))
    assert guard.check(st) == []  # disarmed: nothing
    guard.arm(True)
    guard.check(st)  # locked
    guard.check(st)  # still locked
    assert alerts == []
    guard.check(st)  # locked -> unlocked
    assert alerts == ["Someone just used your laptop"]
    # staying unlocked does not re-alert; a frozen worker (laptop slept) does NOT falsely alert
    monkeypatch.setattr(guard, "locked", lambda: False)
    st["tick"] = time.time() - 600
    guard.check(st)
    assert alerts == ["Someone just used your laptop"]
    guard.arm(False)
    assert guard.check(st) == []  # off: no tracking


def test_guard_tool_and_where(monkeypatch):
    monkeypatch.setattr(guard, "where", lambda: "Wi-Fi: Home")
    assert registry.call("laptop_guard", {"action": "where"}).output == "Wi-Fi: Home"
    assert registry.safety_of(registry.get("laptop_guard")) == "safe"
    assert "off" in registry.call("laptop_guard", {}).output
