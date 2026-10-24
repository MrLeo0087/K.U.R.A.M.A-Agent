"""Where is the laptop? (0 chat tokens, no paid keys, no GPS needed)

Order of accuracy:
  1. Known Wi-Fi: if the laptop is on a Wi-Fi you've labelled ("/here Home"), that exact place is reported.
  2. Wi-Fi positioning: nearby access points -> beacondb.net (the free, public successor to Mozilla Location
     Service; same /v1/geolocate API). Street-level where the APs are in the database.
  3. IP fallback: beacondb's own IP database (DB-IP). City-level. This is also what fixes the wrong-city bug:
     ip-api.com placed this ISP in Dhangadhi; DB-IP places it in Nepalgunj.
The coordinates are turned into a place name with OpenStreetMap's Nominatim (free), and into Google/OSM map links.
Nothing is stored remotely by us; the Wi-Fi lookup sends AP identifiers to beacondb the same way every phone does.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
import urllib.request

from jarvis.core import config, store

log = logging.getLogger(__name__)

BEACONDB = "https://api.beacondb.net/v1/geolocate"
NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
_PLACES_KEY = "known_wifi_places"  # {bssid: label}
_UA = "KURAMA-assistant/1.0 (personal laptop locator)"
_cache: dict = {}
_CACHE_S = 180


def _nmcli(fields: str) -> str:
    try:
        return subprocess.run(["nmcli", "-t", "-f", fields, "dev", "wifi"],
                              capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _unescape(s: str) -> str:
    return s.replace("\\:", ":").replace("\\\\", "\\")


def scan() -> dict:
    """Current SSID/BSSID and the visible access points [{mac, signal}]."""
    ssid = bssid = ""
    aps = []
    for ln in _nmcli("ACTIVE,BSSID,SSID,SIGNAL,CHAN").splitlines():
        # terse rows escape the colons inside the BSSID as "\:"; split on the real field colons only
        parts = re.split(r"(?<!\\):", ln)
        if len(parts) < 5:
            continue
        active, mac, name, sig = parts[0], _unescape(parts[1]), parts[2], parts[3]
        if mac.count(":") != 5:
            continue
        try:
            strength = int(sig)
        except ValueError:
            continue
        aps.append({"macAddress": mac.upper(), "signalStrength": strength - 100})  # 0..100 -> ~ -100..0 dBm
        if active == "yes":
            ssid, bssid = name, mac.upper()
    return {"ssid": ssid, "bssid": bssid, "aps": aps}


def _post_json(url: str, payload: dict, timeout: float) -> dict | None:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except Exception as e:
        log.info("geolocate POST %s failed: %s", url, e)
        return None


def _geolocate(aps: list[dict]) -> dict | None:
    """beacondb: Wi-Fi positioning, falling back to its IP database when the APs are unknown."""
    body: dict = {"considerIp": True}
    if len(aps) >= 2:
        body["wifiAccessPoints"] = aps
    d = _post_json(BEACONDB, body, timeout=15)
    loc = (d or {}).get("location") or {}
    if "lat" not in loc or "lng" not in loc:
        return None
    source = "wi-fi" if "wifiAccessPoints" in body and (d or {}).get("fallback") not in ("ipf", "lacf") else "ip"
    return {"lat": float(loc["lat"]), "lon": float(loc["lng"]),
            "accuracy": int(d.get("accuracy", 0) or 0), "source": source}


def place_name(lat: float, lon: float, accuracy: int = 0) -> str:
    # coarse (IP) fixes jitter between calls, so name only the city/town, not a random ward; precise (Wi-Fi) -> street
    zoom = 10 if accuracy >= 5000 else 13 if accuracy >= 1500 else 16
    url = f"{NOMINATIM}?format=jsonv2&lat={lat:.4f}&lon={lon:.4f}&zoom={zoom}&accept-language=en"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=12) as r:
            d = json.load(r)
    except Exception as e:
        log.info("reverse geocode failed: %s", e)
        return ""
    a = d.get("address") or {}
    city = a.get("city") or a.get("town") or a.get("municipality") or a.get("village") or ""
    if accuracy >= 1500:  # coarse: the city (+ district) is all we honestly know
        region = a.get("state_district") or a.get("county") or a.get("state") or ""
        return city or region or (d.get("display_name") or "").split(",")[0]
    if d.get("name"):
        return f"{d['name']}, {city}".strip(", ") if city and city not in d["name"] else d["name"]
    return (d.get("display_name") or "").split(",")[0]


def maps(lat: float, lon: float) -> tuple[str, str]:
    g = f"https://maps.google.com/?q={lat:.5f},{lon:.5f}"
    osm = f"https://www.openstreetmap.org/?mlat={lat:.5f}&mlon={lon:.5f}#map=16/{lat:.5f}/{lon:.5f}"
    return g, osm


# --- known Wi-Fi places ("this spot is home") ---
def _places() -> dict:
    try:
        return json.loads(store.kv_get(_PLACES_KEY, "") or "{}")
    except ValueError:
        return {}


def label_here(label: str) -> str:
    """Remember the current Wi-Fi as a named place (so /where names it exactly)."""
    cur = scan()
    if not cur["bssid"]:
        return "I'm not on Wi-Fi right now, so I can't label this spot. Connect to the Wi-Fi here and try again."
    places = _places()
    label = label.strip()[:40] or "home"
    places[cur["bssid"]] = label
    store.kv_set(_PLACES_KEY, json.dumps(places))
    _cache.clear()  # so /where reflects the new label right away
    return f"Saved: when the laptop is on “{cur['ssid']}” I'll say it's at “{label}”."


def forget_here() -> str:
    cur = scan()
    places = _places()
    if cur["bssid"] in places:
        lbl = places.pop(cur["bssid"])
        store.kv_set(_PLACES_KEY, json.dumps(places))
        _cache.clear()
        return f"Forgot the “{lbl}” label for this Wi-Fi."
    return "This Wi-Fi isn't labelled."


def locate(use_cache: bool = True) -> dict:
    """Best location now: {lat, lon, accuracy, source, ssid, known, place, map, osm}. {} if nothing worked."""
    now = time.time()
    cur = scan()
    if use_cache and _cache and now - _cache.get("at", 0) < _CACHE_S and _cache.get("bssid") == cur["bssid"]:
        return _cache["loc"]
    geo = _geolocate(cur["aps"])
    if not geo:
        return {}
    g, osm = maps(geo["lat"], geo["lon"])
    out = {**geo, "ssid": cur["ssid"], "known": _places().get(cur["bssid"], ""),
           "place": place_name(geo["lat"], geo["lon"], geo["accuracy"]), "map": g, "osm": osm}
    _cache.update(at=now, bssid=cur["bssid"], loc=out)
    return out


def where_text() -> str:
    """A ready-to-send location report for Telegram (0 tokens)."""
    loc = locate()
    if not loc:
        ssid = scan()["ssid"]
        return ("I couldn't fix the location (offline, or no Wi-Fi to scan)."
                + (f"\nWi-Fi: {ssid}" if ssid else ""))
    lines = ["📍 Laptop location"]
    if loc["known"]:
        lines.append(f"At: {loc['known']}")
    around = loc["place"] or "unknown area"
    acc = f" (±{loc['accuracy'] // 1000} km)" if loc["accuracy"] >= 1500 else (
        f" (±{loc['accuracy']} m)" if loc["accuracy"] else "")
    via = "Wi-Fi" if loc["source"] == "wi-fi" else "IP"
    lines.append(f"Around {around}{acc}, via {via}")
    if loc["ssid"]:
        lines.append(f"Wi-Fi: {loc['ssid']}")
    lines.append(f"Map: {loc['map']}")
    return "\n".join(lines)
