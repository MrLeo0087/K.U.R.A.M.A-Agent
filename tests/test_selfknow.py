"""Self-knowledge, password gate, rename (no network, no real DB writes)."""
from __future__ import annotations

import pytest

from jarvis.core import fastpath, identity, selfknow


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    from jarvis.core import config
    monkeypatch.setattr(config, "FASTPATH", True)
    selfknow._state.update(pending="", pending_ts=0.0, unlocked_until=0.0, fails=0)
    kv: dict = {}
    from jarvis.core import store
    monkeypatch.setattr(store, "kv_get", lambda k, d=None: kv.get(k, d))
    monkeypatch.setattr(store, "kv_set", lambda k, v: kv.__setitem__(k, v))
    monkeypatch.setattr(identity, "_cache", None)
    monkeypatch.setattr(config, "SELF_PASSWORD_ALIASES", "")
    monkeypatch.setattr(config, "SELF_PASSWORD_HASH", selfknow.hash_for("Bluefox"))  # a test password, never the real one
    yield
    identity._cache = None
    fastpath.refresh_names()


def test_public_topic_and_paths():
    out = fastpath.try_answer("where do you store the output").answer
    from jarvis.core import config
    assert str(config.OUTPUTS_DIR) in out and "workspace" in out.lower()


def test_locked_topic_needs_password_then_unlocks():
    assert "password" in fastpath.try_answer("where do you store my data").answer.lower()
    assert "not the right password" in fastpath.try_answer("rajesh").answer
    out = fastpath.try_answer("Bluefox").answer
    assert out.startswith("Thank you") and "jarvis.db" in out
    assert selfknow.unlocked()
    assert "Main database" in selfknow.ask("storage")  # stays unlocked for a while


def test_password_never_stored_and_other_messages_cancel():
    assert selfknow.redact("the password is Bluefox") == "[password given]"
    assert selfknow.redact("open youtube") == "open youtube"
    selfknow.ask("architecture")
    assert not selfknow.looks_like_password_try("open youtube please now")  # moved on
    assert not selfknow.pending()


def test_rename_and_answers_to_new_name():
    assert "Friday" in fastpath.try_answer("change your name to Friday").answer
    assert identity.name() == "Friday" and "friday" in identity.names() and "kurama" in identity.names()
    assert fastpath.normalize("hey friday open youtube") == "open youtube"


def test_find_capability_python_project():
    out = fastpath.try_answer("do you have a tool to create a python project").answer
    assert out.startswith("Yes, I can") and "project" in out.lower()
