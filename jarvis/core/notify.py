"""notify(title, text, level): one alert fanned out to every available channel.

  - desktop: notify-send (if installed and config.NOTIFY_DESKTOP)
  - Telegram: Bot API sendMessage over plain httpx (only when TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
    are set; rate-limited to NOTIFY_TELEGRAM_PER_MIN)
  - SQLite `alerts` table: the idle voice loop speaks pending alerts (pop_spoken_alert)

Identical (title, text) alerts within NOTIFY_DEDUPE_S are sent once. Stdlib + httpx (lazy) only, so
the tiny worker daemons can use it. The bot token is part of the API URL: it is never logged.
"""
from __future__ import annotations

import collections
import logging
import shutil
import subprocess
import threading
import time

from jarvis.core import config, store

log = logging.getLogger("jarvis.notify")
logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx INFO lines contain the bot-token URL
logging.getLogger("httpcore").setLevel(logging.WARNING)

LEVELS = ("info", "warning", "error")
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
_URGENCY = {"info": "low", "warning": "normal", "error": "critical"}
_ICON = {"info": "", "warning": "⚠️ ", "error": "🛑 "}

_lock = threading.Lock()
_recent: dict[tuple[str, str], float] = {}  # (title, text) -> last sent
_tg_sent: collections.deque[float] = collections.deque()
_client = None


def redact(text: str) -> str:
    """Remove the bot token from anything that might be logged or shown."""
    tok = config.TELEGRAM_BOT_TOKEN
    return text.replace(tok, "<token>") if tok and text else text


def telegram_configured() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def _http():
    global _client
    if _client is None:
        import httpx  # lazy

        _client = httpx.Client(timeout=config.HTTP_TIMEOUT_S + config.TELEGRAM_POLL_TIMEOUT_S + 5)
    return _client


def telegram_call(method: str, payload: dict | None = None, timeout: float | None = None,
                  files: dict | None = None) -> dict:
    """POST one Bot API method; returns the decoded "result" (raises RuntimeError on failure).
    files={"document": (name, fileobj)} sends multipart form data (sendDocument/sendPhoto)."""
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("telegram is not configured")
    url = TELEGRAM_API.format(token=config.TELEGRAM_BOT_TOKEN, method=method)
    try:
        if files:
            r = _http().post(url, data={k: str(v) for k, v in (payload or {}).items()}, files=files,
                             timeout=timeout or 120)
        else:
            r = _http().post(url, json=payload or {}, timeout=timeout or config.HTTP_TIMEOUT_S)
        data = r.json()
    except Exception as e:  # network / JSON error: never leak the URL
        raise RuntimeError(redact(f"{type(e).__name__}: {e}")) from None
    if not data.get("ok"):
        raise RuntimeError(redact(f"telegram {method} failed: {data.get('description', r.status_code)}"))
    return data.get("result")


def telegram_send(text: str, chat_id: str | int | None = None) -> bool:
    """sendMessage to the configured chat (rate-limited). False when not configured or failed."""
    if not telegram_configured():
        return False
    now = time.monotonic()
    with _lock:
        while _tg_sent and now - _tg_sent[0] > 60:
            _tg_sent.popleft()
        if len(_tg_sent) >= config.NOTIFY_TELEGRAM_PER_MIN:
            log.warning("telegram rate limit reached; message dropped")
            return False
        _tg_sent.append(now)
    try:
        telegram_call("sendMessage", {"chat_id": chat_id or config.TELEGRAM_CHAT_ID,
                                      "text": text[: config.TELEGRAM_MAX_REPLY_CHARS],
                                      "disable_web_page_preview": True})
        return True
    except RuntimeError as e:
        log.warning("telegram send failed: %s", e)
        return False


def desktop_send(title: str, text: str, level: str = "info") -> bool:
    if not config.NOTIFY_DESKTOP:
        return False
    exe = shutil.which("notify-send")
    if not exe:
        return False
    try:
        subprocess.Popen([exe, "-u", _URGENCY.get(level, "normal"), "-a", "KURAMA", title, text[:500]],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError as e:
        log.debug("notify-send failed: %s", e)
        return False


def _duplicate(title: str, text: str) -> bool:
    now = time.monotonic()
    with _lock:
        for k, t in list(_recent.items()):
            if now - t > config.NOTIFY_DEDUPE_S:
                del _recent[k]
        if (title, text) in _recent:
            return True
        _recent[(title, text)] = now
        return False


def notify(title: str, text: str = "", level: str = "info", source: str = "", desktop: bool = True,
           telegram: bool = True, save: bool = True) -> list[str]:
    """Fan out one alert. Returns the channels it reached ([] when deduplicated)."""
    level = level if level in LEVELS else "info"
    title, text = (title or "KURAMA").strip()[:120], (text or "").strip()[:3000]
    if _duplicate(title, text):
        log.info("dedupe: %s", title)
        return []
    sent: list[str] = []
    if desktop and desktop_send(title, text, level):
        sent.append("desktop")
    if telegram and telegram_send(f"{_ICON[level]}{title}\n{text}".strip()):
        sent.append("telegram")
    if save:
        try:
            store.alert_add(title, text, level, source, ",".join(sent))
            sent.append("store")
        except Exception as e:  # alerts must never crash a worker
            log.warning("could not save alert: %s", e)
    log.info("[%s] %s: %s -> %s", level, title, text[:200].replace("\n", " | "), ",".join(sent) or "-")
    return sent


def reset() -> None:
    """Tests: forget dedupe/rate-limit state."""
    with _lock:
        _recent.clear()
        _tg_sent.clear()


# --- voice: speak pending alerts when idle ---
def pop_spoken_alert() -> str | None:
    """Next pending warning/error alert as one spoken line (marks it announced), or None."""
    try:
        store.alerts_mark_announced(older_than=time.time() - config.ALERT_ANNOUNCE_MAX_AGE_S)
        rows = store.alerts_pending(1, config.ALERT_SPOKEN_LEVELS)
        if not rows:
            return None
        a = rows[0]
        store.alerts_mark_announced([a["id"]])
    except Exception as e:
        log.debug("alert check failed: %s", e)
        return None
    first = (a.get("text") or "").splitlines()[0][:160] if a.get("text") else ""
    return f"Alert: {a['title']}. {first}".strip()
