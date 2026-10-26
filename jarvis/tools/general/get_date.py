"""get_date: today's full date and weekday, in Bikram Sambat (default) or Gregorian/AD (safe)."""
from __future__ import annotations

from datetime import date

from jarvis.core import nepdate
from jarvis.core.registry import tool


@tool(group="general", safety="safe",
      description="Today's full date and weekday. Use calendar='ad' only if the user asks for the English/AD/Gregorian date; otherwise the Nepali Bikram Sambat date.")
def get_date(calendar: str = "bs") -> str:
    """Today's date with the weekday.

    Args:
        calendar: 'bs' = Nepali Bikram Sambat (default), 'ad' = English/Gregorian.
    """
    d = date.today()
    week = nepdate.week_of_year(d)
    if (calendar or "bs").strip().lower() in ("ad", "en", "english", "gregorian", "international"):
        return f"Today is {nepdate.ad_phrase(d)} (week {week} of the year)."
    return (f"Today is {nepdate.bs_phrase(d)} in Bikram Sambat (week {week} of the year). "
            f"In English that's {nepdate.ad_phrase(d)}.")
