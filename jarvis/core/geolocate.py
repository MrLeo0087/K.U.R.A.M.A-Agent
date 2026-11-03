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


def _place_of(bssid: str, aps: list[dict] | None = None) -> dict | None:
    """The saved place for this spot as {label, lat?, lon?}: the connected Wi-Fi, else any saved place whose Wi-Fi
    surroundings (every access point seen when it was pinned) overlap what the laptop sees now (2+ in common, or
    the one that was strongest there). Older saves were a bare label string."""
    places = _places()
    v = places.get(bssid)
    if v is None and aps:
        seen = {a["macAddress"] for a in aps}
        best, hits = None, 0
        for entry in places.values():
            if not isinstance(entry, dict) or not entry.get("aps"):
                continue
            common = len(seen & set(entry["aps"]))
            if common > hits and (common >= 2 or entry["aps"][0] in seen):
                best, hits = entry, common
        v = best
    if v is None:
        return None
    return {"label": v} if isinstance(v, str) else v


def geocode(query: str) -> tuple[float, float] | None:
    """Forward-geocode an address to (lat, lon) via OpenStreetMap (free)."""
    import urllib.parse
    url = f"https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q={urllib.parse.quote(query)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=12) as r:
            d = json.load(r)
        return (float(d[0]["lat"]), float(d[0]["lon"])) if d else None
    except Exception as e:
        log.info("forward geocode failed: %s", e)
        return None


def label_here(label: str, lat: float | None = None, lon: float | None = None) -> str:
    """Remember the current Wi-Fi as a named place. If lat/lon are given (or the label geocodes to a place),
    /where reports that exact spot and map pin whenever the laptop is on this Wi-Fi."""
    cur = scan()
    if not cur["bssid"]:
        return "I'm not on Wi-Fi right now, so I can't label this spot. Connect to the Wi-Fi here and try again."
    label = label.strip()[:60] or "home"
    # only geocode a label that looks like a place (2+ words), never a generic "home"/"office" (which geocodes wrong)
    if lat is None and len(label.split()) >= 2 and (g := geocode(f"{label}, Nepal" if "nepal" not in label.lower() else label)):
        lat, lon = g
    entry: dict = {"label": label,  # every access point seen here, strongest first: the spot is found again by its
                   "aps": [a["macAddress"] for a in sorted(cur["aps"], key=lambda a: -a["signalStrength"])][:12]}
    if lat is not None and lon is not None:  # (Wi-Fi surroundings, even on another network or after a router swap)
        entry["lat"], entry["lon"] = round(float(lat), 6), round(float(lon), 6)
    else:
        store.kv_set(_PIN_WAIT, json.dumps({"label": label, "at": time.time()}))  # the phone's GPS pins it exactly
    places = _places()
    places[cur["bssid"]] = entry
    store.kv_set(_PLACES_KEY, json.dumps(places))
    _cache.clear()  # so /where reflects the new label right away
    if "lat" in entry:
        return (f"Saved: when the laptop sees the Wi-Fi around here (“{cur['ssid']}” and {len(entry['aps']) - 1} "
                f"more) I'll say it's at “{label}” ({entry['lat']}, {entry['lon']}).")
    return (f"Saved “{label}” for the Wi-Fi around here. For the EXACT spot, send your phone's location now "
            f"(📎 → Location → Send my current location) within 10 minutes: its GPS becomes the laptop's pin.")


_PIN_WAIT = "geolocate_pin_wait"


def pin_from_phone(lat: float, lon: float, accuracy: int = 0) -> str | None:
    """A phone location right after '/here <name>': that GPS point becomes the pinned spot (the free Wi-Fi
    database didn't know this area: /where said 'Nepalgunj ±25 km' from the internet provider). None if no pin waits."""
    try:
        wait = json.loads(store.kv_get(_PIN_WAIT, "") or "{}")
    except ValueError:
        wait = {}
    if not wait or time.time() - float(wait.get("at", 0)) > 600:
        return None
    store.kv_set(_PIN_WAIT, "{}")
    out = label_here(wait["label"], lat, lon)
    return out + (f" Phone GPS accuracy ±{accuracy} m." if accuracy else "")


def forget_here() -> str:
    cur = scan()
    places = _places()
    if cur["bssid"] in places:
        lbl = places.pop(cur["bssid"])
        store.kv_set(_PLACES_KEY, json.dumps(places))
        _cache.clear()
        return f"Forgot the “{lbl}” label for this Wi-Fi."
    return "This Wi-Fi isn't labelled."


