"""get_time: current date and time, locally or in any city/country (geocoded timezone; safe)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jarvis.core.registry import tool
from jarvis.tools.general import _geo

FMT = "%A, %d %B %Y, %H:%M (UTC%z)"


def _say(dt: datetime, where: str = "") -> str:
    """A ready-to-speak sentence (the LLM or the fast path can pass it on as is)."""
    h12 = f"{dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"
    return f"It's {h12} on {dt.strftime('%A, %d %B %Y')}{' in ' + where if where else ''}."


@tool(group="general", safety="safe", description="Get the current date and time, locally or in any city or country.")
def get_time(place: str = "") -> str:
    """Current date and time.

    Args:
        place: City or country for world time; empty = local time.
    """
    if not (place or "").strip():
        return _say(datetime.now().astimezone())
    geo = _geo.geocode(place)
    if not geo or not geo.get("timezone"):
        return f"error: couldn't find a place called {place.strip()!r}"
    try:
        tz = ZoneInfo(geo["timezone"])
    except ZoneInfoNotFoundError:
        return f"error: unknown timezone {geo['timezone']!r}"
    return _say(datetime.now(tz), _geo.label(geo))
