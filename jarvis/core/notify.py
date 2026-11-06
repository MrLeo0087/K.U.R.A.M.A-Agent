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

# --- where a reply goes: the owner can talk to KURAMA in any topic of the sections group, and the answer (text,
# photos, files, "typing…") goes back to that topic. Everything addressed to the private chat is redirected while a
# target is set: per thread (replying_to, e.g. a background job asked from a topic), else the bot's current message.
_here = threading.local()
_reply_global: tuple | None = None
_MEDIA = ("sendPhoto", "sendVideo", "sendMediaGroup", "sendAnimation")
_collect: list[int] | None = None  # ids of the messages sent while the bot answers one message (collecting())
_ALERT_IDS = "tg_alert_msgs"  # [chat, message_id] of alerts sent, so /clear can remove them from Telegram


def reply_target() -> tuple | None:
    """(chat id, topic thread id or None) the current reply goes to, or None (the private chat)."""
    return getattr(_here, "to", None) or _reply_global


def set_reply_target(to: tuple | None) -> None:
    """The Telegram bot: the message it is answering came from here (None when done)."""
    global _reply_global
    _reply_global = to


class replying_to:  # noqa: N801 - used as `with notify.replying_to(target):` in this thread only
    def __init__(self, to: tuple | None):
        self.to = to

    def __enter__(self):
        self.old, _here.to = getattr(_here, "to", None), self.to

    def __exit__(self, *exc):
        _here.to = self.old


def _route(method: str, payload: dict | None) -> dict | None:
    """A message for the private chat goes to the topic being talked in; a picture KURAMA sends on its own goes to
    the Images section (when sections are on)."""
    if not payload or str(payload.get("chat_id")) != str(config.TELEGRAM_CHAT_ID) or payload.get("message_thread_id"):
        return payload
    to = reply_target()
    if to is None and (method in _MEDIA or method == "sendDocument"):  # sent from the laptop: pictures -> Images,
        try:  # files (PDF, MD, zips) -> Share
            from jarvis.core import tgtopics
            g, t = tgtopics.where("images" if method in _MEDIA else "share", "info")
            to = (g, t) if g else None
        except Exception:  # noqa: BLE001
            to = None
    if not to or to[0] is None:
        return payload
    p = dict(payload, chat_id=to[0])
    if to[1]:
        p["message_thread_id"] = to[1]
    return p


def collecting() -> None:
    """The bot starts answering a message: remember the ids of what is sent to its chat (for filing a copy)."""
    global _collect
    _collect = []


def collected() -> list[int]:
    global _collect
    ids, _collect = _collect or [], None
    return ids


def _ids(result) -> list[int]:
    rows = result if isinstance(result, list) else [result]
    return [r["message_id"] for r in rows if isinstance(r, dict) and r.get("message_id")]


def _after_send(method: str, payload: dict | None, result) -> None:
    """Note what the current answer sent; file a copy of a picture in the Images section (if it isn't there)."""
    if not payload or not method.startswith("send") or method == "sendChatAction":
        return
    to = reply_target()
    if _collect is not None and to and str(payload.get("chat_id")) == str(to[0]):
        _collect.extend(_ids(result))
    if method not in _MEDIA:
        return
    try:
        from jarvis.core import tgtopics
        g, t = tgtopics.where("images", "info")
        if not g or (str(payload.get("chat_id")) == str(g) and payload.get("message_thread_id") == t):
            return
        telegram_call("copyMessages", {"chat_id": g, "message_thread_id": t, "from_chat_id": payload["chat_id"],
                                       "message_ids": _ids(result)})
    except Exception as e:  # noqa: BLE001 - filing a copy must never break sending
        log.info("filing the picture failed: %s", e)


def _keep_ids(result) -> None:
    """Remember a sent alert so /clear can delete it later (the newest 500)."""
    import json
    if not isinstance(result, dict) or not result.get("message_id"):
        return
    try:
        ids = json.loads(store.kv_get(_ALERT_IDS) or "[]")
        ids.append([(result.get("chat") or {}).get("id"), result["message_id"]])
        store.kv_set(_ALERT_IDS, json.dumps(ids[-500:]))
    except Exception:  # noqa: BLE001
        pass


