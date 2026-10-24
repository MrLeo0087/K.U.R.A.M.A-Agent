"""Telegram remote control (worker "telegram_bot"): long-polling getUpdates over plain httpx.

Only messages from TELEGRAM_CHAT_ID are handled; anything else is ignored silently (and logged).
Text goes to agent.run(text, mode="text") with a Telegram confirm hook (safety mode "telegram"):
confirm-level tools send "Reply yes/no" and wait for the next message (timeout or unclear = no);
blocked tools never run (safety.execute refuses them). Commands: /status, /jobs, /help. Replies are
cut to TELEGRAM_MAX_REPLY_CHARS. Voice notes are not supported. Skipped when not configured.
The agent (LangChain) is imported only when the first real question arrives.
"""
from __future__ import annotations

import collections
import re
import threading
import time

from jarvis.core import config, notify, store
from jarvis.workers.base import Worker

OFFSET_KEY = "telegram_offset"
HELP = (
    "🤖 KURAMA — control your laptop from here\n"
    "Send any question or command as text or a voice note.\n"
    "\n📷 Camera & screen\n"
    "/camera — a photo from the laptop camera\n"
    "/video [secs] — a short camera clip (default 5s, e.g. /video 8)\n"
    "/screen — a screenshot of the laptop\n"
    "\n📍 Find my laptop\n"
    "/where (or /locate) — where the laptop is, with a map link\n"
    "/here <name> — label the current Wi-Fi (e.g. /here Home) so /where names it\n"
    "/guard on | off — watch the laptop; a photo + location if someone uses it\n"
    "\n📋 Clipboard & files\n"
    "copy: <text> — put text on the laptop's clipboard\n"
    "/clip — get the laptop's clipboard\n"
    "Send a file/photo — saved on the laptop (caption 'to <folder>' picks the folder)\n"
    "\n⚙️ Status & work\n"
    "/status (or 'status') — training epochs/accuracy/ETA, jobs, downloads...\n"
    "'stop training' / 'stop training now' — stop a run (asks first)\n"
    "/jobs — background jobs\n"
    "\n/help — this list\nRisky actions ask 'Reply yes/no' first.")
TEXT_ONLY = "Sorry, I can't use that kind of message."
# a reply to find_and_send's numbered list: "2", "send 2", "number 2", "all", "send all" (0 tokens)
PICK = re.compile(r"^\s*(?:send\s+)?(?:(?:no\.?|number|file)\s*)?(\d{1,2}|all|both)\s*[.!]?\s*$", re.I)


