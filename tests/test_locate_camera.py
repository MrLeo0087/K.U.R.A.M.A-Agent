"""Accurate location (Wi-Fi/IP, known places, map link) and camera photo/video to the phone — all mocked."""
from __future__ import annotations

import json

import pytest

from jarvis.core import geolocate, guard

SCAN = (
    "yes:58\\:56\\:C2\\:7E\\:A7\\:0C:Narayan@Chaulagain:74:4\n"
    "no:B4\\:CF\\:E0\\:14\\:90\\:F8:Neighbour:40:8\n"
    "no:5C\\:8C\\:30\\:67\\:1B\\:45:Shop:35:6\n"
)


@pytest.fixture
def no_net(monkeypatch):
    monkeypatch.setattr(geolocate, "_cache", {})
    monkeypatch.setattr(geolocate, "_nmcli", lambda fields: SCAN)


def test_scan_parses_escaped_bssids(no_net):
    s = geolocate.scan()
    assert s["ssid"] == "Narayan@Chaulagain" and s["bssid"] == "58:56:C2:7E:A7:0C"
    assert len(s["aps"]) == 3 and s["aps"][0] == {"macAddress": "58:56:C2:7E:A7:0C", "signalStrength": 74 - 100}


def test_where_reports_place_and_map(no_net, monkeypatch):
    monkeypatch.setattr(geolocate, "_geolocate", lambda aps: {"lat": 28.05, "lon": 81.6167, "accuracy": 25000, "source": "ip"})
    monkeypatch.setattr(geolocate, "place_name", lambda lat, lon, acc=0: "Nepalgunj-10")
    txt = geolocate.where_text()
    assert "Nepalgunj-10" in txt and "±25 km" in txt and "via IP" in txt
    assert "maps.google.com/?q=28.05000,81.61670" in txt
    assert "Narayan@Chaulagain" in txt


def test_known_wifi_names_the_spot(no_net, tmp_path, monkeypatch):
    from jarvis.core import store
    monkeypatch.setattr(geolocate, "_geolocate", lambda aps: {"lat": 28.05, "lon": 81.6167, "accuracy": 25000, "source": "ip"})
    monkeypatch.setattr(geolocate, "place_name", lambda lat, lon, acc=0: "Nepalgunj-10")
    assert "Home" in geolocate.label_here("Home")
    saved = json.loads(store.kv_get(geolocate._PLACES_KEY))["58:56:C2:7E:A7:0C"]
    assert saved["label"] == "Home" and "58:56:C2:7E:A7:0C" in saved["aps"]  # + the Wi-Fi surroundings (11-03)
    assert "At: Home" in geolocate.where_text()
    geolocate.forget_here()
    assert "At: Home" not in geolocate.where_text()


def test_geolocate_uses_wifi_then_falls_back_to_ip(no_net, monkeypatch):
    posted = {}

    def fake_post(url, payload, timeout):
        posted.update(payload)
        return {"location": {"lat": 28.05, "lng": 81.62}, "accuracy": 20, "fallback": None}

    monkeypatch.setattr(geolocate, "_post_json", fake_post)
    g = geolocate._geolocate([{"macAddress": "A", "signalStrength": -50}, {"macAddress": "B", "signalStrength": -60}])
    assert g["source"] == "wi-fi" and "wifiAccessPoints" in posted and posted["considerIp"] is True
    # when beacondb only had an IP answer, we call it IP-level, not Wi-Fi
    monkeypatch.setattr(geolocate, "_post_json", lambda u, p, timeout=15: {"location": {"lat": 1, "lng": 2}, "accuracy": 25000, "fallback": "ipf"})
    assert geolocate._geolocate([{"macAddress": "A", "signalStrength": -50}, {"macAddress": "B", "signalStrength": -60}])["source"] == "ip"


def test_where_handles_no_signal(no_net, monkeypatch):
    monkeypatch.setattr(geolocate, "_geolocate", lambda aps: None)
    assert "couldn't fix the location" in geolocate.where_text()


def test_send_photo_delivers_and_reports_busy(monkeypatch, tmp_path):
    pic = tmp_path / "shot.jpg"
    pic.write_bytes(b"\xff\xd8jpeg")
    sent = []
    monkeypatch.setattr(guard, "photo", lambda: pic)
    monkeypatch.setattr(guard.config, "TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setattr("jarvis.tools.general.send_file_telegram.deliver", lambda p, caption="": sent.append(p) or "Sent.")
    assert "camera" in guard.send_photo().lower() and sent == [pic]

    guard.last_error = "busy"
    monkeypatch.setattr(guard, "photo", lambda: None)
    assert "busy" in guard.send_photo()
    guard.last_error = "none"
    assert "no webcam" in guard.send_photo()


def test_send_clip_records_seconds(monkeypatch, tmp_path):
    vid = tmp_path / "clip.mp4"
    vid.write_bytes(b"\x00" * 100)
    got = {}
    monkeypatch.setattr(guard, "clip", lambda s=5.0: got.update(sec=s) or vid)
    monkeypatch.setattr(guard.config, "TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setattr("jarvis.tools.general.send_file_telegram.deliver", lambda p, caption="": "Sent.")
    assert "video" in guard.send_clip(8).lower() and got["sec"] == 8


def test_phone_commands_match():
    from jarvis.core import phone
    assert phone.CAMERA.match("/camera") and phone.CAMERA.match("send me a photo from the laptop camera")
    assert phone.VIDEO.match("/video 8").group("sec") == "8"
    assert phone.WHERE.match("where is my laptop") and phone.WHERE.match("locate the laptop now")
    assert phone.HERE.match("this is home").group("label") == "home"
    assert phone.HELP_RE.match("give me all laptop control commands") and phone.HELP_RE.match("/help")
    assert not phone.HELP_RE.match("open youtube") and not phone.CAMERA.match("what is the weather")


def test_find_my_phone_opens_the_page(monkeypatch):
    import jarvis.tools.general.find_my_phone as fmp
    opened = []
    monkeypatch.setattr(fmp, "_open", opened.append)
    assert "Find My Device" in fmp.find_my_phone(phone="android") and "google.com/android/find" in opened[0]
    assert "iPhone" in fmp.find_my_phone(phone="iphone") and "icloud.com/find" in opened[1]


def test_find_my_phone_fastpath(monkeypatch):
    from jarvis.core import config, fastpath
    monkeypatch.setattr(config, "FASTPATH", True)
    assert fastpath.match("find my phone").args == {"phone": "android", "want": "open"}
    assert fastpath.match("find my iphone").args == {"phone": "iphone"}
    assert fastpath.match("where is my laptop").tool == "laptop_guard"  # the laptop, not the phone
