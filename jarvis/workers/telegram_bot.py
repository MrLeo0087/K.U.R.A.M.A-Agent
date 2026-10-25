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
    "/history [phone|laptop] — where it's been (share your live location with me to build the phone's trail)\n"
    "/track on | off — log the laptop often and message you on each move (lost mode)\n"
    "\n📋 Clipboard & files\n"
    "copy: <text> — put text on the laptop's clipboard\n"
    "/clip — get the laptop's clipboard\n"
    "Send a file/photo — saved on the laptop (caption 'to <folder>' picks the folder)\n"
    "\n⚙️ Status & work\n"
    "/status (or 'status') — training epochs/accuracy/ETA, jobs, downloads...\n"
    "'stop training' / 'stop training now' — stop a run (asks first)\n"
    "/jobs — background jobs\n"
    "\n🖥 Remote control\n"
    "/control (or 'start remote desktop') — turn on RustDesk; the password works for 15 min\n"
    "/changepass — new remote desktop password (asks your PIN every time)\n"
    "/control off (or 'stop remote desktop') — kill the password now\n"
    "\n🔒 Security\n"
    "/lock — block all risky actions (use if your phone is lost)\n"
    "/unlock <pin> — unlock after /lock\n"
    "Risky actions (camera, send files, shutdown, location, remote desktop) ask for your PIN once per 30 min.\n"
    "\n⚙️ Chat control\n"
    "/stop — stop a stuck task and reset the chat\n"
    "/clear — clear this chat + reminders/alarms (keeps what I know about you)\n"
    "/clearchat — clear just this conversation\n"
    "/reset — wipe everything and start fresh (keeps your password + settings)\n"
    "\n/help — this list\nRisky actions ask 'Reply yes/no' first.")
TEXT_ONLY = "Sorry, I can't use that kind of message."
# a reply to find_and_send's numbered list: "2", "send 2", "number 2", "all", "send all" (0 tokens)
PICK = re.compile(r"^\s*(?:send\s+)?(?:(?:no\.?|number|file)\s*)?(\d{1,2}|all|both)\s*[.!]?\s*$", re.I)


