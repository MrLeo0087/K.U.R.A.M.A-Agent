from jarvis.core import remotedesk


def test_ensure_unattended_sets_options(tmp_path, monkeypatch):
    cfg = tmp_path / "RustDesk2.toml"
    cfg.write_text("[options]\napprove-mode = 'click'\nfoo = 'bar'\n")
    monkeypatch.setattr(remotedesk, "_config_path", lambda: cfg)
    remotedesk._ensure_unattended()
    text = cfg.read_text()
    assert "approve-mode = 'password'" in text
    assert "verification-method = 'use-permanent-password'" in text
    assert "foo = 'bar'" in text and "'click'" not in text


def test_ensure_unattended_creates_section(tmp_path, monkeypatch):
    cfg = tmp_path / "RustDesk2.toml"
    monkeypatch.setattr(remotedesk, "_config_path", lambda: cfg)
    remotedesk._ensure_unattended()
    assert "[options]\napprove-mode = 'password'" in cfg.read_text() or "[options]\nverification-method" in cfg.read_text()


def test_new_password_changes(monkeypatch):
    monkeypatch.setattr(remotedesk.store, "kv_set", lambda k, v: None)
    a, b = remotedesk._new_password(), remotedesk._new_password()
    assert len(a) == 8 and a != b
