"""location_history: show where the laptop (or phone) has been — a text summary and a map opened in the browser (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import locationlog
from jarvis.core.registry import tool
from jarvis.tools.general.open_url import _open


@tool(group="system", safety="safe",
      description="Show the laptop's (or phone's) location history: where it's been over the last N hours, as a "
                  "summary plus a map opened in the browser. The phone's trail comes from live location you share "
                  "with KURAMA on Telegram.")
def location_history(device: Literal["laptop", "phone"] = "laptop", hours: int = 24, open_map: bool = True) -> str:
    """Location history / movement trail.

    Args:
        device: laptop or phone.
        hours: how far back to look (default 24).
        open_map: also open a map of the trail in the browser.
    """
    hours = max(1, min(24 * 30, int(hours or 24)))
    text = locationlog.summary(device, hours)
    if open_map:
        path = locationlog.map_html(device, hours)
        if path is not None:
            try:
                _open(path.as_uri())
                return f"{text}\n(Map opened in your browser.)"
            except Exception:
                return f"{text}\n(Map saved: {path})"
    return text
