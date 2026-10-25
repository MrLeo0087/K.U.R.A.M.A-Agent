"""Telegram security: risky detection, the PIN window, and the /lock switch."""
from __future__ import annotations

import pytest

from jarvis.core import config, telesec


@pytest.fixture(autouse=True)
def _pins(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_RISKY_PIN", "1500")
    monkeypatch.setattr(config, "TELEGRAM_LOCK_PIN", "0087")
    monkeypatch.setattr(config, "TELEGRAM_PIN_WINDOW_S", 1800)


def test_risky_detection():
    for t in ["/camera", "shut down the laptop", "delete file x", "send me clz_project folder",
              "send this folder", "where is my laptop", "start remote desktop", "run this command rm -rf"]:
        assert telesec.is_risky(t), t
    for t in ["status", "what's the weather", "/status", "how is training", "set a reminder", "/help"]:
        assert not telesec.is_risky(t), t


def test_pin_gate_and_window():
    assert telesec.gate("/camera") is not None  # needs a PIN
    assert telesec.verify_pin("9999") is False and telesec.gate("/camera") is not None
    assert telesec.verify_pin("1500") is True
    assert telesec.gate("/camera") is None  # unlocked for the window
    assert telesec.gate("status") is None   # harmless always fine


def test_lock_switch():
    telesec.verify_pin("1500")  # even with a PIN window open...
    assert telesec.gate("/camera") is None
    telesec.lock()
    assert telesec.is_locked() and "locked" in telesec.gate("/camera").lower()  # ...lock blocks everything risky
    assert "Wrong" in telesec.unlock("1111") and telesec.is_locked()
    assert "Unlocked" in telesec.unlock("0087") and not telesec.is_locked()
    assert telesec.gate("/camera") is not None  # lock cleared, but the PIN window was dropped by lock()


def test_looks_like_pin():
    assert telesec.looks_like_pin("1500") and telesec.looks_like_pin("/0087")
    assert not telesec.looks_like_pin("hello") and not telesec.looks_like_pin("12")
