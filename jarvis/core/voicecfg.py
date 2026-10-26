"""Voice settings the dashboard can change: the laptop's microphone volume (PulseAudio/PipeWire, pactl) and how
easily the wake word triggers (kv 'wake_sensitivity'). The page's own settings (speech sensitivity, pause before
sending, browser noise suppression...) live in the page; these two need the system or the server."""
from __future__ import annotations

import re
import shutil
import subprocess

from jarvis.core import config

WAKE_LEVELS = {  # level -> (min loudness of a burst, name-match ratio)
    "low": (1500.0, 0.78),     # noisy room: only clear, loud "KURAMA"
    "normal": (config.WAKE_MIN_RMS, config.WAKE_MATCH_RATIO),
    "high": (550.0, 0.65),     # quiet voice / far from the laptop
}


def _pactl(*args: str) -> str:
    if not shutil.which("pactl"):
        return ""
    try:
        return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=4).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def mic() -> dict:
    out = _pactl("get-source-volume", "@DEFAULT_SOURCE@")
    m = re.search(r"(\d+)%", out)
    src = _pactl("get-default-source").strip()
    return {"volume": int(m.group(1)) if m else None, "source": src,
            "echo_canceller": src.startswith("kurama_ec")}


def set_mic_volume(pct: int) -> dict:
    pct = max(10, min(150, int(pct)))
    _pactl("set-source-volume", "@DEFAULT_SOURCE@", f"{pct}%")
    return mic()


def wake_level() -> str:
    from jarvis.core import store
    try:
        lv = store.kv_get("wake_sensitivity") or "normal"
    except Exception:  # noqa: BLE001
        lv = "normal"
    return lv if lv in WAKE_LEVELS else "normal"


def set_wake_level(level: str) -> str:
    from jarvis.core import store
    if level not in WAKE_LEVELS:
        raise ValueError(f"wake sensitivity must be one of {', '.join(WAKE_LEVELS)}")
    store.kv_set("wake_sensitivity", level)
    return level


def wake_min_rms() -> float:
    return WAKE_LEVELS[wake_level()][0]


def wake_ratio() -> float:
    return WAKE_LEVELS[wake_level()][1]


def status() -> dict:
    return {"mic": mic(), "wake": wake_level()}
