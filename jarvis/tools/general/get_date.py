"""get_date: today's date and weekday, in Bikram Sambat (default) or Gregorian/AD (safe)."""
from __future__ import annotations

from datetime import date

from jarvis.core import nepdate
from jarvis.core.registry import tool


@tool(group="general", safety="safe",
      description="Today's date and weekday. Nepali Bikram Sambat by default; calendar='ad' only if the user asks for English/AD; week=True only if they ask which week.")
def get_date(calendar: str = "bs", week: bool = False) -> str:
    """Today's date with the weekday.

    Args:
        calendar: 'bs' = Nepali Bikram Sambat (default), 'ad' = English/Gregorian.
        week: also say the week of the year (only when asked).
    """
    d = date.today()
    ad = (calendar or "bs").strip().lower() in ("ad", "en", "english", "gregorian", "international")
    text = nepdate.ad_phrase(d) if ad else nepdate.bs_phrase(d)
    tail = f", week {nepdate.week_of_year(d)} of the year" if week else ""
    return f"Today is {text}{tail}."
