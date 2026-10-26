import time

from jarvis.core import config, fastpath, store
from jarvis.tools.general import _sys
from jarvis.tools.general.clipboard_history import clipboard_history
from jarvis.workers import clipboard_watch as cw


def test_secrets_and_password_managers_are_never_kept():
    assert cw.looks_secret("Xk9$mPq2!zT") and cw.looks_secret("ghp_AbCdEf123456789xyz")
    assert not cw.looks_secret("hello world") and not cw.looks_secret("ram@example.com")
    assert not cw.looks_secret("https://github.com/x/Y?a=1")
    assert not cw.keep("pass123", "UTF8_STRING\nx-kde-passwordManagerHint", "")
    assert not cw.keep("some text", "UTF8_STRING", "keepassxc KeePassXC")
    assert cw.keep("Meeting notes for Monday", "UTF8_STRING", "brave-browser Brave-browser")
    assert not cw.keep("__kurama_copy_123__", "UTF8_STRING", "")


def test_history_search_time_restore_and_expiry(monkeypatch):
    now = time.time()
    for text, ago in (("old thing", 30 * 3600), ("https://github.com/leo/kurama", 3600), ("buy milk", 600),
                      ("print('hi')", 60)):
        rid = store.clip_add(text)
        store._exec("UPDATE clipboard SET created=? WHERE id=?", (now - ago, rid))
    store.clip_add("fresh")  # prunes items older than CLIPBOARD_KEEP_H
    assert all(r["text"] != "old thing" for r in store.clip_recent(10))
    assert clipboard_history(minutes_ago=10).startswith("Around then (10 min ago) you copied:\nbuy milk")
    out = clipboard_history(query="github link")
    assert "github.com/leo/kurama" in out and "buy milk" not in out
    listing = clipboard_history(limit=3)
    assert listing.startswith("Copied:\n1. fresh") and "copy back number 2" in listing
    put = []
    monkeypatch.setattr(_sys, "clip_set", put.append)
    assert clipboard_history(restore=2).startswith("Copied it back") and put == ["print('hi')"]
    assert clipboard_history(clear=True).startswith("Forgot") and "Nothing copied yet" in clipboard_history()


def test_routing(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    a = lambda t: fastpath.match(t).args
    assert a("what did I copy 10 minutes ago") == {"action": "history", "limit": 8, "minutes_ago": 10}
    assert a("what did i copy an hour ago")["minutes_ago"] == 60
    assert a("show my clipboard history") == {"action": "history", "limit": 8}
    assert a("find the link I copied") == {"action": "history", "query": "link", "limit": 5}
    assert a("copy back number 2") == {"action": "history", "restore": 2}
    assert a("clear my clipboard history") == {"action": "clear_history"}
    # owner's general phrasings
    assert a("what is my copy ten minutes ago")["minutes_ago"] == 10
    assert a("what was copied ten minutes ago")["minutes_ago"] == 10
    assert a("show my last 20 copies") == {"action": "history", "limit": 20}
    assert a("give me what I copied before") == {"action": "history", "limit": 8}
    assert a("what is on my clipboard") == {"action": "read"}


def test_worker_registered_and_in_modes():
    from jarvis.core import modes
    from jarvis.workers import supervisor
    assert "clipboard_watch" in supervisor.WORKERS and "clipboard_watch" in modes.ESSENTIAL
    assert "clipboard_watch" not in modes.PRESETS["lowram"]["workers"]


def test_copy_event_detection_works_with_real_xlib_classes():
    """python-xlib makes its own event class per display: isinstance() never matched and nothing was recorded."""
    Fake = type("SetSelectionOwnerNotify", (), {"selection": 518})
    assert cw.is_copy_event(Fake(), 518) and not cw.is_copy_event(Fake(), 1)
    assert not cw.is_copy_event(type("PropertyNotify", (), {"selection": 518})(), 518)