def delete_alerts() -> int:
    """Delete the alerts KURAMA sent to Telegram (private chat and sections) — /clear, /clearchat, /reset.
    Telegram lets a bot delete its messages for 48 hours; older ones are skipped. Returns how many were asked."""
    import json
    try:
        ids = json.loads(store.kv_get(_ALERT_IDS) or "[]")
    except Exception:  # noqa: BLE001
        return 0
    store.kv_delete(_ALERT_IDS)
    by_chat: dict = collections.defaultdict(list)
    for chat, mid in ids:
        if chat:
            by_chat[chat].append(mid)
    for chat, mids in by_chat.items():
        for i in range(0, len(mids), 100):
            try:
                telegram_call("deleteMessages", {"chat_id": chat, "message_ids": mids[i:i + 100]})
            except RuntimeError as e:  # some too old: one by one, skipping those
                log.info("deleteMessages: %s", e)
                for m in mids[i:i + 100]:
                    try:
                        telegram_call("deleteMessage", {"chat_id": chat, "message_id": m})
                    except RuntimeError:
                        pass
    return len(ids)


def redact(text: str) -> str:
    """Remove the bot token from anything that might be logged or shown."""
    tok = config.TELEGRAM_BOT_TOKEN
    return text.replace(tok, "<token>") if tok and text else text


def telegram_configured() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def _transport():
    """IPv4 only for Telegram (config.TELEGRAM_IPV4): on this network 1 of 4 IPv6 connections to api.telegram.org
    hangs for 20 s+ (measured 11-06: curl -6 20.0 s twice in 8, IPv4 0.6 s every time), and httpx doesn't fall back
    to IPv4 by itself. That hang was the "screenshot arrives after a minute"."""
    import httpx  # lazy
    return httpx.HTTPTransport(local_address="0.0.0.0", retries=1) if config.TELEGRAM_IPV4 else None


def _http():
    global _client
    if _client is None:
        import httpx  # lazy

        _client = httpx.Client(timeout=config.HTTP_TIMEOUT_S + config.TELEGRAM_POLL_TIMEOUT_S + 5, transport=_transport())
    return _client


_upload_client = None


def _upload_http():
    """Its own connection for file uploads: never queued behind the bot's long poll on the shared client."""
    global _upload_client
    if _upload_client is None:
        import httpx  # lazy

        _upload_client = httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0), transport=_transport())
    return _upload_client


def _upload(url: str, payload: dict | None, files: dict, timeout: float | None):
    import httpx  # lazy
    data = {k: str(v) for k, v in (payload or {}).items()}
    for attempt in (1, 2):  # a CONNECT failure sent nothing, so one more try can't make a duplicate
        try:
            with httpx.Client(timeout=httpx.Timeout(timeout or 60, connect=8.0), transport=_transport()) as c:
                return c.post(url, data=data, files=files)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if attempt == 2:
                raise
            time.sleep(1)


def telegram_call(method: str, payload: dict | None = None, timeout: float | None = None,
                  files: dict | None = None, upload: bool = False) -> dict:
    """POST one Bot API method; returns the decoded "result" (raises RuntimeError on failure).
    files={"document": (name, fileobj)} sends multipart form data (sendDocument/sendPhoto)."""
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("telegram is not configured")
    url = TELEGRAM_API.format(token=config.TELEGRAM_BOT_TOKEN, method=method)
    payload = _route(method, payload)
    try:
        if files and upload:  # a FRESH connection per upload: a pooled one gone stale behind the router hung the
            r = _upload(url, payload, files, timeout)  # upload for a minute and then failed (11-04)
        elif files:
            r = _http().post(url, data={k: str(v) for k, v in (payload or {}).items()}, files=files, timeout=timeout or 120)
        else:
            r = _http().post(url, json=payload or {}, timeout=timeout or config.HTTP_TIMEOUT_S)
        data = r.json()
    except Exception as e:  # network / JSON error: never leak the URL
        raise RuntimeError(redact(f"{type(e).__name__}: {e}")) from None
    if not data.get("ok"):
        raise RuntimeError(redact(f"telegram {method} failed: {data.get('description', r.status_code)}"))
    _after_send(method, payload, data.get("result"))
    return data.get("result")


def _cut_at(s: str, n: int) -> int:
    c = s.rfind("\n", 0, n)
    if c > n // 2:
        return c
    c = s.rfind(" ", 0, n)
    return c if c > n // 2 else n


