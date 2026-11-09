"""Laptop health, quietly (plan 11-09 phase 3): checked every timemachine tick (10 min), a message ONLY when it
needs you, each kind at most once a day / week. 0 tokens, a few file reads.

- Disk trend: free space on the home disk, one sample a day (30 kept). Falling so fast that it is full within
  HEALTH_DISK_WARN_DAYS -> "full in ~N days" with buttons (what fills it, clean caches). Once a week.
- Battery care: plugged in at 100% for HEALTH_FULL_PLUGGED_H hours -> "unplug" tip (wear; this laptop has no charge
  limit setting). Once a day. Battery health (full / design capacity) checked monthly: a drop of 5+ points -> told.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from jarvis.core import notify, store

DISK_KEY, BATT_KEY, SENT_KEY = "health_disk", "health_batt", "health_sent"
DISK_WARN_DAYS = 21
FULL_PLUGGED_H = 3.0
BAT = Path("/sys/class/power_supply")


def _kv(key: str, default):
    try:
        v = json.loads(store.kv_get(key) or "null")
        return v if isinstance(v, type(default)) else default
    except (ValueError, TypeError):
        return default


def _once(kind: str, every_s: float, now: float) -> bool:
    """True (and remembered) when `kind` was not told within every_s."""
    sent = _kv(SENT_KEY, {})
    if now - float(sent.get(kind) or 0) < every_s:
        return False
    sent[kind] = now
    store.kv_set(SENT_KEY, json.dumps(sent))
    return True


def battery_health() -> tuple[int, int] | None:
    """(health %, charge cycles) from sysfs, or None (no battery)."""
    for b in sorted(BAT.glob("BAT*")):
        def read(n: str) -> int:
            try:
                return int((b / n).read_text().strip())
            except (OSError, ValueError):
                return 0
        full, design = read("energy_full") or read("charge_full"), read("energy_full_design") or read("charge_full_design")
        if full and design:
            return round(100 * full / design), read("cycle_count")
    return None


def disk_check(now: float, free: int | None = None, total: int | None = None) -> str | None:
    if free is None:
        u = shutil.disk_usage(Path.home())
        free, total = u.free, u.total
    day = int(now // 86400)
    rows = [r for r in _kv(DISK_KEY, []) if isinstance(r, list) and len(r) == 2]
    if not rows or rows[-1][0] != day:
        rows = (rows + [[day, free]])[-30:]
        store.kv_set(DISK_KEY, json.dumps(rows))
    old = next((r for r in rows if day - r[0] >= 7), None)
    if old is None:
        return None
    per_day = (old[1] - free) / max(1, day - old[0])
    if per_day <= 0 or free / per_day > DISK_WARN_DAYS or not _once("disk", 7 * 86400, now):
        return None
    gb = 1e9
    return (f"Disk: {free / gb:.0f} GB free of {(total or 0) / gb:.0f} GB, filling ~{per_day / gb:.1f} GB a day "
            f"-> full in about {free / per_day:.0f} days.")


def battery_check(now: float, plugged: bool | None = None, percent: float | None = None) -> str | None:
    if plugged is None:
        try:
            import psutil
            b = psutil.sensors_battery()
        except Exception:  # noqa: BLE001
            b = None
        if b is None:
            return None
        plugged, percent = b.power_plugged, b.percent
    st = _kv(BATT_KEY, {})
    msg = None
    if plugged and (percent or 0) >= 99:
        st.setdefault("full_since", now)
        if now - st["full_since"] >= FULL_PLUGGED_H * 3600 and _once("battery_full", 86400, now):
            h = battery_health()
            msg = (f"Battery: plugged in at 100% for {(now - st['full_since']) / 3600:.0f} h. Unplug it now and then "
                   f"(below ~80% is kinder)" + (f"; its health is {h[0]}% after {h[1]} charge cycles." if h else "."))
    else:
        st.pop("full_since", None)
    if now - float(st.get("checked") or 0) >= 30 * 86400 and (h := battery_health()):
        if st.get("health") and h[0] <= st["health"] - 5:
            msg = f"Battery health fell from {st['health']}% to {h[0]}% this month ({h[1]} charge cycles)."
        st.update(checked=now, health=h[0])
    store.kv_set(BATT_KEY, json.dumps(st))
    return msg


def tick(now: float | None = None) -> list[str]:
    """Run by the timemachine worker. Returns what it told."""
    now = time.time() if now is None else now
    told = []
    if d := disk_check(now):
        notify.notify("💽 Disk filling up", d, level="warning", source="power",
                      markup={"inline_keyboard": [[{"text": "📊 What fills the disk", "callback_data": "/disk"}],
                                                  [{"text": "🧹 Clean caches", "callback_data": "/clean storage"}]]})
        told.append(d)
    if b := battery_check(now):
        notify.notify("🔋 Battery care", b, source="power")
        told.append(b)
    return told


def report() -> str:
    """'How is my laptop?' in three lines: battery health, disk and its trend, RAM now."""
    import psutil
    lines = []
    if h := battery_health():
        b = psutil.sensors_battery()
        lines.append(f"🔋 Battery health {h[0]}% of new ({h[1]} charge cycles)"
                     + (f", now {b.percent:.0f}% {'charging' if b.power_plugged else 'on battery'}" if b else "") + ".")
    u = shutil.disk_usage(Path.home())
    rows = [r for r in _kv(DISK_KEY, []) if isinstance(r, list) and len(r) == 2]
    trend = ""
    if len(rows) >= 2 and rows[-1][0] > rows[0][0]:
        per_day = (rows[0][1] - u.free) / max(1, rows[-1][0] - rows[0][0])
        trend = (f", using ~{per_day / 1e9:.1f} GB a day" if per_day > 0.05e9 else ", steady")
    lines.append(f"💽 Disk {u.free / 1e9:.0f} GB free of {u.total / 1e9:.0f} GB{trend}.")
    m = psutil.virtual_memory()
    lines.append(f"🧠 RAM {m.percent:.0f}% used ({m.available / 1e9:.1f} GB free).")
    return "\n".join(lines)
