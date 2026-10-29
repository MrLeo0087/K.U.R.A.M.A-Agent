"""info: quick facts: time (anywhere), date (also Nepali calendar), weather, calculator/units, contacts, where the
phone or the laptop is (safe dispatcher)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.core._hub import Act, run

TABLE = {
    "time": Act("get_time", lambda a: {"place": a.get("query", "")}),
    "date": Act("get_date", lambda a: {"calendar": a.get("query", "")}),
    "weather": Act("weather", lambda a: {"place": a.get("query", ""), "days": a.get("days", 1)}),
    "calculate": Act("calculate", lambda a: {"expression": a.get("query")}),
    "contact": Act("contacts", lambda a: {"action": "find", "name": a.get("query")}),
    "save_contact": Act("contacts", lambda a: {"action": "add", "name": a.get("query"), "phone": a.get("value", "")}),
    "phone_location": Act("location_history", lambda a: {"device": "phone"}),
    "find_phone": Act("find_my_phone", lambda a: {"want": "open"}),
    "laptop_location": Act("laptop_guard", lambda a: {"action": "where"}),
}


@tool(group="core", safety="safe",
      description="Quick facts: time (any place), date (also Nepali BS calendar), weather (any place, days ahead), "
                  "calculate (math, %, units), contact (find a phone number), save_contact, phone_location, find_phone, "
                  "laptop_location.")
def info(action: Literal["time", "date", "weather", "calculate", "contact", "save_contact", "phone_location", "find_phone",
                         "laptop_location"], query: str = "", value: str = "", days: int = 1) -> str:
    """Quick facts.

    Args:
        action: What to look up.
        query: The place (time/weather), 'bs' for the Nepali date, the expression (calculate) or the person's name.
        value: save_contact: the phone number.
        days: weather: how many days ahead (1 = today).
    """
    return run(TABLE, {"action": action, "query": query, "value": value, "days": days})
