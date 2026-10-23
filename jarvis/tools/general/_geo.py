"""Shared helpers for weather/time tools (not a tool): a tiny TTL cache, JSON GET with a timeout,
and the free Open-Meteo geocoder (no API key) with spelling fallbacks ("Nepalganj" -> Nepalgunj)."""
from __future__ import annotations

import re
import threading
import time
from typing import Any

from jarvis.core import config

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"


class TTLCache:
    """Thread-safe in-memory cache: get() returns None once an entry is older than ttl seconds."""

    def __init__(self, ttl: float, max_items: int = 256):
        self.ttl, self.max_items = ttl, max_items
        self._data: dict[Any, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: Any) -> Any:
        with self._lock:
            hit = self._data.get(key)
            if hit and time.monotonic() - hit[0] < self.ttl:
                return hit[1]
            self._data.pop(key, None)
            return None

    def set(self, key: Any, value: Any) -> None:
        with self._lock:
            if len(self._data) >= self.max_items:
                self._data.pop(next(iter(self._data)))
            self._data[key] = (time.monotonic(), value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


_geo_cache = TTLCache(config.GEO_CACHE_S)


_client = None


def get_json(url: str, params: dict) -> dict:
    """GET url and parse JSON via one pooled keep-alive client (patched in tests: no network)."""
    global _client
    if _client is None:
        import httpx  # lazy: only weather/time-by-place need it

        _client = httpx.Client(timeout=config.HTTP_TIMEOUT_S, follow_redirects=True)
    r = _client.get(url, params=params)
    r.raise_for_status()
    return r.json()


def _clean(place: str) -> str:
    p = re.sub(r"[?!.]+$", "", place.strip().strip("\"'"))
    p = re.sub(r"^(?:the\s+)", "", p, flags=re.I)
    return re.sub(r"\s+(?:city|town|district)$", "", p, flags=re.I).strip()


def _variants(place: str) -> list[str]:
    out = [place]
    low = place.lower()
    for a, b in (("ganj", "gunj"), ("gunj", "ganj"), ("pur", "pura"), ("mandu", "mandoo")):
        if a in low:
            out.append(re.sub(a, b, place, flags=re.I))
    if "," in place:  # "Paris, France" -> "Paris"
        out.append(place.split(",")[0].strip())
    return list(dict.fromkeys(v for v in out if v))


def geocode(place: str) -> dict | None:
    """{name, country, admin1, lat, lon, timezone} for the best match, or None if nothing found."""
    place = _clean(place)
    if not place:
        return None
    key = place.lower()
    cached = _geo_cache.get(key)
    if cached is not None:
        return cached or None
    found: dict | None = None
    for q in _variants(place):
        data = get_json(GEOCODE_URL, {"name": q, "count": 1, "format": "json"})
        res = (data or {}).get("results") or []
        if res:
            r = res[0]
            found = {"name": r.get("name") or q, "country": r.get("country") or "",
                     "admin1": r.get("admin1") or "", "lat": r["latitude"], "lon": r["longitude"],
                     "timezone": r.get("timezone") or ""}
            break
    _geo_cache.set(key, found or {})
    return found


def label(geo: dict) -> str:
    name, country = geo.get("name", ""), geo.get("country", "")
    return name if not country or country == name else f"{name}, {country}"
