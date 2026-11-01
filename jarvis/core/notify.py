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
import re
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


_upload_client = None


def _upload_http():
    """Its own connection for file uploads: never queued behind the bot's long poll on the shared client."""
    global _upload_client
    if _upload_client is None:
        import httpx  # lazy

        _upload_client = httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0))
    return _upload_client


def telegram_call(method: str, payload: dict | None = None, timeout: float | None = None,
                  files: dict | None = None, upload: bool = False) -> dict:
    """POST one Bot API method; returns the decoded "result" (raises RuntimeError on failure).
    files={"document": (name, fileobj)} sends multipart form data (sendDocument/sendPhoto)."""
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("telegram is not configured")
    url = TELEGRAM_API.format(token=config.TELEGRAM_BOT_TOKEN, method=method)
    try:
        if files:
            r = (_upload_http() if upload else _http()).post(url, data={k: str(v) for k, v in (payload or {}).items()},
                                                            files=files, timeout=timeout or 120)
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


def wants_phone(level: str, source: str) -> bool:
    """Does this alert go to the phone too? Yes for every alert (owner: laptop AND Telegram, always) unless
    KURAMA_TELEGRAM_ALL=0, which keeps the old rule: warnings/errors, info only from TELEGRAM_INFO_SOURCES."""
    if config.TELEGRAM_ALL:
        return True
    return level in ("warning", "error") or source in config.TELEGRAM_INFO_SOURCES


# --- mute ("don't send RAM warnings for 20 minutes"): kv MUTE_KEY = {source: until_ts} ---
MUTE_KEY = "notify_mute"


def _mutes() -> dict[str, float]:
    import json
    try:
        d = json.loads(store.kv_get(MUTE_KEY, "{}") or "{}")
    except (ValueError, TypeError):
        return {}
    now = time.time()
    return {k: float(v) for k, v in d.items() if float(v) > now}


def _save_mutes(d: dict[str, float]) -> None:
    import json
    store.kv_set(MUTE_KEY, json.dumps(d))


def mute_sources(kind: str) -> tuple[str, ...]:
    """'resource' -> ('resource_guard',); 'all' -> '*'; unknown -> the source itself."""
    kind = (kind or "").strip().lower()
    if kind in ("all", "*", "everything"):
        return ("*",)
    return config.MUTE_KINDS.get(kind, (kind,) if kind else ())


def mute(kind: str, minutes: float) -> float:
    """Silence one kind of alert (or 'all') for `minutes`. Returns the until timestamp."""
    until = time.time() + min(max(1.0, minutes), config.MUTE_MAX_MIN) * 60  # never forever
    d = _mutes()
    for src in mute_sources(kind):
        d[src] = until
    _save_mutes(d)
    return until


def unmute(kind: str = "all") -> list[str]:
    """Lift a mute ('all' lifts every mute). Returns the sources unmuted."""
    d = _mutes()
    gone = list(d) if (kind or "all").lower() in ("all", "*", "everything") else \
        [s for s in mute_sources(kind) if s in d]
    for s in gone:
        d.pop(s, None)
    _save_mutes(d)
    return gone


def muted(source: str) -> float:
    """Until when `source` is muted (0 = not muted). 'all' never covers MUTE_ALL_KEEPS."""
    d = _mutes()
    own = d.get(source, 0.0)
    every = d.get("*", 0.0) if source not in config.MUTE_ALL_KEEPS else 0.0
    return max(own, every)


def active_mutes() -> dict[str, float]:
    return _mutes()


# --- Telegram replies: which alert did the user reply to? ---
_replied = {"text": ""}


def source_of(quoted: str) -> str:
    """The source of a sent alert, found by its first line (the title after the level icon); '' = not an alert."""
    first = (quoted or "").strip().splitlines()[0] if (quoted or "").strip() else ""
    title = first
    for icon in _ICON.values():
        if icon and title.startswith(icon):
            title = title[len(icon):]
    title = title.strip()
    if not title:
        return ""
    for a in store.alerts_recent(300):
        if (a.get("title") or "").strip() == title and a.get("source"):
            return a["source"]
    return ""


def set_replied(quoted: str) -> None:
    _replied["text"] = quoted or ""


def replied_source() -> str:
    """Source of the alert the current Telegram message replies to ('' when none)."""
    return source_of(_replied["text"]) if _replied["text"] else ""


def notify(title: str, text: str = "", level: str = "info", source: str = "", desktop: bool = True,
           telegram: bool | None = None, save: bool = True) -> list[str]:
    """Fan out one alert. telegram=None decides by wants_phone(). Returns the channels it reached.
    A muted source (mute()) is only saved (channel 'muted'), never shown or sent."""
    level = level if level in LEVELS else "info"
    telegram = wants_phone(level, source) if telegram is None else telegram
    title, text = (title or "KURAMA").strip()[:120], (text or "").strip()[:3000]
    if _duplicate(title, text):
        log.info("dedupe: %s", title)
        return []
    try:
        if source and muted(source):
            desktop = telegram = False
    except Exception as e:  # a broken kv must never block alerts
        log.warning("mute check failed: %s", e)
    sent: list[str] = []
    if desktop and desktop_send(title, text, level):
        sent.append("desktop")
    if telegram and telegram_send(f"{_ICON[level]}{title}\n{text}".strip()):
        sent.append("telegram")
    if save:
        try:
            store.alert_add(title, text, level, source, ",".join(sent) or ("muted" if source and muted(source) else ""))
            sent.append("store")
        except Exception as e:  # alerts must never crash a worker
            log.warning("could not save alert: %s", e)
    log.info("[%s] %s: %s -> %s", level, title, text[:200].replace("\n", " | "), ",".join(sent) or "-")
    return sent


# --- what KURAMA told the user on its own (so the agent can answer "why didn't you tell me earlier?") ---
_ASKS_PAST = re.compile(r"\b(?:remind|alert|notif|messag|told|tell me|earlier|sent|warn|missed|job|why did|why didn)",
                        re.I)


def recent_sent(window_s: float, limit: int = 4) -> list[dict]:
    """Alerts that actually reached the user (desktop / Telegram) in the last window_s, newest first."""
    try:
        rows = store.alerts_recent(limit * 3)
    except Exception:
        return []
    now = time.time()
    reached = lambda r: bool({"desktop", "telegram"} & set((r.get("channels") or "").split(",")))  # noqa: E731
    return [r for r in rows if now - r["ts"] <= window_s and reached(r)][:limit]


def context_line(user_text: str, channel: str = "") -> str:
    """One system-prompt line listing those messages, only when the turn may be about them (~40-80 tokens):
    the user mentions reminders/alerts/messages, or writes on Telegram within 3 h of one."""
    rows = recent_sent(config.NOTIFY_CONTEXT_S)
    if not rows:
        return ""
    fresh = time.time() - rows[0]["ts"] < 3 * 3600
    if not (_ASKS_PAST.search(user_text or "") or (channel == "telegram" and fresh)):
        return ""
    items = "; ".join(f"[{time.strftime('%a %I:%M %p', time.localtime(r['ts']))}] {r['title']}: "
                      f"{(r.get('text') or '').splitlines()[0][:110] if r.get('text') else ''}"
                      for r in reversed(rows))
    return f"Messages you sent the user on your own recently (desktop/Telegram): {items}."


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
