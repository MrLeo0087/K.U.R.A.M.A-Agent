"""power_mode: switch how much of KURAMA runs (full / best AI / normal / basic / low RAM / laptop only / no AI) (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="usage", safety="safe", description="Switch KURAMA's power mode to save RAM (full, smart, normal, basic, "
      "lowram, laptop, noai) or tell the current one.")
def power_mode(mode: Literal["status", "full", "smart", "normal", "basic", "lowram", "laptop", "noai"] = "status") -> str:
    """KURAMA power mode.

    Args:
        mode: "status" = say the current mode; full = everything on; smart = best AI for everything; normal = the usual KURAMA;
            basic = important helpers only; lowram = laptop busy (small screen, small AI); laptop = no background
            helpers; noai = 0 tokens, built-in commands only.
    """
    from jarvis.core import modes

    if mode and mode != "status":
        modes.set_mode(mode)
    st = modes.current()
    p = modes.PRESETS.get(st["mode"])
    head = f"{modes.name(st)} mode {'on' if mode != 'status' else 'is on'}, about {modes.estimate(st)} MB."
    return f"{head} {p['desc']}" if p else head + " (your own mix of switches)"
