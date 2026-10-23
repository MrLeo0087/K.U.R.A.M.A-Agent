"""Groq chat client: streaming, retry/backoff on 429/5xx, smart->fast fallback, budget, logging.

Usage:
    reply = chat(msgs)                       # Reply (str(reply) == text)
    for delta in chat(msgs, stream=True): ...  # text deltas; generator returns the Reply
"""
from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

import groq

from jarvis.core import budget, config, store

log = logging.getLogger("jarvis.llm")

_client: Any = None
_sleep = time.sleep  # patched in tests


class LLMError(RuntimeError):
    """Raised when every model in the chain failed."""


@dataclass
class Reply:
    text: str
    model: str
    tool_calls: list[dict] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated: bool = False

    def __str__(self) -> str:
        return self.text


def get_client() -> Any:
    global _client
    if _client is None:
        if not config.GROQ_API_KEY:
            raise LLMError("GROQ_API_KEY missing: add it to .env")
        _client = groq.Groq(api_key=config.GROQ_API_KEY, max_retries=0, timeout=config.LLM_TIMEOUT_S)
    return _client


def set_client(client: Any) -> None:
    """Inject a client (tests) or reset with None."""
    global _client
    _client = client


# --- helpers ---
def _estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1 if text else 0


def _estimate_prompt(messages: list[dict]) -> int:
    total = 0
    for m in messages:
        c = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        total += _estimate_tokens(c if isinstance(c, str) else str(c or "")) + 4
    return total


def _status(err: Exception) -> int | None:
    return getattr(err, "status_code", None)


def _retryable(err: Exception) -> bool:
    if isinstance(err, (groq.RateLimitError, groq.InternalServerError, groq.APIConnectionError)):
        return True
    s = _status(err)
    return s is not None and (s == 429 or s >= 500)


