from jarvis.core import remotedesk, telesec


def _fake(monkeypatch, ok=True):
    calls, kv = [], {}
    monkeypatch.setattr(remotedesk, "installed", lambda: True)
    monkeypatch.setattr(remotedesk, "_ensure_running", lambda: None)
    monkeypatch.setattr(remotedesk, "get_id", lambda: "123456789")
    monkeypatch.setattr(remotedesk, "_helper", lambda *a: (calls.append(a), (ok, "" if ok else "sudo: a password is required"))[1])
    monkeypatch.setattr(remotedesk.store, "kv_set", lambda k, v: kv.__setitem__(k, v))
    monkeypatch.setattr(remotedesk.store, "kv_get", lambda k, d=None: kv.get(k, d))
    return calls, kv


def test_start_sets_fresh_password_with_expiry(monkeypatch):
    calls, _ = _fake(monkeypatch)
    a, b = remotedesk.start(), remotedesk.start()
    assert a["id"] == "123456789" and len(a["password"]) == 8 and a["password"] != b["password"]
    assert calls[0] == ("on", a["password"]) and remotedesk.expires_at() > 0
    assert "15 minutes" in remotedesk.status_text(a) or "minutes" in remotedesk.status_text(a)


def test_expiry_rotates_password_off(monkeypatch):
    calls, _ = _fake(monkeypatch)
    remotedesk.start()
    exp = remotedesk.expires_at()
    assert not remotedesk.expire_if_due(exp - 1)
    assert remotedesk.expire_if_due(exp + 1)
    assert calls[-1] == ("off",) and remotedesk.expires_at() == 0
    assert not remotedesk.expire_if_due(exp + 100)


def test_no_sudo_setup_gives_hint(monkeypatch):
    _fake(monkeypatch, ok=False)
    assert "one-time setup" in remotedesk.start()["error"]


def test_stop_phrases_and_not_pin_gated():
    for t in ("/control off", "stop remote desktop", "turn off rustdesk", "end remote control"):
        assert remotedesk.STOP_RE.match(t)
        assert not telesec.is_risky(t)
    assert telesec.is_risky("/control laptop")
