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
    """The first webcam that can actually capture video (skips metadata-only /dev/video* nodes)."""
    if not shutil.which("ffmpeg"):
        return None
    for dev in sorted(Path("/dev").glob("video*"), key=lambda p: p.name):
        try:
            out = subprocess.run(["v4l2-ctl", "-d", str(dev), "--list-formats"], capture_output=True, text=True,
                                 timeout=3).stdout
            if "Video Capture" in out or "[0]" in out:
                return str(dev)
        except (OSError, subprocess.SubprocessError):
            return str(dev)  # v4l2-ctl missing: fall back to the first node
    return None


_IN = ["-f", "v4l2", "-input_format", "mjpeg", "-video_size", "1280x720"]  # MJPEG: quick, no slow raw transfer


def _busy(stderr: bytes) -> bool:
    return b"resource busy" in (stderr or b"").lower() or b"Device or resource busy" in (stderr or b"")


# the last capture's trouble, for a clear message to the phone ("" = fine, "busy" = camera in use, "none" = no camera)
last_error = ""


def photo() -> Path | None:
    """One webcam frame (skipped frames let the camera adjust its exposure)."""
    global last_error
    dev = camera()
    if not dev:
        last_error = "none"
        return None
    d = Path(config.DATA_DIR) / "guard"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"guard-{time.strftime('%Y%m%d-%H%M%S')}.jpg"
    try:
        r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *_IN, "-i", dev, "-vf", "select=gte(n\\,6)",
                            "-frames:v", "1", str(out)], capture_output=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        last_error = "fail"
        return None
    last_error = "busy" if _busy(r.stderr) else ""
    return out if out.exists() and out.stat().st_size > 0 else None


def clip(seconds: float = 5.0) -> Path | None:
    """A short webcam video (skips the first frames so the exposure settles)."""
    dev = camera()
    if not dev:
        return None
    d = Path(config.DATA_DIR) / "guard"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"clip-{time.strftime('%Y%m%d-%H%M%S')}.mp4"
    global last_error
    secs = max(1.0, min(30.0, float(seconds)))
    try:
        r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *_IN, "-i", dev, "-t", f"{secs:.1f}",
                            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", str(out)], capture_output=True, timeout=secs + 25)
    except (OSError, subprocess.SubprocessError):
        last_error = "fail"
        return None
    last_error = "busy" if _busy(r.stderr) else ""
    return out if out.exists() and out.stat().st_size > 0 else None


def _no_camera_msg() -> str:
    return ("The laptop's camera is busy (another app is using it)." if last_error == "busy"
            else "I couldn't use the camera (no webcam found)." if last_error == "none"
            else "I couldn't use the camera (no webcam, or it's busy).")


def send_photo() -> str:
    """Take one webcam photo and send it to Telegram (for 'find my laptop')."""
    pic = photo()
    if pic is None:
        return _no_camera_msg()
    if not config.TELEGRAM_BOT_TOKEN:
        return f"Photo saved on the laptop: {pic} (set up Telegram to get it on your phone)."
    from jarvis.tools.general.send_file_telegram import deliver
    r = deliver(pic, f"Laptop camera · {time.strftime('%H:%M:%S')}")
    return "📷 Sent a photo from the laptop camera." if not r.startswith("error") else r


def send_clip(seconds: float = 5.0) -> str:
    """Record a short webcam video and send it to Telegram."""
    vid = clip(seconds)
    if vid is None:
        return _no_camera_msg()
    if not config.TELEGRAM_BOT_TOKEN:
        return f"Video saved on the laptop: {vid}."
    from jarvis.tools.general.send_file_telegram import deliver
    r = deliver(vid, f"Laptop camera · {int(max(1, min(30, seconds)))}s clip")
    return "🎥 Sent a video from the laptop camera." if not r.startswith("error") else r


def where() -> str:
    """Where the laptop is: known Wi-Fi spot, Wi-Fi/IP position, place name and a map link (0 tokens, free)."""
    from jarvis.core import geolocate
    return geolocate.where_text()


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

