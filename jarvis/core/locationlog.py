"""Location history for the laptop and the phone (0 chat tokens).

Laptop: a worker records the laptop's position every config.LOCATION_LOG_INTERVAL_S (geolocate; Wi-Fi/IP, so
city-level unless on a labelled Wi-Fi). "Lost mode" (kv) logs more often and sends each new fix to Telegram.

Phone: KURAMA can't run on the phone, so the phone's trail comes from location you share with the Telegram bot —
Telegram "live location" (updates for 15 min–8 h) or a one-off location pin. The bot logs each update here.

A trail is viewed as a self-contained Leaflet map (OpenStreetMap tiles, free) saved under data/outputs/, and
summarised as text for Telegram. Points closer together than LOCATION_MIN_MOVE_M are treated as "same spot".
"""
from __future__ import annotations

import html
import logging
import math
import time
from pathlib import Path

from jarvis.core import config, store

log = logging.getLogger(__name__)

LOST_KEY = "location_lost_mode"  # "laptop" entries, kv value "1"


def _lost_key(device: str) -> str:
    return f"{LOST_KEY}:{device}"


def lost_mode(device: str = "laptop") -> bool:
    """On = the kv holds the time it was switched on. It switches itself off after LOCATION_LOST_MAX_H (a
    forgotten /track sent the owner's location every 15 min for a day); an old '1' (no time) counts as expired."""
    v = store.kv_get(_lost_key(device), "0") or "0"
    if v == "0":
        return False
    try:
        since = float(v) if v != "1" else 0.0
    except ValueError:
        since = 0.0
    if time.time() - since < config.LOCATION_LOST_MAX_H * 3600:
        return True
    store.kv_set(_lost_key(device), "0")
    log.info("lost mode for the %s ended by itself", device)
    if since and config.TELEGRAM_BOT_TOKEN:
        try:
            from jarvis.core import notify
            notify.notify(f"📍 Lost mode ended ({device})", f"It switched itself off after "
                          f"{config.LOCATION_LOST_MAX_H:g} h. Send /track to start it again.",
                          level="info", source="location", telegram=True, desktop=False)
        except Exception as e:
            log.warning("lost-mode end notify failed: %s", e)
    return False


def set_lost(device: str, on: bool) -> str:
    was = lost_mode(device)
    store.kv_set(_lost_key(device), str(time.time()) if on else "0")
    if on:
        record_laptop(force=True) if device == "laptop" else None
        return (f"Lost mode on for the {device}: I'll message your phone its location on each new fix for the next "
                f"{config.LOCATION_LOST_MAX_H:g} h. Stop it with 'stop tracking the {device}' or /track off.")
    return (f"Lost mode off for the {device}: no more location messages." if was
            else f"Lost mode was already off for the {device}.")


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def record(device: str, lat: float, lon: float, accuracy: int = 0, source: str = "", place: str = "",
           ts: float | None = None, notify_lost: bool = True) -> dict | None:
    """Log one point. Skips a point that barely moved from the last one (keeps the trail small)."""
    last = store.location_last(device)
    moved = _haversine_m((last["lat"], last["lon"]), (lat, lon)) if last and last["lat"] is not None else 1e9
    if last and moved < config.LOCATION_MIN_MOVE_M and (ts or time.time()) - last["ts"] < config.LOCATION_LOG_INTERVAL_S * 4:
        return None  # same place, recent: don't pile up points
    store.location_add(device, lat, lon, accuracy, source, place, ts)
    point = {"device": device, "lat": lat, "lon": lon, "accuracy": accuracy, "source": source,
             "place": place, "ts": ts or time.time(), "moved_m": None if last is None else moved}
    if notify_lost and lost_mode(device) and config.TELEGRAM_BOT_TOKEN:
        _notify_fix(point)
    return point


def _notify_fix(p: dict) -> None:
    from jarvis.core import notify
    mapurl = f"https://maps.google.com/?q={p['lat']:.5f},{p['lon']:.5f}"
    where = p["place"] or "unknown area"
    moved = f" (moved {int(p['moved_m'])} m)" if p.get("moved_m") and p["moved_m"] < 1e8 else ""
    try:
        notify.notify(f"📍 {p['device'].title()} location", f"{where}{moved}\n{mapurl}", level="info",
                      source="location", telegram=True, desktop=False)
    except Exception as e:
        log.warning("lost-mode notify failed: %s", e)


def record_laptop(force: bool = False) -> dict | None:
    from jarvis.core import geolocate
    loc = geolocate.locate(use_cache=not force)
    if not loc:
        return None
    place = loc.get("known") or loc.get("place") or ""
    return record("laptop", loc["lat"], loc["lon"], loc.get("accuracy", 0), loc.get("source", ""), place)


