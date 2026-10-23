"""Chat turns + web confirmations: the bridge between the blocking agent and the async API.

Each chat turn runs Agent.stream in its own thread and pushes events onto an asyncio.Queue that the
SSE response drains:
  {type:"delta", text} {type:"tool", name, ok, ms} {type:"confirm", id, prompt}
  {type:"confirm_timeout", id} {type:"error", text} {type:"done", text, route, tier, tokens, ms, lang}
Confirmations: a "web" confirm hook (also used for text/voice modes in this process, where stdin is
not the user) parks the agent thread on an Event until POST /api/v1/confirm or the timeout (deny).
The agent is imported lazily (first request, or a background warm-up) so the API itself stays light.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from jarvis.api.settings import Settings

log = logging.getLogger("jarvis.api")


@dataclass
class Turn:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue
    closed: bool = False  # client went away
    confirm_ids: list[str] = field(default_factory=list)

    def push(self, ev: dict | None) -> None:
        with contextlib.suppress(RuntimeError):  # loop already closed
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ev)


@dataclass
class Pending:
    prompt: str
    event: threading.Event = field(default_factory=threading.Event)
    answer: bool = False


def _route(r: Any) -> Any:
    if r is None or isinstance(r, (str, int, float, dict, list)):
        return r
    return {k: getattr(r, k) for k in ("groups", "method", "reasoning", "latency_ms") if hasattr(r, k)}


def _turn_tokens(ts0: float) -> int:
    try:
        from jarvis.core import store
        rows = store.llm_usage_between(ts0, time.time() + 1)
        return int(sum(r["total"] or 0 for r in rows if r["purpose"] != "stt"))
    except Exception:
        return 0


def _tool_ms(name: str, ts0: float, used: set[int]) -> int | None:
    try:
        from jarvis.core import store
        rows = [r for r in reversed(store.recent_tool_calls(20)) if (r["ts"] or 0) >= ts0 - 0.5]
    except Exception:
        return None
    for i, r in enumerate(rows):
        if i not in used and r["tool"] == name:
            used.add(i)
            return r["latency_ms"]
    return None


def reply_lang(text: str, hint: str | None = None) -> str:
    if hint:
        return hint
    try:
        from jarvis.core.stt import text_lang
        return text_lang(text) if text else "en"
    except Exception:
        return "en"


class Engine:
    """One agent conversation per process: turns are serialized, confirmations go to the browser."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.turn_lock = threading.Lock()
        self._load_lock = threading.Lock()
        self.current: Turn | None = None
        self.pending: dict[str, Pending] = {}
        self.hooked = False
        self.ready = False  # agent imported + warmed

    # --- confirmations ---
    def web_confirm(self, prompt: str) -> bool:
        """safety confirm hook: ask the browser of the running turn; no answer in time -> deny."""
        turn = self.current
        if turn is None or turn.closed:
            return False
        cid = uuid.uuid4().hex[:12]
        p = Pending(prompt)
        self.pending[cid] = p
        turn.confirm_ids.append(cid)
        turn.push({"type": "confirm", "id": cid, "prompt": prompt})
        try:
            answered = p.event.wait(self.settings.confirm_timeout_s)
            if not answered:
                turn.push({"type": "confirm_timeout", "id": cid})
            return bool(answered and p.answer)
        finally:
            self.pending.pop(cid, None)

    def answer(self, cid: str, yes: bool) -> bool:
        p = self.pending.get(cid)
        if p is None:
            return False
        p.answer = yes
        p.event.set()
        return True

    def deny_pending(self, turn: Turn) -> None:
        for cid in turn.confirm_ids:
            p = self.pending.get(cid)
            if p is not None:
                p.answer = False
                p.event.set()

    # --- agent ---
    def agent(self) -> Any:
        """Import the agent on first use and route confirmations to the browser."""
        with self._load_lock:
            from jarvis.core import agent as agent_mod
            from jarvis.core import safety
            if not self.hooked:
                for mode in ("web", "text", "voice"):  # stdin is not the user in this process
                    safety.set_confirm_hook(mode, self.web_confirm)
                self.hooked = True
        return agent_mod.get_agent()

    def warm(self) -> None:
        time.sleep(self.settings.warm_delay_s)
        try:
            a = self.agent()
            if hasattr(a, "warm"):
                a.warm()
            self.ready = True
        except Exception as e:  # best effort; the first chat retries
            log.warning("agent warm-up failed: %s", e)

    # --- one turn (worker thread) ---
    def _emit_tools(self, turn: Turn, ag: Any, seen: int, ts0: float, used: set[int]) -> int:
        tools = (getattr(ag, "last", None) or {}).get("tools") or []
        for t in tools[seen:]:
            turn.push({"type": "tool", "name": t.get("name"), "ok": bool(t.get("ok")),
                       "ms": t.get("ms", _tool_ms(str(t.get("name")), ts0, used))})
        return max(seen, len(tools))

    def run_turn(self, turn: Turn, text: str, mode: str, lang: str | None) -> None:
        t0, ts0 = time.monotonic(), time.time()
        with self.turn_lock:
            self.current = turn
            try:
                ag = self.agent()
                seen, used, parts = 0, set(), []
                for delta in ag.stream(text, mode=mode, lang=lang):
                    seen = self._emit_tools(turn, ag, seen, ts0, used)
                    if turn.closed:
                        break  # closing the generator tells the agent to stop
                    if delta:
                        parts.append(delta)
                        turn.push({"type": "delta", "text": delta})
                self._emit_tools(turn, ag, seen, ts0, used)
                last = getattr(ag, "last", None) or {}
                tier = last.get("tier") or ("fastpath" if last.get("fastpath") else "")
                reply = "".join(parts).strip()
                turn.push({"type": "done", "text": reply, "route": _route(last.get("route")), "tier": tier,
                           "tokens": _turn_tokens(ts0), "ms": int((time.monotonic() - t0) * 1000),
                           "lang": reply_lang(reply, last.get("lang") or lang)})
            except Exception as e:
                log.exception("chat turn failed")
                turn.push({"type": "error", "text": f"Something went wrong: {type(e).__name__}: {str(e)[:200]}"})
                turn.push({"type": "done", "text": "", "route": None, "tier": "", "tokens": _turn_tokens(ts0),
                           "ms": int((time.monotonic() - t0) * 1000), "lang": lang or "en"})
            finally:
                self.current = None
                self.deny_pending(turn)
                turn.push(None)
