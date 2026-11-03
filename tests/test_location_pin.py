"""Laptop location: the free Wi-Fi database doesn't know this area (beacondb answered 'ipf': the internet provider's
city, ±25 km), so a spot is pinned once with the phone's GPS ('/here home' + share location) and found again by
its whole Wi-Fi surroundings; an IP-only answer says it is not the real spot."""
from jarvis.core import geolocate, store

APS = [{"macAddress": m, "signalStrength": s} for m, s in
       (("AA:00:00:00:00:01", -40), ("AA:00:00:00:00:02", -60), ("AA:00:00:00:00:03", -70))]


def _scan(bssid, aps):
    return lambda: {"ssid": "Home", "bssid": bssid, "aps": aps}


def test_here_then_the_phone_location_pins_the_exact_spot(monkeypatch):
    monkeypatch.setattr(geolocate, "scan", _scan("AA:00:00:00:00:01", APS))
    monkeypatch.setattr(geolocate, "geocode", lambda q: None)
    assert "send your phone's location" in geolocate.label_here("home")
    out = geolocate.pin_from_phone(28.0612, 81.6201, 8)
    assert out and "28.0612" in out and "±8 m" in out
    assert geolocate.pin_from_phone(1.0, 1.0) is None  # only right after /here


def test_a_pinned_spot_is_found_by_its_wifi_surroundings(monkeypatch):
    monkeypatch.setattr(geolocate, "scan", _scan("AA:00:00:00:00:01", APS))
    geolocate.label_here("home", 28.0612, 81.6201)
    other = [{"macAddress": "AA:00:00:00:00:02", "signalStrength": -50},
             {"macAddress": "AA:00:00:00:00:03", "signalStrength": -55}, {"macAddress": "BB:1", "signalStrength": -80}]
    hit = geolocate._place_of("CC:NEW:ROUTER", other)  # a different network, the same neighbours
    assert hit and hit["lat"] == 28.0612
    assert geolocate._place_of("CC:NEW:ROUTER", [{"macAddress": "ZZ", "signalStrength": -50}]) is None


def test_an_ip_only_location_says_it_is_not_the_real_spot(monkeypatch):
    monkeypatch.setattr(geolocate, "locate", lambda use_cache=True: {
        "lat": 28.05, "lon": 81.6167, "accuracy": 25000, "source": "ip", "ssid": "Home", "known": "",
        "place": "Nepalgunj", "map": "m", "osm": "o"})
    txt = geolocate.where_text()
    assert "±25 km" in txt and "Not the laptop's real spot" in txt and "/here home" in txt
