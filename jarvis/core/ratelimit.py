"""Thread-safe per-model token buckets for the Groq free tier (TPM + RPM).

acquire(model, est_tokens, priority) reserves tokens before a call; settle(ticket, actual) fixes the
estimate afterwards (from usage_metadata). Response headers (x-ratelimit-remaining-tokens) are
authoritative when the client hook sees them. Background callers must leave
config.RATE_BACKGROUND_RESERVE of the bucket free for interactive calls and wait otherwise;
interactive calls never wait while the bucket is fine (and at most RATE_INTERACTIVE_MAX_WAIT_S).
A thread-local context sets the default priority and a cancel event for job threads.
"""
from __future__ import annotations

import contextlib
import logging
import threading
import time
from dataclasses import dataclass
from typing import Iterator

from jarvis.core import config

log = logging.getLogger("jarvis.ratelimit")

INTERACTIVE, BACKGROUND = "interactive", "background"
_clock = time.monotonic  # patched in tests
_sleep_step = 0.25  # seconds between re-checks while waiting


class Cancelled(Exception):
    """The waiting background job was cancelled."""


@dataclass
class Ticket:
    model: str
    est: int
    t: float
    waited: float = 0.0


class Bucket:
    def __init__(self, tpm: int, rpm: int):
        self.tpm, self.rpm = max(1, tpm), max(1, rpm)
        self.tokens, self.requests = float(self.tpm), float(self.rpm)
        self.t = _clock()
        self.header_t = 0.0  # last time headers set the token level

    def refill(self, now: float) -> None:
        dt = max(0.0, now - self.t)
        self.tokens = min(self.tpm, self.tokens + dt * self.tpm / 60.0)
        self.requests = min(self.rpm, self.requests + dt * self.rpm / 60.0)
        self.t = now

    def fits(self, est: int, priority: str) -> bool:
        if priority == BACKGROUND:
            r = config.RATE_BACKGROUND_RESERVE
            return self.tokens - est >= r * self.tpm and self.requests - 1 >= r * self.rpm
        return self.tokens >= min(est, self.tpm) and self.requests >= 1

    def need_s(self, est: int, priority: str) -> float:
        """Seconds until `fits` would hold (rough, for sleeping)."""
        r = config.RATE_BACKGROUND_RESERVE if priority == BACKGROUND else 0.0
        tok_gap = (min(est, self.tpm) + r * self.tpm) - self.tokens
        req_gap = (1 + r * self.rpm) - self.requests
        return max(0.0, tok_gap * 60.0 / self.tpm, req_gap * 60.0 / self.rpm)


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, Bucket] = {}
        self._cond = threading.Condition()

    def bucket(self, model: str) -> Bucket:
        b = self._buckets.get(model)
        if b is None:
            lim = config.MODEL_LIMITS.get(model, {})
            b = self._buckets[model] = Bucket(lim.get("tpm", config.MODEL_TPM),
                                              lim.get("rpm", config.MODEL_RPM))
        return b

    def acquire(self, model: str, est_tokens: int, priority: str | None = None,
                cancel: threading.Event | None = None, timeout: float | None = None) -> Ticket:
        priority = priority or current_priority()
        cancel = cancel if cancel is not None else current_cancel()
        est = max(1, int(est_tokens))
        t0 = _clock()
        max_wait = config.RATE_INTERACTIVE_MAX_WAIT_S if priority != BACKGROUND else timeout
        with self._cond:
            while True:
                now = _clock()
                b = self.bucket(model)
                b.refill(now)
                waited = now - t0
                if b.fits(est, priority) or (max_wait is not None and waited >= max_wait):
                    b.tokens -= est
                    b.requests -= 1
                    if waited > 0.05:
                        log.info("%s waited %.1fs for %s (%d tokens)", priority, waited, model, est)
                    return Ticket(model, est, now, waited)
                if cancel is not None and cancel.is_set():
                    raise Cancelled(f"cancelled while waiting for {model}")
                step = min(max(b.need_s(est, priority), 0.01), _sleep_step)
                if max_wait is not None:
                    step = min(step, max(0.01, max_wait - waited))
                self._cond.wait(step)

    def settle(self, ticket: Ticket, actual_tokens: int) -> None:
        """Replace the estimate with the real usage (unless headers already set the level)."""
        with self._cond:
            b = self.bucket(ticket.model)
            if b.header_t >= ticket.t and b.header_t > 0:
                return
            b.tokens = min(b.tpm, b.tokens + ticket.est - max(0, int(actual_tokens)))
            self._cond.notify_all()

    def update_from_headers(self, model: str, headers: dict) -> None:
        """Groq: x-ratelimit-remaining-tokens is the per-minute token level (requests are per day)."""
        rem = headers.get("x-ratelimit-remaining-tokens")
        if rem is None or not model:
            return
        try:
            remaining = float(rem)
        except (TypeError, ValueError):
            return
        with self._cond:
            b = self.bucket(model)
            lim = headers.get("x-ratelimit-limit-tokens")
            if lim and str(lim).isdigit() and model not in config.MODEL_LIMITS:
                b.tpm = int(lim)
            now = _clock()
            b.refill(now)
            b.tokens = min(b.tpm, remaining)
            b.header_t = now
            self._cond.notify_all()

    def available(self, model: str) -> float:
        with self._cond:
            b = self.bucket(model)
            b.refill(_clock())
            return b.tokens

    def reset(self) -> None:
        with self._cond:
            self._buckets.clear()


LIMITER = RateLimiter()
acquire = LIMITER.acquire
settle = LIMITER.settle
update_from_headers = LIMITER.update_from_headers
available = LIMITER.available
reset = LIMITER.reset

_local = threading.local()


def current_priority() -> str:
    return getattr(_local, "priority", None) or INTERACTIVE


def current_cancel() -> threading.Event | None:
    return getattr(_local, "cancel", None)


@contextlib.contextmanager
def context(priority: str = BACKGROUND, cancel: threading.Event | None = None) -> Iterator[None]:
    """Default priority (and cancel event) for every LLM call made by this thread."""
    old = (getattr(_local, "priority", None), getattr(_local, "cancel", None))
    _local.priority, _local.cancel = priority, cancel
    try:
        yield
    finally:
        _local.priority, _local.cancel = old
