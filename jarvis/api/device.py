"""This laptop at a glance, for the dashboard's "This laptop" card (GET /api/v1/device).

Mostly /sys and /proc reads; nmcli and pactl only where nothing else knows (Wi-Fi name, volume). Cached
for 15 s, and the UI asks only while the dashboard is visible, so it costs nothing while you work.
"""
from __future__ import annotations

import platform
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import psutil

TTL_S = 15
_cache: dict = {"t": 0.0, "data": None}
_lock = threading.Lock()
_static: dict | None = None


def _read(path: Path | str) -> str:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


def _cmd(argv: list[str], timeout: float = 2.0) -> str:
    if not shutil.which(argv[0]):
        return ""
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _model() -> str:
    dmi = Path("/sys/class/dmi/id")
    vendor, name, version = (_read(dmi / f) for f in ("sys_vendor", "product_name", "product_version"))
    if vendor.lower() == "lenovo" and version and "thinkpad" not in name.lower():
        name = version  # Lenovo keeps the marketing name in product_version
    vendor = vendor.replace("Inc.", "").replace("Corporation", "").strip()
    junk = ("to be filled", "system product name", "default string")
    if any(j in name.lower() for j in junk):
        name = ""
    if vendor and name.lower().startswith(vendor.split()[0].lower()):
        return name
    return f"{vendor} {name}".strip()


def _os() -> str:
    for line in _read("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip('"')
    return platform.system()


def static() -> dict:
    """Things that don't change while the laptop runs (read once)."""
    global _static
    if _static is None:
        _static = {"model": _model(), "os": _os(), "kernel": platform.release(), "host": socket.gethostname()}
    return _static


def wifi() -> dict | None:
    out = _cmd(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi", "list", "--rescan", "no"])
    for line in out.splitlines():
        parts = line.replace("\\:", "\0").split(":")
        if len(parts) >= 3 and parts[0] == "yes":
            return {"ssid": parts[1].replace("\0", ":"), "signal": int(parts[2]) if parts[2].isdigit() else None}
    return None


def local_ip() -> str:
    iface = ""
    for line in _read("/proc/net/route").splitlines()[1:]:
        f = line.split()
        if len(f) > 3 and f[1] == "00000000" and int(f[3], 16) & 2:  # default route, gateway flag
            iface = f[0]
            break
    for a in psutil.net_if_addrs().get(iface, []):
        if a.family == socket.AF_INET:
            return a.address
    return ""


def volume() -> dict | None:
    out = _cmd(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
    if "%" not in out:
        return None
    pct = int(out.split("%", 1)[0].rsplit(None, 1)[-1].lstrip("/"))
    muted = "yes" in _cmd(["pactl", "get-sink-mute", "@DEFAULT_SINK@"]).lower()
    return {"percent": pct, "muted": muted}


def brightness() -> int | None:
    for d in sorted(Path("/sys/class/backlight").glob("*")):
        cur, top = _read(d / "brightness"), _read(d / "max_brightness")
        if cur.isdigit() and top.isdigit() and int(top):
            return round(100 * int(cur) / int(top))
    return None


def battery_health() -> dict | None:
    for d in sorted(Path("/sys/class/power_supply").glob("BAT*")):
        for full, design in (("energy_full", "energy_full_design"), ("charge_full", "charge_full_design")):
            f, dz = _read(d / full), _read(d / design)
            if f.isdigit() and dz.isdigit() and int(dz):
                cycles = _read(d / "cycle_count")
                return {"health": min(100, round(100 * int(f) / int(dz))),
                        "cycles": int(cycles) if cycles.isdigit() and int(cycles) > 0 else None}
    return None


def next_reminder() -> dict | None:
    try:
        from jarvis.core import store
        now = time.time()
        rows = [r for r in store.schedules_list(limit=20) if (r.get("next_run") or 0) > now and r.get("kind") != "command"]
    except Exception:
        return None
    if not rows:
        return None
    r = min(rows, key=lambda r: r["next_run"])
    return {"text": r["text"][:60], "at": r["next_run"]}


def collect() -> dict:
    return {**static(), "uptime_s": int(time.time() - psutil.boot_time()), "wifi": wifi(), "ip": local_ip(),
            "volume": volume(), "brightness": brightness(), "battery": battery_health(), "next": next_reminder()}


def info() -> dict:
    with _lock:
        if _cache["data"] is None or time.time() - _cache["t"] > TTL_S:
            _cache["data"], _cache["t"] = collect(), time.time()
        return _cache["data"]
