"""Location history: recording/dedupe, summary, Leaflet map, the lightweight worker, phone via Telegram."""
from __future__ import annotations

import time
from unittest import mock

import pytest

from jarvis.core import config, locationlog, store


@pytest.fixture(autouse=True)
def _place(monkeypatch):
    monkeypatch.setattr("jarvis.core.geolocate.place_name", lambda lat, lon, acc=0: f"spot-{lat:.2f}")


def test_record_dedupes_nearby_points():
    base = time.time() - 3600
    assert locationlog.record("phone", 28.05, 81.61, 20, "live", "A", ts=base)
    assert locationlog.record("phone", 28.0501, 81.6101, 20, "live", "A", ts=base + 20) is None  # barely moved
    assert locationlog.record("phone", 28.07, 81.65, 20, "live", "B", ts=base + 600)
    assert len(locationlog.trail("phone", 24)) == 2


def test_summary_and_map(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    base = time.time() - 1800
    for i, (la, lo) in enumerate([(28.05, 81.61), (28.06, 81.63), (28.07, 81.65)]):
        locationlog.record("phone", la, lo, 20, "live", chr(65 + i), ts=base + i * 300)
    s = locationlog.summary("phone", 24)
    assert "Phone history" in s and "3 points" in s and "maps.google.com" in s
    m = locationlog.map_html("phone", 24)
    assert m.exists() and "leaflet" in m.read_text() and str(tmp_path) in str(m)


def test_summary_empty_hints_how_to_fill():
    assert "Share your live location" in locationlog.summary("phone", 24)
    assert "log it as the laptop moves" in locationlog.summary("laptop", 24)


def test_worker_only_hits_network_on_schedule(monkeypatch):
    from jarvis.workers.location_tracker import LocationTracker
    clock = [5_000_000.0]
    w = LocationTracker(now=lambda: clock[0])
    rec = mock.MagicMock(return_value={"lat": 1, "lon": 2, "place": "home"})
    monkeypatch.setattr(locationlog, "record_laptop", rec)
    w.tick()  # first tick (last_log=0 vs a big clock): logs once
    assert rec.call_count == 1
    clock[0] += 120
    w.tick()  # 2 min later: just a clock check, no network
    assert rec.call_count == 1
    clock[0] += config.LOCATION_LOG_INTERVAL_S + 1
    w.tick()
    assert rec.call_count == 2


def test_lost_mode_logs_often_and_notifies(monkeypatch):
    sent = []
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setattr("jarvis.core.notify.notify", lambda *a, **k: sent.append((a, k)) or [])
    out = locationlog.set_lost("laptop", True)
    assert "Lost mode on" in out and locationlog.lost_mode("laptop")
    locationlog.record("laptop", 10.0, 20.0, 50, "ip", "Town")
    assert sent and sent[-1][1].get("telegram") is True
    assert "Lost mode off" in locationlog.set_lost("laptop", False) and not locationlog.lost_mode("laptop")


def test_telegram_logs_shared_phone_location(monkeypatch):
    from jarvis.workers import telegram_bot
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", 42)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "x")
    sent = []
    bot = telegram_bot.TelegramBot()
    monkeypatch.setattr(bot, "send", lambda t: sent.append(t))
    bot.started = 0
    msg = {"chat": {"id": 42}, "date": int(time.time()), "location": {"latitude": 28.1, "longitude": 81.6}}
    bot.handle({"message": msg})
    assert store.location_last("phone")["lat"] == 28.1 and sent and "location" in sent[0].lower()


def test_location_history_tool_opens_map(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    import jarvis.tools.general.location_history as lh
    opened = []
    monkeypatch.setattr(lh, "_open", opened.append)
    locationlog.record("laptop", 28.05, 81.61, 20, "ip", "Home", ts=time.time() - 100)
    out = lh.location_history(device="laptop", hours=24)
    assert "Laptop history" in out and opened and opened[0].endswith(".html")
