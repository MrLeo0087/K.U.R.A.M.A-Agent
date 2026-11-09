"""Plan 11-09 phase 3: 'done for today' saves the tabs / project / song and reports; 'start my day' opens them;
'Send to phone' from the Files app sends the selected files to Telegram."""
import json

import pytest

from jarvis.core import browsertab, day, music, notify, store, timemachine


@pytest.fixture
def kv(monkeypatch):
    d = {}
    monkeypatch.setattr(store, "kv_get", lambda k: d.get(k))
    monkeypatch.setattr(store, "kv_set", lambda k, v: d.__setitem__(k, v))
    monkeypatch.setattr(store, "jobs_list", lambda *a, **k: [])
    return d


def test_done_saves_reports_and_only_sleeps_on_yes_then_start_opens_it_again(kv, monkeypatch, tmp_path):
    monkeypatch.setattr(browsertab, "tabs", lambda: [{"url": "https://kaggle.com/x", "title": "Kaggle"},
                                                     {"url": "chrome://newtab", "title": "New"}])
    monkeypatch.setattr(timemachine, "vscode_folder", lambda: tmp_path)
    monkeypatch.setattr(timemachine, "snapshot", lambda p, reason="": "ok")
    monkeypatch.setattr(music, "running", lambda: False)
    sent, opened = [], []
    monkeypatch.setattr(notify, "telegram_send", lambda text, *a, **k: sent.append(text) or True)
    monkeypatch.setattr(day, "_open", lambda argv: opened.append(argv) or True)
    out = day.done(ask=lambda q: False)
    assert "1 tabs saved: Kaggle" in out and sent and not opened  # "no": nothing closed, no sleep
    assert json.loads(kv[day.KEY])["project"] == str(tmp_path)
    out = day.start()
    assert "Opened 1 tabs" in out and any("https://kaggle.com/x" in a for a in opened[0]) and opened[1] == ["code", str(tmp_path)]


def test_start_without_a_saved_day_says_how(kv):
    assert "done for today" in day.start()


def test_send_to_phone_sends_each_selected_path(monkeypatch):
    from fastapi.testclient import TestClient

    from jarvis.api.app import create_app
    from jarvis.tools.general import send_file_telegram as sft
    got = []
    monkeypatch.setattr(sft, "send_file_telegram", lambda p: got.append(p) or "Sent")
    monkeypatch.setattr(notify, "desktop_send", lambda *a, **k: True)
    import threading
    monkeypatch.setattr(threading, "Thread", lambda target, args=(), **k: type("T", (), {"start": lambda s: target(*args)})())
    from jarvis.api.settings import Settings
    c = TestClient(create_app(Settings(warm_on_start=False, allowed_hosts=["127.0.0.1", "localhost"])),
                   base_url="http://127.0.0.1:8000")
    r = c.post("/api/v1/phone/send", json={"paths": ["/home/x/a.pdf", "/home/x/folder"]})
    assert r.json()["ok"] and got == ["/home/x/a.pdf", "/home/x/folder"]