_DUR = re.compile(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?$")


def _parse_duration(v: str) -> float | None:
    """Parse '7.5', '2m59.5s', '120ms' -> seconds."""
    v = (v or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        pass
    m = _DUR.match(v)
    if not m or not any(m.groups()):
        return None
    h, mi, s, ms = (float(x) if x else 0.0 for x in m.groups())
    return h * 3600 + mi * 60 + s + ms / 1000


def _retry_after(err: Exception) -> float | None:
    resp = getattr(err, "response", None)
    headers = getattr(resp, "headers", None) or {}
    if "retry-after-ms" in headers:
        try:
            return float(headers["retry-after-ms"]) / 1000
        except ValueError:
            pass
    for key in ("retry-after", "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
        if key in headers:
            d = _parse_duration(headers[key])
            if d is not None:
                return d
    return None


def _backoff(attempt: int) -> float:
    return min(config.LLM_MAX_WAIT_S, config.LLM_BACKOFF_BASE_S * (2 ** attempt) + random.uniform(0, 0.25))


def _chain(tier: str) -> list[str]:
    if tier not in config.TIER_CHAIN:
        raise ValueError(f"unknown tier {tier!r}; use one of {list(config.TIER_CHAIN)}")
    chain = config.TIER_CHAIN[tier]
    allowed = [m for m in chain if budget.allow(m)]
    if not allowed:  # all self-budgets spent: still try the cheapest; Groq enforces real limits
        log.warning("daily token budget exhausted for %s; trying %s anyway", chain, chain[-1])
        allowed = [chain[-1]]
    return allowed


def _log(model: str, purpose: str, p: int, c: int, t0: float, ok: bool, error: str = "",
         estimated: bool = False) -> None:
    try:
        store.log_llm(model, purpose, p, c, int((time.monotonic() - t0) * 1000), ok, error, estimated)
    except Exception as e:  # logging must never break a reply
        log.warning("store.log_llm failed: %s", e)


def _request(model: str, messages: list[dict], stream: bool, tools: list | None,
             max_tokens: int | None, temperature: float | None, extra: dict) -> dict:
    kw: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "max_tokens": max_tokens or config.LLM_MAX_TOKENS,
        "temperature": config.LLM_TEMPERATURE if temperature is None else temperature,
        **config.MODEL_PARAMS.get(model, {}),
        **extra,
    }
    if tools:
        kw["tools"] = tools
        kw.setdefault("tool_choice", "auto")
    return kw


def _plan_retry(err: Exception, attempt: int, retries: int, has_next: bool) -> float | None:
    """Return seconds to sleep before retrying the same model, or None to move on/stop."""
    if not _retryable(err) or attempt >= retries:
        return None
    wait = _retry_after(err)
    if wait is None:
        return _backoff(attempt)
    if wait > config.LLM_MAX_WAIT_S:
        return None  # too long: fall back (or fail) instead of hanging
    return wait


def _tool_calls_from_message(msg: Any) -> list[dict]:
    out = []
    for tc in getattr(msg, "tool_calls", None) or []:
        fn = getattr(tc, "function", None)
        out.append({"id": getattr(tc, "id", ""), "name": getattr(fn, "name", ""),
                    "arguments": getattr(fn, "arguments", "") or ""})
    return out


# --- public API ---
def chat(messages: list[dict], tier: str = "fast", stream: bool = False, tools: list | None = None,
         purpose: str = "", max_tokens: int | None = None, temperature: float | None = None,
         **extra: Any) -> Reply | Iterator[str]:
    """Chat completion on Groq. tier: "fast" | "smart" | "vision"."""
    models = _chain(tier)
    if stream:
        return _stream(models, messages, tools, purpose, max_tokens, temperature, extra)
    return _complete(models, messages, tools, purpose, max_tokens, temperature, extra)


def _complete(models, messages, tools, purpose, max_tokens, temperature, extra) -> Reply:
    client = get_client()
    last: Exception | None = None
    for i, model in enumerate(models):
        has_next = i < len(models) - 1
        retries = config.LLM_RETRIES_BEFORE_FALLBACK if has_next else config.LLM_MAX_RETRIES
        for attempt in range(retries + 1):
            t0 = time.monotonic()
            try:
                resp = client.chat.completions.create(
                    **_request(model, messages, False, tools, max_tokens, temperature, extra))
            except Exception as e:
                last = e
                _log(model, purpose, 0, 0, t0, False, f"{type(e).__name__}: {e}")
                wait = _plan_retry(e, attempt, retries, has_next)
                if wait is None:
                    if not _retryable(e):
                        raise LLMError(f"{model}: {e}") from e
                    break
                log.info("retry %s in %.1fs (%s)", model, wait, type(e).__name__)
                _sleep(wait)
                continue
            msg = resp.choices[0].message
            text = msg.content or ""
            usage = getattr(resp, "usage", None)
            est = usage is None
            p = getattr(usage, "prompt_tokens", 0) if usage else _estimate_prompt(messages)
            c = getattr(usage, "completion_tokens", 0) if usage else _estimate_tokens(text)
            _log(model, purpose, p, c, t0, True, estimated=est)
            return Reply(text, model, _tool_calls_from_message(msg), p, c, est)
        if has_next:
            log.warning("falling back %s -> %s", model, models[i + 1])
    raise LLMError(f"all models failed ({', '.join(models)}): {last}") from last


def _chunk_usage(chunk: Any) -> Any:
    xg = getattr(chunk, "x_groq", None)
    u = getattr(xg, "usage", None) if xg is not None else None
    return u or getattr(chunk, "usage", None)


def _merge_tool_deltas(acc: dict[int, dict], deltas: Any) -> None:
    for d in deltas or []:
        slot = acc.setdefault(getattr(d, "index", 0) or 0, {"id": "", "name": "", "arguments": ""})
        if getattr(d, "id", None):
            slot["id"] = d.id
        fn = getattr(d, "function", None)
        if fn is not None:
            slot["name"] += getattr(fn, "name", None) or ""
            slot["arguments"] += getattr(fn, "arguments", None) or ""


def _stream(models, messages, tools, purpose, max_tokens, temperature, extra):
    client = get_client()
    last: Exception | None = None
    for i, model in enumerate(models):
        has_next = i < len(models) - 1
        retries = config.LLM_RETRIES_BEFORE_FALLBACK if has_next else config.LLM_MAX_RETRIES
        for attempt in range(retries + 1):
            t0 = time.monotonic()
            parts: list[str] = []
            tool_acc: dict[int, dict] = {}
            usage = None
            started = False
            try:
                resp = client.chat.completions.create(
                    **_request(model, messages, True, tools, max_tokens, temperature, extra))
                for chunk in resp:
                    usage = _chunk_usage(chunk) or usage
                    choices = getattr(chunk, "choices", None)
                    if not choices:
                        continue
                    delta = choices[0].delta
                    _merge_tool_deltas(tool_acc, getattr(delta, "tool_calls", None))
                    text = getattr(delta, "content", None)
                    if text:
                        started = True
                        parts.append(text)
                        yield text
            except GeneratorExit:  # consumer stopped early (e.g. barge-in)
                full = "".join(parts)
                _log(model, purpose, _estimate_prompt(messages), _estimate_tokens(full), t0, True,
                     "aborted", estimated=True)
                raise
            except Exception as e:
                last = e
                _log(model, purpose, 0, 0, t0, False, f"{type(e).__name__}: {e}")
                if started:
                    raise LLMError(f"{model}: stream broke mid-reply: {e}") from e
                wait = _plan_retry(e, attempt, retries, has_next)
                if wait is None:
                    if not _retryable(e):
                        raise LLMError(f"{model}: {e}") from e
                    break
                log.info("retry %s in %.1fs (%s)", model, wait, type(e).__name__)
                _sleep(wait)
                continue
            full = "".join(parts)
            est = usage is None
            p = getattr(usage, "prompt_tokens", 0) if usage else _estimate_prompt(messages)
            c = getattr(usage, "completion_tokens", 0) if usage else _estimate_tokens(full)
            _log(model, purpose, p, c, t0, True, estimated=est)
            return Reply(full, model, [tool_acc[k] for k in sorted(tool_acc)], p, c, est)
        if has_next:
            log.warning("falling back %s -> %s", model, models[i + 1])
    raise LLMError(f"all models failed ({', '.join(models)}): {last}") from last
