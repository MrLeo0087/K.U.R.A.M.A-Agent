from jarvis.api import device


def test_device_info_from_sys_and_cli(monkeypatch, tmp_path):
    out = {
        "nmcli": "no:Other:40\nyes:Home\\:Net:58\n",
        "pactl get-sink-volume": "Volume: front-left: 49152 /  75% / -7.50 dB,   front-right: 49152 /  75% / -7.50 dB\n",
        "pactl get-sink-mute": "Mute: no\n",
    }
    monkeypatch.setattr(device, "_cmd", lambda argv, timeout=2.0: next((v for k, v in out.items() if " ".join(argv).startswith(k)), ""))
    assert device.wifi() == {"ssid": "Home:Net", "signal": 58}
    assert device.volume() == {"percent": 75, "muted": False}
    bat = tmp_path / "BAT0"
    bat.mkdir()
    for k, v in {"energy_full": "39500000", "energy_full_design": "50000000", "cycle_count": "538"}.items():
        (bat / k).write_text(v)
    real_path = device.Path
    monkeypatch.setattr(device, "Path", lambda p: tmp_path if p == "/sys/class/power_supply" else real_path(p))
    assert device.battery_health() == {"health": 79, "cycles": 538}


def test_device_endpoint_is_cached(monkeypatch):
    from fastapi.testclient import TestClient

    from jarvis.api.app import create_app
    from tests.test_api import BASE, settings
    calls = []
    monkeypatch.setattr(device, "collect", lambda: calls.append(1) or {"model": "Laptop", "wifi": None})
    monkeypatch.setattr(device, "_cache", {"t": 0.0, "data": None})
    c = TestClient(create_app(settings()), base_url=BASE)
    assert c.get("/api/v1/device").json()["model"] == "Laptop"
    c.get("/api/v1/device")
    assert len(calls) == 1