class TelegramBot(Worker):
    name = "telegram_bot"
    interval_s = 5.0

    def __init__(self, interval_s: float | None = None):
        super().__init__(interval_s)
        self.offset = 0
        self._agent = None
        self._backlog: collections.deque[dict] = collections.deque()
        self._confirm_lock = threading.Lock()
        self.handled = 0
        self.started = time.time()

    def available(self) -> str | None:
        return None if notify.telegram_configured() else "not configured"

    def setup(self) -> None:
        try:
            self.offset = int(store.kv_get(OFFSET_KEY, "0") or 0)
        except ValueError:
            self.offset = 0

    def info(self) -> dict:
        return {"handled": self.handled}

    def stop(self, timeout: float = 1.0) -> None:
        super().stop(timeout)  # a pending long poll may hold the (daemon) thread up to 25 s

    # --- Bot API ---
    def poll(self, timeout: int | None = None) -> list[dict]:
        timeout = config.TELEGRAM_POLL_TIMEOUT_S if timeout is None else timeout
        updates = notify.telegram_call("getUpdates", {"offset": self.offset, "timeout": timeout,
                                                      "allowed_updates": ["message"]},
                                       timeout=timeout + 10) or []
        if updates:
            self.offset = max(int(u.get("update_id", 0)) for u in updates) + 1
            store.kv_set(OFFSET_KEY, str(self.offset))
        return updates

    def typing(self) -> None:
        """Show "typing…" in the chat (lasts ~5 s), so a slow answer doesn't look stuck."""
        try:
            notify.telegram_call("sendChatAction", {"chat_id": config.TELEGRAM_CHAT_ID, "action": "typing"})
        except Exception:
            pass

    def _keep_typing(self, stop: "threading.Event") -> None:
        while not stop.is_set():
            self.typing()
            if stop.wait(4):  # Telegram clears "typing…" after ~5 s, so refresh a little sooner
                break

    def reply_with_typing(self, text: str) -> str:
        """Answer `text` while "typing…" shows, so the user always sees something is happening."""
        stop = threading.Event()
        pinger = threading.Thread(target=self._keep_typing, args=(stop,), name="tg-typing", daemon=True)
        pinger.start()
        try:
            return self.answer(text)
        finally:
            stop.set()

    def send(self, text: str) -> None:
        text = (text or "(no answer)").strip()
        limit = config.TELEGRAM_MAX_REPLY_CHARS
        if len(text) > limit:
            text = text[: limit - 20].rstrip() + "\n…(truncated)"
        try:
            notify.telegram_call("sendMessage", {"chat_id": config.TELEGRAM_CHAT_ID, "text": text,
                                                 "disable_web_page_preview": True})
        except RuntimeError as e:
            self.log.warning("reply failed: %s", e)

    def _own_message(self, update: dict) -> dict | None:
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return None
        chat = str((msg.get("chat") or {}).get("id", ""))
        if chat != str(config.TELEGRAM_CHAT_ID):
            self.log.info("ignored message from chat %s", chat)
            return None
        # never execute stale commands queued while KURAMA was off (e.g. old "hi", old "delete ...")
        if int(msg.get("date") or 0) < self.started - config.TELEGRAM_MAX_AGE_S:
            self.log.info("ignored stale message from %s", msg.get("date"))
            return None
        return msg

    # --- loop ---
    def tick(self) -> None:
        updates = list(self._backlog) or self.poll()
        self._backlog.clear()
        for u in updates:
            if self.stopping:
                break
            self.handle(u)

    def handle(self, update: dict) -> None:
        msg = self._own_message(update)
        if msg is None:
            return
        self.typing()  # at once: "typing…" shows even while a voice note transcribes or a file saves
        text = (msg.get("text") or "").strip()
        if not text:
            from jarvis.core import phone
            if msg.get("voice"):  # a voice note: Whisper turns it into text, then it's a normal message
                try:
                    text = phone.voice_text(msg)
                except Exception as e:
                    self.send(f"Sorry, I couldn't hear that voice note: {e}")
                    return
                if not text:
                    self.send("I couldn't make out any words in that voice note.")
                    return
                self.send(f"🎤 {text}")
            else:  # a file / photo / video: saved on the laptop (its caption may name the folder)
                self.send(phone.save_incoming(msg) or TEXT_ONLY)
                return
        self.handled += 1
        self.log.info("message (%d chars)", len(text))
        self.send(self.reply_with_typing(text))

    def answer(self, text: str) -> str:
        from jarvis.core import guard, phone
        if text.startswith("/"):
            cmd = text.split()[0].split("@")[0].lower()
            arg = text.split()[1].lower() if len(text.split()) > 1 else ""
            if cmd == "/status":
                from jarvis.core import overview
                return overview.status_all()
            if cmd == "/jobs":
                return jobs_text()
            if cmd == "/clip":
                return phone.clipboard_text()
            if cmd == "/screen":
                return phone.screenshot_to_phone()
            if cmd == "/guard":
                return guard.arm(arg == "on") if arg in ("on", "off") else guard.status()
            if cmd in ("/where", "/locate", "/find"):
                return guard.where()
            if cmd in ("/camera", "/photo"):
                return guard.send_photo()
            if cmd in ("/video", "/vid", "/rec", "/record"):
                return guard.send_clip(int(arg) if arg.isdigit() else 5)
            if cmd == "/here":
                from jarvis.core import geolocate
                label = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else "home"
                return geolocate.label_here(label)
            return HELP
        if m := phone.COPY.match(text):  # 0 tokens: phone -> laptop clipboard
            return phone.set_clipboard(m.group("t").strip())
        if phone.CLIP.match(text):
            return phone.clipboard_text()
        if phone.SCREEN.match(text):
            return phone.screenshot_to_phone()
        if phone.CAMERA.match(text):
            return guard.send_photo()
        if m := phone.VIDEO.match(text):
            return guard.send_clip(int(m.group("sec")) if m.group("sec") else 5)
        if phone.WHERE.match(text):
            return guard.where()
        if m := phone.HERE.match(text):
            from jarvis.core import geolocate
            return geolocate.label_here(m.group("label"))
        if phone.HELP_RE.match(text):
            return HELP
        if (m := PICK.match(text)) and (picked := self.pick_found(m.group(1))):
            return picked
        try:
            return self.agent().run(text, mode="text")
        except Exception as e:
            self.log.exception("agent failed")
            return f"Sorry, that failed: {type(e).__name__}: {str(e)[:200]}"

    @staticmethod
    def pick_found(choice: str) -> str | None:
        """Send item N (or all) of the last find_and_send list; None when there is no recent list."""
        from jarvis.core import safety
        from jarvis.tools.general import find_and_send as fs

        if not fs.last_list():
            return None
        res = safety.execute("find_and_send", {"pick": -1 if choice.lower() in ("all", "both") else int(choice)})
        return res.output if res.ok else (res.error or res.output)

    def agent(self):
        if self._agent is None:
            from jarvis.core import agent, safety  # lazy: LangChain only when needed

            safety.set_confirm_hook("telegram", self.confirm)
            self._agent = agent.Agent(confirm=safety.get_confirm("telegram"), channel="telegram")
        return self._agent

    # --- confirm hook (safety mode "telegram") ---
    def confirm(self, prompt: str) -> bool:
        from jarvis.core.safety import parse_yes_no

        with self._confirm_lock:
            self.send(f"{prompt}\nReply yes/no")
            deadline = time.monotonic() + config.TELEGRAM_CONFIRM_TIMEOUT_S
            while not self.stopping:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                updates = self.poll(timeout=int(min(config.TELEGRAM_POLL_TIMEOUT_S, max(1, left))))
                for i, u in enumerate(updates):
                    msg = self._own_message(u)
                    if msg is None:
                        continue
                    self._backlog.extend(updates[i + 1:])  # later messages are handled afterwards
                    ok = parse_yes_no(msg.get("text") or "") is True
                    self.send("OK, doing it." if ok else "OK, not doing it.")
                    return ok
            self.send("No answer, so I did not do it.")
            return False


def jobs_text(limit: int = 8) -> str:
    rows = store.jobs_list(limit)
    if not rows:
        return "No background jobs."
    return "\n".join(f"#{r['id']} [{r['status']}] {r['title']}" + (f" ({r['progress']})" if r.get("progress") else "")
                     for r in rows)


def status_text() -> str:
    from jarvis.workers import process_watch, resource_guard, status

    lines = [resource_guard.summary()]
    watches = store.watches_list(("active",), 10)
    lines.append("Watches: " + ("; ".join(process_watch.describe(w) for w in watches) if watches else "none"))
    active = store.jobs_list(5, ("queued", "running"))
    lines.append("Jobs: " + ("; ".join(f"#{r['id']} {r['title']} ({r['status']})" for r in active)
                             if active else "none running"))
    lines.append(status.summary())
    return "\n".join(lines)
