"""Settings for the KURAMA HTTP API (jarvis.api). Kept out of core/config.py on purpose.

Every value comes from an environment variable so the same code runs on the laptop or, later, in a
Docker container on a server. Old JARVIS_WEB_* names (P7b test UI) still work as fallbacks.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LANGS = ("en", "ne", "hi")
LOOPBACK = ("127.0.0.1", "localhost", "::1")


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n)
        if v is not None and v.strip() != "":
            return v.strip()
    return default


def _int(default: int, *names: str) -> int:
    try:
        return int(_env(*names, default=str(default)))
    except ValueError:
        return default


def _float(default: float, *names: str) -> float:
    try:
        return float(_env(*names, default=str(default)))
    except ValueError:
        return default


def _bool(default: bool, *names: str) -> bool:
    v = _env(*names)
    return default if v == "" else v.lower() in ("1", "true", "yes", "on")


def _list(raw: str) -> list[str]:
    return [x.strip().rstrip("/") for x in raw.split(",") if x.strip()]


def _default_origins(port: int) -> list[str]:
    """The frontend served by this API, plus common local static-server ports (python -m http.server,
    VS Code Live Server, Vite)."""
    ports = sorted({port, 8000, 8080, 5500, 5173, 3000})
    return [f"http://{h}:{p}" for p in ports for h in ("127.0.0.1", "localhost")]


@dataclass
class Settings:
    host: str = "127.0.0.1"
    port: int = 8000
    token: str = ""  # empty: no auth (only allowed on a loopback host unless allow_no_token)
    allow_no_token: bool = False
    cors_origins: list[str] = field(default_factory=list)
    allowed_hosts: list[str] = field(default_factory=list)  # Host header allowlist (DNS-rebinding guard)
    serve_frontend: bool = True
    frontend_dir: Path = ROOT / "frontend"
    confirm_timeout_s: float = 120.0  # no answer from the browser -> deny
    warm_on_start: bool = True  # import + warm the agent in the background after startup
    warm_delay_s: float = 1.0
    max_text_chars: int = 4000
    max_audio_bytes: int = 8 * 1024 * 1024  # a few minutes of webm/opus
    ffmpeg: str = "ffmpeg"
    ffmpeg_timeout_s: float = 20.0
    status_interval_s: float = 2.0  # /status/stream push interval
    status_cache_s: float = 1.5  # one snapshot shared by every client within this window
    procs_refresh_s: float = 4.0  # process table walk is the costly part: refresh less often
    status_jobs: int = 6
    status_alerts: int = 5
    log_level: str = "warning"

    @property
    def loopback(self) -> bool:
        return self.host in LOOPBACK


def from_env(host: str | None = None, port: int | None = None) -> Settings:
    """Settings from the environment; host/port (e.g. CLI flags) override and shape the defaults."""
    host = host or _env("JARVIS_API_HOST", default="127.0.0.1")
    port = port or _int(8000, "JARVIS_API_PORT", "JARVIS_WEB_PORT")
    origins = _env("JARVIS_CORS_ORIGINS")
    hosts = _env("JARVIS_API_ALLOWED_HOSTS")
    return Settings(
        host=host,
        port=port,
        token=_env("JARVIS_API_TOKEN"),
        allow_no_token=_bool(False, "JARVIS_API_ALLOW_NO_TOKEN"),
        cors_origins=_list(origins) if origins else _default_origins(port),
        allowed_hosts=_list(hosts) if hosts else (list(LOOPBACK) if host in LOOPBACK else ["*"]),
        serve_frontend=_bool(True, "JARVIS_SERVE_FRONTEND"),
        frontend_dir=Path(_env("JARVIS_FRONTEND_DIR", default=str(ROOT / "frontend"))),
        confirm_timeout_s=_float(120.0, "JARVIS_API_CONFIRM_TIMEOUT", "JARVIS_WEB_CONFIRM_TIMEOUT"),
        warm_on_start=_bool(True, "JARVIS_API_WARM", "JARVIS_WEB_WARM"),
        warm_delay_s=_float(1.0, "JARVIS_API_WARM_DELAY", "JARVIS_WEB_WARM_DELAY"),
        max_text_chars=_int(4000, "JARVIS_API_MAX_TEXT", "JARVIS_WEB_MAX_TEXT"),
        max_audio_bytes=_int(8 * 1024 * 1024, "JARVIS_API_MAX_AUDIO", "JARVIS_WEB_MAX_AUDIO"),
        ffmpeg=_env("JARVIS_API_FFMPEG", "JARVIS_WEB_FFMPEG", default="ffmpeg"),
        ffmpeg_timeout_s=_float(20.0, "JARVIS_API_FFMPEG_TIMEOUT", "JARVIS_WEB_FFMPEG_TIMEOUT"),
        status_interval_s=max(1.0, _float(2.0, "JARVIS_API_STATUS_INTERVAL")),
        log_level=_env("JARVIS_API_LOG_LEVEL", "JARVIS_WEB_LOG_LEVEL", default="warning"),
    )
