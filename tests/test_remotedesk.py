from jarvis.core import remotedesk, telesec


def _fake(monkeypatch, ok=True):
    calls, kv = [], {}
    monkeypatch.setattr(remotedesk, "installed", lambda: True)
    monkeypatch.setattr(remotedesk, "_ensure_running", lambda: None)
    monkeypatch.setattr(remotedesk, "service_up", lambda: True)
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


def test_password_only_on_telegram_with_pin_every_time(monkeypatch):
    from jarvis.tools.general.remote_desktop import remote_desktop
    kv = {}
    monkeypatch.setattr(telesec.store, "kv_get", lambda k, d=None: kv.get(k, d))
    monkeypatch.setattr(telesec.store, "kv_set", lambda k, v: kv.__setitem__(k, v))
    fn = getattr(remote_desktop, "func", remote_desktop)
    assert "only given on Telegram" in fn()  # dashboard/voice never get the password
    for t in ("/control", "/changepass", "/changepin", "change remote desktop password"):
        assert remotedesk.wants_password(t)
    assert not remotedesk.wants_password("change my password")
    assert telesec.verify_pin(str(telesec.config.TELEGRAM_RISKY_PIN))  # PIN window open...
    assert "PIN" in telesec.gate("/changepass")                       # ...still asks for the password
    assert telesec.gate("/control off") is None


def test_service_down_is_started_before_password(monkeypatch):
    calls, _ = _fake(monkeypatch)
    state = {"up": False}
    monkeypatch.setattr(remotedesk, "service_up", lambda: state["up"])
    real = remotedesk._helper
    def helper(*a):
        if a == ("ensure",):
            state["up"] = True
        return real(*a)
    monkeypatch.setattr(remotedesk, "_helper", helper)
    r = remotedesk.start()
    assert r["id"] == "123456789" and calls[0] == ("ensure",) and calls[1][0] == "on"


def test_service_wont_start_says_why(monkeypatch):
    _fake(monkeypatch)
    monkeypatch.setattr(remotedesk, "service_up", lambda: False)
    monkeypatch.setattr(remotedesk.time, "sleep", lambda s: None)
    assert "offline" in remotedesk.start()["error"]


def test_keep_alive_restarts_stopped_service_throttled(monkeypatch):
    calls, _ = _fake(monkeypatch)
    state = {"up": False}
    monkeypatch.setattr(remotedesk, "service_up", lambda: state["up"])
    monkeypatch.setattr(remotedesk, "_last_check", 0.0)
    real = remotedesk._helper
    monkeypatch.setattr(remotedesk, "_helper", lambda *a: (state.__setitem__("up", True), real(*a))[1])
    assert remotedesk.keep_alive(1000.0) and calls == [("ensure",)]
    state["up"] = False
    assert not remotedesk.keep_alive(1100.0) and len(calls) == 1  # within 5 min: no check
    assert remotedesk.keep_alive(1400.0) and len(calls) == 2
