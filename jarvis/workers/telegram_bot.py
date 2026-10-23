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
import threading
import time

from jarvis.core import config, notify, store
from jarvis.workers.base import Worker

OFFSET_KEY = "telegram_offset"
HELP = ("I'm Jarvis. Send a question or command as text.\n"
        "/status: system resources, watches, jobs and workers\n"
        "/jobs: background jobs\n/help: this message\n"
        "Risky actions ask 'Reply yes/no' first. Only text is supported.")
TEXT_ONLY = "Sorry, only text messages are supported."


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
        # never execute stale commands queued while Jarvis was off (e.g. old "hi", old "delete ...")
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
        text = (msg.get("text") or "").strip()
        if not text:
            self.send(TEXT_ONLY)
            return
        self.handled += 1
        self.log.info("message (%d chars)", len(text))
        self.send(self.answer(text))

    def answer(self, text: str) -> str:
        if text.startswith("/"):
            cmd = text.split()[0].split("@")[0].lower()
            if cmd == "/status":
                return status_text()
            if cmd == "/jobs":
                return jobs_text()
            return HELP
        try:
            return self.agent().run(text, mode="text")
        except Exception as e:
            self.log.exception("agent failed")
            return f"Sorry, that failed: {type(e).__name__}: {str(e)[:200]}"

    def agent(self):
        if self._agent is None:
            from jarvis.core import agent, safety  # lazy: LangChain only when needed

            safety.set_confirm_hook("telegram", self.confirm)
            self._agent = agent.Agent(confirm=safety.get_confirm("telegram"))
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