BROWSER_KEY = "browser_gps_fix"
BROWSER_FRESH_S = 900  # a browser GPS fix counts as "current" for 15 min


def set_browser_fix(lat: float, lon: float, accuracy: float = 0.0) -> None:
    """Store an accurate position the dashboard got from the browser's Geolocation API (Google-backed: real GPS/
    Wi-Fi, updates as the laptop moves). Shared across processes (the API writes it, Telegram reads it)."""
    store.kv_set(BROWSER_KEY, json.dumps({"lat": round(float(lat), 6), "lon": round(float(lon), 6),
                                          "accuracy": int(accuracy or 0), "at": time.time()}))
    _cache.clear()


def browser_fix() -> dict | None:
    try:
        d = json.loads(store.kv_get(BROWSER_KEY, "") or "{}")
    except ValueError:
        return None
    if not d or time.time() - d.get("at", 0) > BROWSER_FRESH_S:
        return None
    return d


def locate(use_cache: bool = True) -> dict:
    """Best location now: {lat, lon, accuracy, source, ssid, known, place, map, osm}. {} if nothing worked.
    Priority: a fresh browser GPS fix (accurate, moves with the laptop) -> Wi-Fi geolocation -> a pinned spot -> IP."""
    now = time.time()
    cur = scan()
    if use_cache and _cache and now - _cache.get("at", 0) < _CACHE_S and _cache.get("bssid") == cur["bssid"]:
        return _cache["loc"]

    def finish(lat, lon, accuracy, source, place=None, known=""):
        g, osm = maps(lat, lon)
        out = {"lat": lat, "lon": lon, "accuracy": int(accuracy), "source": source, "ssid": cur["ssid"],
               "known": known, "place": place if place is not None else place_name(lat, lon, accuracy),
               "map": g, "osm": osm}
        _cache.update(at=now, bssid=cur["bssid"], loc=out)
        return out

    bf = browser_fix()  # the real, dynamic one (updates as the laptop moves)
    if bf:
        return finish(bf["lat"], bf["lon"], bf["accuracy"] or 30, "gps")
    known = _place_of(cur["bssid"], cur["aps"])  # a spot you pinned (e.g. home): trusted over beacondb's Nepal data
    if known and "lat" in known:
        return finish(known["lat"], known["lon"], 30, "known", place=known["label"], known=known["label"])
    geo = _geolocate(cur["aps"])  # Wi-Fi/IP positioning (the only dynamic option on an unpinned network, coarse in Nepal)
    if geo:
        return finish(geo["lat"], geo["lon"], geo["accuracy"], geo["source"],
                      known=(known or {}).get("label", ""))
    return {}


def where_text() -> str:
    """A ready-to-send location report for Telegram (0 tokens)."""
    loc = locate()
    if not loc:
        ssid = scan()["ssid"]
        return ("I couldn't fix the location (offline, or no Wi-Fi to scan)."
                + (f"\nWi-Fi: {ssid}" if ssid else ""))
    lines = ["Laptop location:"]
    if loc["known"]:
        lines.append(f"At: {loc['known']}" + (" (your saved spot)" if loc["source"] == "known" else ""))
    if loc["source"] != "known":  # pinned spot needs no coarse guess; otherwise show the Wi-Fi/IP area
        around = loc["place"] or "unknown area"
        acc = f" (±{loc['accuracy'] // 1000} km)" if loc["accuracy"] >= 1500 else (
            f" (±{loc['accuracy']} m)" if loc["accuracy"] else "")
        via = {"gps": "GPS", "wi-fi": "Wi-Fi"}.get(loc["source"], "IP")
        lead = "Near" if loc["source"] == "gps" else "Around"
        lines.append(f"{lead} {around}{acc}, via {via}")
        if loc["source"] == "ip":  # honest: this is the internet provider's area, not where the laptop is
            lines.append("⚠️ Not the laptop's real spot: the Wi-Fi around it isn't in the free location database, so "
                         "this is only your internet provider's city. For the exact spot: /here home, then share "
                         "your phone's location once (that place is then found by its Wi-Fi).")
    if loc["ssid"]:
        lines.append(f"Wi-Fi: {loc['ssid']}")
    lines.append(f"Map: {loc['map']}")
    return "\n".join(lines)
