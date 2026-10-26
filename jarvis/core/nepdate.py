"""Bikram Sambat (BS) <-> Gregorian (AD) date helper.

Thin wrapper over the pure-Python `nepali_datetime` package (no heavy deps). Lazy
imported so it costs nothing until a date is actually asked for.
"""
from __future__ import annotations

from datetime import date as _date

_EN_WEEKDAY = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _bs(d: _date):
    import nepali_datetime as nd  # lazy: pure python, ~no startup cost until used
    return nd.date.from_datetime_date(d)


def week_of_year(d: _date) -> int:
    """ISO week number (1-53)."""
    return d.isocalendar()[1]


def ad_phrase(d: _date | None = None) -> str:
    """English (Gregorian) date, e.g. 'Monday, 26 October 2026'."""
    d = d or _date.today()
    return d.strftime("%A, %d %B %Y").replace(" 0", " ")


def bs_phrase(d: _date | None = None, nepali_script: bool = False) -> str:
    """Bikram Sambat date with weekday.

    nepali_script=False -> 'Monday, Kartik 9, 2083'
    nepali_script=True  -> 'सोमबार, कार्तिक ९, २०८३'
    """
    d = d or _date.today()
    b = _bs(d)
    if nepali_script:
        return b.strftime("%G, %N %D, %K")
    day = b.strftime("%d").lstrip("0") or "0"
    return f"{d.strftime('%A')}, {b.strftime('%B')} {day}, {b.strftime('%Y')}"
