"""weather: current weather and a short forecast for any place via Open-Meteo (free, no key; safe)."""
from __future__ import annotations

from datetime import date

from jarvis.core import config
from jarvis.core.registry import tool
from jarvis.tools.general import _geo

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_cache = _geo.TTLCache(config.WEATHER_CACHE_S)

# WMO weather interpretation codes -> words
CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "light showers",
    81: "showers", 82: "violent showers", 85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}


def describe(code) -> str:
    try:
        return CODES.get(int(code), "unknown conditions")
    except (TypeError, ValueError):
        return "unknown conditions"


def _r(x) -> str:
    try:
        return str(round(float(x)))
    except (TypeError, ValueError):
        return "?"


def _rain(p) -> str:
    """Main point about rain only: none / chance / likely."""
    if p is None:
        return ""
    p = round(float(p))
    if p < 20:
        return "no rain expected"
    return f"{p}% chance of rain" if p < 60 else f"rain likely ({p}%)"


def _format(where: str, data: dict, days: int) -> str:
    """Short, speakable summary: now + today's range + rain (feels-like/wind only if notable)."""
    cur, d = data.get("current") or {}, data.get("daily") or {}
    temp, feels = cur.get("temperature_2m"), cur.get("apparent_temperature")
    now = f"{where}: {_r(temp)}°C and {describe(cur.get('weather_code'))}"
    try:
        if abs(float(feels) - float(temp)) >= 4:
            now += f", feels like {_r(feels)}°C"
        if float(cur.get("wind_speed_10m") or 0) >= 30:
            now += ", windy"
    except (TypeError, ValueError):
        pass
    parts = [now + "."]
    lo, hi = d.get("temperature_2m_min") or [], d.get("temperature_2m_max") or []
    rain, codes, dates = (d.get("precipitation_probability_max") or [], d.get("weather_code") or [],
                          d.get("time") or [])
    for i in range(min(days, len(lo), len(hi))):
        r = _rain(rain[i] if i < len(rain) else None)
        if i == 0:
            parts.append(f"Today {_r(lo[0])} to {_r(hi[0])}°C" + (f", {r}." if r else "."))
            continue
        try:
            day = "Tomorrow" if i == 1 else date.fromisoformat(dates[i]).strftime("%A")
        except (IndexError, ValueError):
            day = f"Day {i + 1}"
        what = describe(codes[i]) if i < len(codes) else ""
        parts.append(f"{day} {_r(lo[i])} to {_r(hi[i])}°C, {what}" + (f", {r}." if r else "."))
    return " ".join(parts)


@tool(group="weather", safety="safe", description="Current weather and up to 3-day forecast for any city or country.")
def weather(place: str = "", days: int = 1) -> str:
    """Weather for a place.

    Args:
        place: City, town or country (any spelling); empty = the user's home place.
        days: 1 = today, 2 = include tomorrow, up to 3.
    """
    if not (place or "").strip():
        from jarvis.core import profile  # learned home city, else config.HOME_PLACE
        place = profile.home_place()
    place = place.strip()
    days = max(1, min(int(days or 1), 3))
    key = (place.lower(), days)
    if (hit := _cache.get(key)) is not None:
        return hit
    geo = _geo.geocode(place)
    if not geo:
        return f"error: couldn't find a place called {place!r}"
    data = _geo.get_json(FORECAST_URL, {
        "latitude": geo["lat"], "longitude": geo["lon"], "timezone": "auto", "forecast_days": days,
        "wind_speed_unit": "kmh",
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
    })
    out = _format(_geo.label(geo), data, days)
    _cache.set(key, out)
    return out