def split_for_telegram(text: str) -> tuple[list[str], str]:
    """(messages as Telegram HTML, the whole text for a file or ''): nothing is ever cut.
    Short: as it is. Long: the first lines show, the rest is folded in an expandable quote ("show more" on the
    phone, like a post). Longer than two messages: the start + "show more", and the WHOLE text as an .md file."""
    import html
    text = (text or "").strip()
    limit = config.TELEGRAM_MAX_REPLY_CHARS
    if len(text) <= config.TELEGRAM_FOLD_CHARS:
        return [html.escape(text, quote=False)], ""

    def folded(head: str, rest: str) -> str:
        return html.escape(head.rstrip(), quote=False) + ("\n<blockquote expandable>" + html.escape(rest.strip(), quote=False) + "</blockquote>"
                                             if rest.strip() else "")
    c = _cut_at(text, config.TELEGRAM_FOLD_CHARS // 2)
    head, rest = text[:c], text[c:]
    if len(text) <= limit:
        return [folded(head, rest)], ""
    if len(text) <= 2 * limit - 200:
        c2 = _cut_at(rest, limit - len(head) - 50)
        return [folded(head, rest[:c2]), "<blockquote expandable>" + html.escape(rest[c2:].strip(), quote=False) + "</blockquote>"], ""
    c2 = _cut_at(rest, limit - len(head) - 200)
    return [folded(head, rest[:c2]) + "\n📎 The whole text is in the file below."], text


def send_long(text: str, chat_id: str | int | None = None, title: str = "reply", thread: int | None = None,
              keep: bool = False) -> bool:
    """Send any text to Telegram complete: folded "show more" messages, plus an .md file when it is very long.
    keep: an alert, remembered so /clear can delete it."""
    parts, whole = split_for_telegram(text)
    ok = True
    for part in parts:
        try:
            r = telegram_call("sendMessage", {"chat_id": chat_id or config.TELEGRAM_CHAT_ID, "text": part,
                                              "parse_mode": "HTML", "disable_web_page_preview": True,
                                              **({"message_thread_id": thread} if thread else {})})
            if keep:
                _keep_ids(r)
        except RuntimeError as e:  # (an HTML problem: the same text plain, never lost)
            if thread and "thread not found" in str(e).lower():  # you deleted that topic: forget it, send privately
                from jarvis.core import tgtopics
                tgtopics.forget_thread(thread)
                return send_long(text, None, title, None, keep)
            log.warning("telegram send failed (%s): sending plain", e)
            try:
                import html
                plain = re.sub(r"</?blockquote[^>]*>", "", part)
                r = telegram_call("sendMessage", {"chat_id": chat_id or config.TELEGRAM_CHAT_ID,
                                                  "text": html.unescape(plain), "disable_web_page_preview": True,
                                                  **({"message_thread_id": thread} if thread else {})})
                if keep:
                    _keep_ids(r)
            except RuntimeError as e2:
                log.warning("telegram send failed: %s", e2)
                return False
    if whole:
        import io
        name = re.sub(r"[^\w-]+", "-", title.lower()).strip("-")[:40] or "reply"
        try:
            telegram_call("sendDocument", {"chat_id": chat_id or config.TELEGRAM_CHAT_ID,
                                           **({"message_thread_id": thread} if thread else {})},
                          files={"document": (f"{name}.md", io.BytesIO(whole.encode("utf-8")))}, upload=True,
                          timeout=60)
        except RuntimeError as e:
            log.warning("telegram file send failed: %s", e)
            ok = False
    return ok


def telegram_send(text: str, chat_id: str | int | None = None, thread: int | None = None, keep: bool = False) -> bool:
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
    return send_long(text, chat_id, title=text.split("\n", 1)[0][:40], thread=thread, keep=keep)  # complete


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
    title, text = (title or "KURAMA").strip()[:120], (text or "").strip()  # whole: send_long never cuts it
    if _duplicate(title, text):
        log.info("dedupe: %s", title)
        return []
    try:
        if source and muted(source):
            desktop = telegram = False
    except Exception as e:  # a broken kv must never block alerts
        log.warning("mute check failed: %s", e)
    sent: list[str] = []
    if desktop and desktop_send(title, text[:600], level):
        sent.append("desktop")
    group, thread = None, None
    try:  # sorted into a topic of the owner's group when sections are on (core/tgtopics.py)
        from jarvis.core import tgtopics
        group, thread = tgtopics.where(source, level, title)
    except Exception:  # noqa: BLE001 - no sections: the private chat
        pass
    if telegram and telegram_send(f"{_ICON[level]}{title}\n{text}".strip(), group, thread, keep=True):
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