def record_phone(lat: float, lon: float, accuracy: int = 0, live: bool = False) -> dict | None:
    """A location the phone shared with the Telegram bot (live update or a one-off pin)."""
    place = ""
    try:
        from jarvis.core import geolocate
        place = geolocate.place_name(lat, lon, accuracy)
    except Exception:
        place = ""
    return record("phone", lat, lon, accuracy, "live" if live else "shared", place)


# --- viewing ---
def _bounds(pts: list[dict]) -> tuple[float, float, float, float]:
    lats = [p["lat"] for p in pts]
    lons = [p["lon"] for p in pts]
    return min(lats), min(lons), max(lats), max(lons)


def trail(device: str, hours: float = 24) -> list[dict]:
    return store.locations_since(device, time.time() - hours * 3600)


def _fmt_span(pts: list[dict]) -> str:
    dur = pts[-1]["ts"] - pts[0]["ts"]
    h = dur / 3600
    return f"{h:.0f} h" if h >= 1 else f"{dur / 60:.0f} min"


def summary(device: str, hours: float = 24) -> str:
    pts = trail(device, hours)
    if not pts:
        return (f"No {device} location history in the last {hours:.0f} h."
                + (" Share your live location with me on Telegram to build the phone's trail." if device == "phone"
                   else " I'll log it as the laptop moves."))
    total_m = sum(_haversine_m((pts[i - 1]["lat"], pts[i - 1]["lon"]), (pts[i]["lat"], pts[i]["lon"]))
                  for i in range(1, len(pts)))
    places, seen = [], set()
    for p in pts:
        name = p["place"] or f"{p['lat']:.3f},{p['lon']:.3f}"
        if name not in seen:
            seen.add(name)
            places.append(name)
    last = pts[-1]
    dist = f"{total_m / 1000:.1f} km" if total_m >= 1000 else f"{total_m:.0f} m"
    lines = [f"📍 {device.title()} history · last {_fmt_span(pts)} · {len(pts)} points",
             f"Distance moved: {dist}",
             "Places: " + ", ".join(places[:6]) + (" …" if len(places) > 6 else ""),
             f"Now: {last['place'] or 'unknown'} — https://maps.google.com/?q={last['lat']:.5f},{last['lon']:.5f}"]
    return "\n".join(lines)


def map_html(device: str, hours: float = 24) -> Path | None:
    """A standalone Leaflet map of the trail, saved under data/outputs/maps/. Returns the path."""
    pts = trail(device, hours)
    if not pts:
        return None
    out_dir = Path(config.OUTPUTS_DIR) / "maps"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{device}-trail-{time.strftime('%Y%m%d-%H%M%S')}.html"
    coords = [[round(p["lat"], 6), round(p["lon"], 6)] for p in pts]
    markers = [{"ll": [round(p["lat"], 6), round(p["lon"], 6)],
                "t": html.escape(f"{time.strftime('%d %b %H:%M', time.localtime(p['ts']))} · {p['place'] or ''}")}
               for p in pts]
    s, w, n, e = _bounds(pts)
    import json as _json
    page = _MAP_TEMPLATE.replace("__TITLE__", html.escape(f"{device.title()} location history")) \
        .replace("__LINE__", _json.dumps(coords)).replace("__MARKERS__", _json.dumps(markers)) \
        .replace("__BOUNDS__", _json.dumps([[s, w], [n, e]])).replace("__DEVICE__", html.escape(device))
    out.write_text(page, encoding="utf-8")
    return out


_MAP_TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><title>__TITLE__</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#map{height:100%;margin:0}#t{position:absolute;z-index:1000;top:8px;left:50px;background:#111;
color:#fff;padding:6px 12px;border-radius:8px;font:14px system-ui;opacity:.85}</style></head>
<body><div id="t">__TITLE__</div><div id="map"></div><script>
var map=L.map('map');L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
{subdomains:'abcd',maxZoom:20,attribution:'© OpenStreetMap, © CARTO'}).addTo(map);
var line=__LINE__, marks=__MARKERS__, bounds=__BOUNDS__;
L.polyline(line,{color:'#ff7a1a',weight:4,opacity:.8}).addTo(map);
marks.forEach(function(m,i){var c=i===marks.length-1?'#ff3b30':(i===0?'#2ec27e':'#6fb7ff');
L.circleMarker(m.ll,{radius:i===marks.length-1?8:5,color:c,fillColor:c,fillOpacity:.9}).addTo(map).bindPopup(m.t);});
map.fitBounds(bounds,{padding:[40,40],maxZoom:17});
</script></body></html>"""
