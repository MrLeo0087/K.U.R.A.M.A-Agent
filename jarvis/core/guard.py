"""Laptop guard: while armed, anyone who unlocks the laptop, types a wrong password or wakes it up gets their photo
taken with the webcam and sent to your Telegram, with where the laptop is (Wi-Fi name, public IP, rough location).
Arm it from the laptop or the phone ("guard my laptop" / /guard on); 0 tokens. The "guard" worker checks every 5 s
only while armed: the screen lock state (loginctl), password failures in the system journal, and wake-ups.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

from jarvis.core import config, notify, store


def armed() -> bool:
    return store.kv_get("guard_armed") == "1"


def arm(on: bool) -> str:
    store.kv_set("guard_armed", "1" if on else "0")
    store.kv_set("guard_since", str(time.time()))
    if on:
        cam = "the webcam will take a photo" if camera() else "no webcam found, so I'll just alert you"
        return (f"Laptop guard is on: if someone unlocks it, types a wrong password or wakes it up, {cam} and send "
                f"it to your Telegram with the laptop's location. Turn it off with 'guard off' (or /guard off).")
    return "Laptop guard is off."


def camera() -> str | None:
    cams = sorted(Path("/dev").glob("video*"))
    return str(cams[0]) if cams and shutil.which("ffmpeg") else None


def photo() -> Path | None:
    """One webcam frame (skipped frames let the camera adjust its exposure)."""
    dev = camera()
    if not dev:
        return None
    d = Path(config.DATA_DIR) / "guard"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"guard-{time.strftime('%Y%m%d-%H%M%S')}.jpg"
    try:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "v4l2", "-i", dev, "-vf", "select=gte(n\\,8)",
                        "-frames:v", "1", str(out)], capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return out if out.exists() and out.stat().st_size > 0 else None


def where() -> str:
    """Wi-Fi name, public IP and rough location (ip-api.com, free, no key)."""
    parts = []
    try:
        out = subprocess.run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"], capture_output=True, text=True,
                             timeout=8).stdout
        ssid = next((ln.split(":", 1)[1] for ln in out.splitlines() if ln.startswith("yes:")), "")
        parts.append(f"Wi-Fi: {ssid or 'not connected'}")
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        r = notify._http().get("http://ip-api.com/json/?fields=status,query,city,regionName,country,lat,lon,isp",
                               timeout=8)
        d = r.json()
        if d.get("status") == "success":
            parts.append(f"IP {d['query']} ({d.get('isp', '')}), around {d.get('city')}, {d.get('regionName')}, "
                         f"{d.get('country')}: https://maps.google.com/?q={d['lat']},{d['lon']}")
    except Exception:
        parts.append("public IP unknown (offline?)")
    return "\n".join(parts)


def alert(what: str) -> None:
    """Photo + location to Telegram (and the desktop alert log)."""
    pic = photo()
    text = f"{what} at {time.strftime('%H:%M:%S')}.\n{where()}"
    if pic is not None and config.TELEGRAM_BOT_TOKEN:
        from jarvis.tools.general.send_file_telegram import deliver
        try:
            deliver(pic, f"Laptop guard: {what}")
        except Exception:
            pass
    notify.notify("Laptop guard", text + (f"\nPhoto: {pic}" if pic else ""), level="warning", source="guard",
                  telegram=True, desktop=False)


def locked() -> bool | None:
    try:
        out = subprocess.run(["loginctl", "show-session", "auto", "-p", "LockedHint"], capture_output=True, text=True,
                             timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return "LockedHint=yes" in out if "LockedHint=" in out else None


AUTH_FAIL = re.compile(r"authentication failure|Authentication failure|password check failed|incorrect password",
                       re.I)


def auth_failures(since: float) -> int:
    """Wrong-password attempts (lock screen / login / sudo) logged since `since`."""
    try:
        out = subprocess.run(["journalctl", "-q", "--no-pager", "-o", "cat", f"--since=@{int(since)}",
                              "SYSLOG_IDENTIFIER=gdm-password", "+", "SYSLOG_IDENTIFIER=unix_chkpwd", "+",
                              "SYSLOG_IDENTIFIER=gdm-session-worker", "+", "SYSLOG_IDENTIFIER=sudo"],
                             capture_output=True, text=True, timeout=8).stdout
    except (OSError, subprocess.SubprocessError):
        return 0
    return sum(1 for ln in out.splitlines() if AUTH_FAIL.search(ln))


def check(state: dict) -> list[str]:
    """One guard tick (state persists between ticks). Returns what was reported."""
    if not armed():
        state.clear()
        return []
    now = time.time()
    events = []
    last_tick = state.get("tick", now)
    if now - last_tick > max(60.0, config.GUARD_INTERVAL_S * 6):
        events.append("The laptop woke up (lid opened or resumed)")
    lk = locked()
    if lk is False and state.get("locked") is True:
        events.append("Someone unlocked the laptop")
    if lk is not None:
        state["locked"] = lk
    since = state.get("journal_since", float(store.kv_get("guard_since") or now))
    if (n := auth_failures(since)) > 0:
        events.append(f"Wrong password typed {n} time(s)")
    state["journal_since"] = now
    state["tick"] = now
    for e in events[:1] if events else []:  # one photo per tick is plenty
        alert(e if len(events) == 1 else "; ".join(events))
    return events


def status() -> str:
    on = armed()
    since = float(store.kv_get("guard_since") or 0)
    shots = sorted((Path(config.DATA_DIR) / "guard").glob("*.jpg"))[-3:] if on or since else []
    return (f"Laptop guard is {'on' if on else 'off'}" + (f" (since {time.strftime('%H:%M', time.localtime(since))})"
                                                          if on and since else "") + "."
            + (f" Last photos: {', '.join(p.name for p in shots)}" if shots else ""))

