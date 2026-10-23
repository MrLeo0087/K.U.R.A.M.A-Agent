"""battery_status: battery percentage, charging state, time left and health (upower). Safe."""
from __future__ import annotations

import re

from jarvis.core.registry import tool
from jarvis.tools.general import _sys


def parse(text: str) -> dict:
    """upower -i output -> {key: value} (keys lower-case, e.g. 'percentage', 'time to empty')."""
    out = {}
    for line in text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip().lower()] = v.strip().strip("'")
    return out


def summary(info: dict) -> str:
    pct = info.get("percentage", "?").replace(".0000", "")
    state = info.get("state", "unknown").replace("-", " ")
    parts = [f"Battery {pct}, {state}"]
    if info.get("time to empty") and state == "discharging":
        parts.append(f"{info['time to empty']} left")
    if info.get("time to full") and state == "charging":
        parts.append(f"full in {info['time to full']}")
    if cap := info.get("capacity"):
        m = re.match(r"([\d.]+)", cap)
        if m:
            parts.append(f"health {float(m.group(1)):.0f}% of design capacity")
    if cyc := info.get("charge-cycles"):
        if cyc.isdigit() and int(cyc) > 0:
            parts.append(f"{cyc} charge cycles")
    return ", ".join(parts) + "."


@tool(group="power", safety="safe", description="Battery level, charging state, time remaining and battery health.")
def battery_status() -> str:
    """Report the laptop battery."""
    if not _sys.which("upower"):
        return "error: upower not found: sudo apt install upower"
    try:
        devices = [d.strip() for d in _sys.run(["upower", "-e"]).splitlines() if "battery_" in d]
        for dev in devices:
            info = parse(_sys.run(["upower", "-i", dev]))
            if info.get("present", "yes") == "yes" and info.get("power supply", "yes") == "yes":
                return summary(info)
    except _sys.SysError as e:
        return f"error: could not read the battery ({e})"
    return "No battery found: this computer runs on mains power."
