"""get_time: current local date and time (safe)."""
from __future__ import annotations

from datetime import datetime

from jarvis.core.registry import tool


@tool(group="general", safety="safe", description="Get the current local date and time.")
def get_time() -> str:
    now = datetime.now().astimezone()
    return now.strftime("%A, %d %B %Y, %H:%M (UTC%z)")
