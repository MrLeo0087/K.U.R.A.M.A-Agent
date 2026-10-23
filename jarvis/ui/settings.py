"""Settings for the web test UI (jarvis.server). Kept out of core/config.py on purpose.

Every value can be overridden with an environment variable (JARVIS_WEB_*).
"""
from __future__ import annotations

import os
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


HOST = "127.0.0.1"  # fixed, no override: localhost only: the UI can run tools on this laptop
PORT = _int("JARVIS_WEB_PORT", 8000)
WEB_DIR = Path(__file__).resolve().parent / "web"
CONFIRM_TIMEOUT_S = _float("JARVIS_WEB_CONFIRM_TIMEOUT", 60.0)  # no answer from the browser -> deny
WARM_ON_START = _bool("JARVIS_WEB_WARM", True)  # import + warm the agent in the background after startup
WARM_DELAY_S = _float("JARVIS_WEB_WARM_DELAY", 1.0)
STATUS_REFRESH_S = _int("JARVIS_WEB_STATUS_REFRESH", 10)  # page polls /api/status this often
MAX_TEXT_CHARS = _int("JARVIS_WEB_MAX_TEXT", 4000)
MAX_AUDIO_BYTES = _int("JARVIS_WEB_MAX_AUDIO", 8 * 1024 * 1024)  # ~ a few minutes of webm/opus
FFMPEG = os.getenv("JARVIS_WEB_FFMPEG", "ffmpeg")
FFMPEG_TIMEOUT_S = _float("JARVIS_WEB_FFMPEG_TIMEOUT", 20.0)
STATUS_JOBS = _int("JARVIS_WEB_STATUS_JOBS", 6)
STATUS_ALERTS = _int("JARVIS_WEB_STATUS_ALERTS", 5)
LOG_LEVEL = os.getenv("JARVIS_WEB_LOG_LEVEL", "warning")
