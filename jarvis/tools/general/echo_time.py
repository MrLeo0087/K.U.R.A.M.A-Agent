"""get_time: current date and time, locally or in any city/country (geocoded timezone; safe)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.core.registry import tool
from jarvis.tools.general import _geo

FMT = "%A, %d %B %Y, %H:%M (UTC%z)"


@tool(group="general", safety="safe", description="Get the current date and time, locally or in any city or country.")
def get_time(place: str = "") -> str:
    """Current date and time.

    Args:
        place: City or country for world time; empty = local time.
    """
    if not (place or "").strip():
        return datetime.now().astimezone().strftime(FMT)
    geo = _geo.geocode(place)
    if not geo or not geo.get("timezone"):
        return f"error: couldn't find a place called {place.strip()!r}"
    try:
        tz = ZoneInfo(geo["timezone"])
    except ZoneInfoNotFoundError:
        return f"error: unknown timezone {geo['timezone']!r}"
    return f"{_geo.label(geo)}: {datetime.now(tz).strftime(FMT)}"