class TelegramBot(Worker):
    name = "telegram_bot"
    interval_s = 5.0

    def next_delay(self) -> float:
        # poll back-to-back: getUpdates already long-polls (blocking, ~0 CPU), so there's no reason to sleep 5 s
        # between polls — that sleep was adding up to 5 s before a command (camera/screenshot/…) was even picked up
        return 0.2 if not self.errors else super().next_delay()

    def __init__(self, interval_s: float | None = None):
        super().__init__(interval_s)
        self.offset = 0
        self._agent = None
        self._pending_risky: str | None = None  # a risky message waiting for the PIN
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
                                                      "allowed_updates": ["message", "edited_message"]},
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
        """Answer `text` while "typing…" shows, but never hang forever: a reply that takes longer than
        config.TELEGRAM_ANSWER_TIMEOUT_S is given up on (so "typing…" can't run for an hour)."""
        stop = threading.Event()
        pinger = threading.Thread(target=self._keep_typing, args=(stop,), name="tg-typing", daemon=True)
        pinger.start()
        box: dict = {}

        def run() -> None:
            try:
                box["out"] = self.answer(text)
            except Exception as e:
                box["out"] = f"Sorry, that failed: {type(e).__name__}: {str(e)[:200]}"

        worker = threading.Thread(target=run, name="tg-answer", daemon=True)
        worker.start()
        worker.join(config.TELEGRAM_ANSWER_TIMEOUT_S)
        stop.set()
        if worker.is_alive():  # still running after the timeout: don't wait, tell the user
            try:
                self.agent().abort()
            except Exception:
                pass
            return ("That took too long and I stopped waiting on it. Try a simpler request, or send /stop to reset. "
                    "(A big job like writing or a scan keeps running in the background and I'll tell you when it's done.)")
        return box.get("out") or "(no answer)"

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
    _TRANSIENT = ("ReadTimeout", "ConnectTimeout", "ConnectError", "RemoteProtocolError", "Bad Gateway",
                  "Too Many Requests", "Gateway Timeout", "Service Unavailable", "name resolution")

    def tick(self) -> None:
        try:
            updates = list(self._backlog) or self.poll()
        except RuntimeError as e:
            if not any(w in str(e) for w in self._TRANSIENT):
                raise
            # a network blip (Wi-Fi waking up, Telegram 502/429): one quiet line and a short retry, instead of a
            # traceback and an exponential backoff that kept the bot deaf for up to 80 s
            self.log.warning("telegram poll: %s (retrying)", str(e)[:120])
            self._stop.wait(3 if "Too Many" not in str(e) else 6)
            return
        self._backlog.clear()
        for u in updates:
            if self.stopping:
                break
            self.handle(u)

    def handle(self, update: dict) -> None:
        msg = self._own_message(update)
        if msg is None:
            return
        if msg.get("location"):  # a shared pin or a live-location update from the phone -> the phone's trail
            from jarvis.core import locationlog
            loc = msg["location"]
            live = bool(loc.get("live_period")) or bool((update.get("edited_message")))
            pt = locationlog.record_phone(loc["latitude"], loc["longitude"], int(loc.get("horizontal_accuracy") or 0), live)
            if not update.get("edited_message"):  # reply only to the first share, not every live update
                self.send("📍 Got your phone's location — I'll keep a trail while you share it. /history phone to see it."
                          if pt else "📍 Location received (same spot as before).")
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
        # --- security: lock switch + PIN for risky actions ---
        from jarvis.core import telesec
        low = text.strip().lower()
        if low.startswith("/lock") or low in ("lock kurama", "lock"):
            self._pending_risky = None
            self.send(telesec.lock())
            return
        if low.startswith("/unlock"):
            parts = text.split(maxsplit=1)
            self.send(telesec.unlock(parts[1] if len(parts) > 1 else ""))
            return
        if self._pending_risky and telesec.looks_like_pin(text):  # a PIN answering a held-back risky action
            if telesec.verify_pin(text.strip().lstrip("/")):
                pending, self._pending_risky = self._pending_risky, None
                self.send("PIN accepted.")
                self.send(self.reply_with_typing(pending))
            else:
                self.send("Wrong PIN. The action was not run.")
            return
        if telesec.looks_like_pin(text) and telesec.verify_pin(text.strip().lstrip("/")):
            self.send(f"PIN accepted — risky actions unlocked for {int(config.TELEGRAM_PIN_WINDOW_S // 60)} min.")
            return
        if (gated := telesec.gate(text)) is not None:
            self._pending_risky = text  # the next PIN runs it
            self.send(gated)
            return
        self.send(self.reply_with_typing(text))

    def answer(self, text: str) -> str:
        from jarvis.core import guard, phone, remotedesk
        if remotedesk.wants_password(text):  # only reached after the PIN (telesec.gate): a fresh password each time
            return remotedesk.status_text(remotedesk.start())
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
            if cmd in ("/history", "/trail"):
                from jarvis.core import locationlog
                dev = "laptop" if arg.startswith("laptop") else "phone"
                hrs = next((int(w) for w in text.split()[1:] if w.isdigit()), 24)
                return locationlog.summary(dev, hrs)
            if cmd == "/track":  # lost mode for the laptop (the phone uses Find My Device / live-location sharing)
                from jarvis.core import locationlog
                return locationlog.set_lost("laptop", arg != "off")
            if cmd == "/stop":  # abort the current task and reset the conversation so you can start again
                try:
                    self.agent().abort()
                except Exception:
                    pass
                from jarvis.core import reset
                return reset.clear_chat(self._agent) + "\nStopped. Send a new message anytime."
            if cmd in ("/clear", "/clearchat", "/clear_chat", "/new"):
                from jarvis.core import reset
                return reset.clear_chat(self._agent) if "chat" in cmd or cmd == "/new" else reset.clear_recent(self._agent)
            if cmd in ("/reset", "/wipe"):
                from jarvis.core import reset
                return reset.reset_all(self._agent)
            if cmd in ("/help", "/start", "/commands", "/command", "/?", "/menu"):
                return HELP
            # any other "/…" (a file path like /home/leo/x.pdf, a name, a typo) is NOT a command: let the agent handle
            # it instead of dumping the command list
        if m := phone.COPY.match(text):  # 0 tokens: phone -> laptop clipboard
            return phone.set_clipboard(m.group("t").strip())
        if phone.CLIP.match(text):
            return phone.clipboard_text()
        if phone.SCREEN.match(text):
            return phone.screenshot_to_phone()
        # "send this folder" / "send X folder in Y" / "send it" (after we discussed a folder) -> send that, reliably
        # (0 tokens, before the resend/LLM path) so it never asks for a chat id or sends a random file
        from jarvis.core import fastpath
        if config.FASTPATH:
            if si := fastpath.sendfile_intent(fastpath.normalize(text)):
                from jarvis.tools.general.send_file_telegram import send_file_telegram
                return send_file_telegram(**si.args)
        if phone.RESEND.match(text):  # "send that / send it again" -> resend the last photo/video/screenshot
            return phone.resend_last()
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
