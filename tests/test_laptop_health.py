"""Plan 11-09 phase 3: laptop health quietly (disk trend, battery care) and Downloads tidied with old installers
offered as a button; a message only when it needs you."""
import time

import pytest

from jarvis.core import automation, health, notify, store

DAY = 86400.0


@pytest.fixture
def kv(monkeypatch):
    d = {}
    monkeypatch.setattr(store, "kv_get", lambda k: d.get(k))
    monkeypatch.setattr(store, "kv_set", lambda k, v: d.__setitem__(k, v))
    return d


def test_a_disk_that_fills_fast_is_told_once_a_week_a_steady_one_never(kv):
    t0 = 1000 * DAY
    for i in range(8):  # 2 GB a day, 40 GB left at the end
        out = health.disk_check(t0 + i * DAY, free=int((54 - 2 * i) * 1e9), total=int(105e9))
    assert out and "full in about 20 days" in out
    assert health.disk_check(t0 + 8 * DAY, free=int(38e9), total=int(105e9)) is None  # told this week already
    kv.clear()
    for i in range(10):
        assert health.disk_check(t0 + i * DAY, free=int(50e9), total=int(105e9)) is None


def test_plugged_in_at_full_for_hours_gets_one_tip_a_day(kv, monkeypatch):
    monkeypatch.setattr(health, "battery_health", lambda: (75, 551))
    t = 2000 * DAY
    assert health.battery_check(t, plugged=True, percent=100) is None
    out = health.battery_check(t + 3.5 * 3600, plugged=True, percent=100)
    assert out and "75%" in out and "551" in out
    assert health.battery_check(t + 5 * 3600, plugged=True, percent=100) is None
    assert health.battery_check(t + 6 * 3600, plugged=False, percent=100) is None


def test_nightly_tidy_tells_what_it_did_and_offers_old_installers(kv, monkeypatch, tmp_path):
    kv["sort_auto"] = "1"
    old = tmp_path / "zoom.deb"
    old.write_bytes(b"0" * 2_000_000)
    monkeypatch.setattr(automation, "sort_run", lambda: "Sorted 3 files into folders.")
    monkeypatch.setattr(automation, "old_installers", lambda days=30: [old])
    got = {}
    monkeypatch.setattr(notify, "notify", lambda title, text, **k: got.update(title=title, text=text, **k))
    automation.sort_auto_tick()
    assert "zoom.deb" in got["text"] and got["markup"]["inline_keyboard"][0][0]["callback_data"] == "/oldinstallers"


def test_the_health_report_names_battery_disk_and_ram(kv, monkeypatch):
    monkeypatch.setattr(health, "battery_health", lambda: (75, 551))
    out = health.report()
    assert "Battery health 75%" in out and "Disk" in out and "RAM" in out
