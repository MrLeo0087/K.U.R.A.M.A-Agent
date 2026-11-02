"""Groq chat through LangChain (ChatGroq): per-model settings from config, our own retry/backoff on
429/5xx (retry-after aware), tier fallback chain, daily budget, and a callback handler that logs
every attempt (model, purpose, tokens, latency, ok/error) to SQLite.

Usage:
    reply = chat(msgs)                          # Reply (str(reply) == text, reply.message = AIMessage)
    for delta in chat(msgs, stream=True): ...   # text deltas; the generator returns the Reply
    model = get_chat_model("fast")              # configured runnable (ChatGroq + fallbacks + logging)

msgs may be LangChain messages or OpenAI-style dicts. All ChatGroq instances share one raw Groq
client (get_client), which also serves Whisper STT.
"""
from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Sequence
from uuid import UUID

import groq
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage, convert_to_messages
from langchain_groq import ChatGroq

from jarvis.core import budget, config, ratelimit, store

log = logging.getLogger("jarvis.llm")

_client: Any = None
_models: dict[str, Any] = {}  # ChatGroq, or ChatGoogleGenerativeAI for the Gemini fallback
_cool: dict[str, float] = {}  # model -> time until which it is skipped (its daily / per-minute limit is used up)
_models_lock = threading.Lock()
_sleep = time.sleep  # patched in tests

# MODEL_PARAMS keys that are ChatGroq fields; anything else goes to model_kwargs.
_CHATGROQ_FIELDS = {"reasoning_effort", "reasoning_format", "service_tier", "stop"}


class LLMError(RuntimeError):
    """Raised when every model in the chain failed."""


@dataclass
class Reply:
    text: str
    model: str
    tool_calls: list[dict] = field(default_factory=list)  # [{id, name, arguments (JSON str)}]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated: bool = False
    message: AIMessage | None = None

    def __str__(self) -> str:
        return self.text


# --- clients and models ---
def get_client() -> Any:
    global _client
    if _client is None:
        if not config.GROQ_API_KEY:
            raise LLMError("GROQ_API_KEY missing: add it to .env")
        http = groq.DefaultHttpxClient(event_hooks={"response": [_rate_headers]})
        _client = groq.Groq(api_key=config.GROQ_API_KEY, max_retries=0, timeout=config.LLM_TIMEOUT_S,
                            http_client=http)
    return _client


def _rate_headers(response: Any) -> None:
    """httpx response hook: feed Groq's x-ratelimit-* headers to the rate limiter."""
    try:
        if "x-ratelimit-remaining-tokens" not in response.headers:
            return
        model = json.loads(response.request.content or b"{}").get("model", "")
        ratelimit.update_from_headers(model, response.headers)
    except Exception as e:  # never break a request over bookkeeping
        log.debug("rate header hook failed: %s", e)


def set_client(client: Any) -> None:
    """Inject a raw Groq client (tests) or reset with None. Drops cached ChatGroq models."""
    global _client
    _client = client
    with _models_lock:
        _models.clear()


class _NoAsync:
    """Placeholder so ChatGroq does not build an unused async HTTP client."""

    def create(self, *a: Any, **k: Any) -> Any:
        raise NotImplementedError("KURAMA only uses the sync Groq client")


def model_settings(model: str) -> dict:
    params = dict(config.MODEL_PARAMS.get(model, {}))
    kw = {k: params.pop(k) for k in list(params) if k in _CHATGROQ_FIELDS}
    if params:
        kw["model_kwargs"] = params
    return kw


def is_gemini(model: str) -> bool:
    return model.startswith("gemini")


def _gemini(model: str) -> Any:
    """Google's Gemini through LangChain: the fallback after Groq's models (their daily limits)."""
    from langchain_google_genai import ChatGoogleGenerativeAI  # lazy: only when the fallback is used
    if not config.GEMINI_API_KEY:
        raise LLMError("GEMINI_API_KEY missing")
    return ChatGoogleGenerativeAI(model=model, google_api_key=config.GEMINI_API_KEY, temperature=config.LLM_TEMPERATURE,
                                  max_output_tokens=config.LLM_MAX_TOKENS, max_retries=0, timeout=config.LLM_TIMEOUT_S,
                                  **config.MODEL_PARAMS.get(model, {}))


def model_for(model: str) -> Any:
    """Cached chat model for one model id (max_retries=0: retries are ours)."""
    with _models_lock:
        m = _models.get(model)
        if m is None and is_gemini(model):
            m = _models[model] = _gemini(model)
        if m is None:
            m = ChatGroq(model=model, temperature=config.LLM_TEMPERATURE,
                         max_tokens=config.LLM_MAX_TOKENS, max_retries=0,
                         client=get_client().chat.completions, async_client=_NoAsync(),
                         **model_settings(model))
            _models[model] = m
    return m


def warm(tiers: Sequence[str] = ("fast", "smart", "voice")) -> None:
    """Build the ChatGroq objects up front so the first turn pays no setup cost."""
    try:
        for tier in tiers:
            for m in config.TIER_CHAIN.get(tier, []):
                model_for(m)
    except LLMError as e:  # no key yet: the first real call reports it
        log.warning("llm warm-up skipped: %s", e)


# --- logging callback ---
def _estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1 if text else 0


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p if isinstance(p, str) else str(p.get("text", "")) for p in content
                       if isinstance(p, (str, dict)))
    return str(content or "")


def _estimate_prompt(messages: Sequence[Any]) -> int:
    total = 0
    for m in messages:
        c = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
        total += _estimate_tokens(_content_text(c)) + 4
    return total


def _log(model: str, purpose: str, p: int, c: int, t0: float, ok: bool, error: str = "",
         estimated: bool = False) -> None:
    try:
        store.log_llm(model, purpose, p, c, int((time.monotonic() - t0) * 1000), ok, error, estimated)
    except Exception as e:  # logging must never break a reply
        log.warning("store.log_llm failed: %s", e)


class UsageLogger(BaseCallbackHandler):
    """Logs every chat-model run to SQLite from usage_metadata (estimates when missing)."""

    raise_error = False

    def __init__(self) -> None:
        self._runs: dict[UUID, dict] = {}
        self._lock = threading.Lock()

    def on_chat_model_start(self, serialized: dict, messages: list[list[BaseMessage]], *,
                            run_id: UUID, metadata: dict | None = None, **kw: Any) -> None:
        md = metadata or {}
        model = md.get("ls_model_name") or (kw.get("invocation_params") or {}).get("model", "")
        with self._lock:
            self._runs[run_id] = {"t0": time.monotonic(), "model": model, "chars": 0,
                                  "purpose": md.get("purpose", ""),
                                  "prompt": _estimate_prompt(messages[0] if messages else [])}

    def on_llm_new_token(self, token: str, *, run_id: UUID, **kw: Any) -> None:
        st = self._runs.get(run_id)
        if st is not None:
            st["chars"] += len(token or "")

    def on_llm_end(self, response: Any, *, run_id: UUID, **kw: Any) -> None:
        with self._lock:
            st = self._runs.pop(run_id, None)
        if st is None:
            return
        gen = response.generations[0][0] if response.generations and response.generations[0] else None
        usage = getattr(getattr(gen, "message", None), "usage_metadata", None)
        if usage:
            p, c, est = usage.get("input_tokens", 0), usage.get("output_tokens", 0), False
        else:
            p, c, est = st["prompt"], _estimate_tokens(getattr(gen, "text", "") or ""), True
        _log(st["model"], st["purpose"], p, c, st["t0"], True, estimated=est)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kw: Any) -> None:
        with self._lock:
            st = self._runs.pop(run_id, None)
        if st is None:
            return
        if isinstance(error, GeneratorExit):  # consumer stopped the stream early (barge-in)
            _log(st["model"], st["purpose"], st["prompt"], st["chars"] // 4 + 1, st["t0"], True,
                 "aborted", estimated=True)
        else:
            _log(st["model"], st["purpose"], 0, 0, st["t0"], False, f"{type(error).__name__}: {error}")


LOGGER = UsageLogger()


def _cfg(purpose: str) -> dict:
    return {"callbacks": [LOGGER], "metadata": {"purpose": purpose}}


def get_chat_model(tier: str = "fast", purpose: str = "") -> Any:
    """The tier's configured runnable: primary ChatGroq with fallbacks, logging attached."""
    chain = _chain(tier)
    primary = model_for(chain[0])
    runnable = primary.with_fallbacks([model_for(m) for m in chain[1:]]) if len(chain) > 1 else primary
    return runnable.with_config(_cfg(purpose))


# --- retry helpers ---
def _status(err: Exception) -> int | None:
    s = getattr(err, "status_code", None) or getattr(err, "code", None)
    if isinstance(s, int):
        return s
    m = re.search(r"\b(429|5\d\d)\b|RESOURCE_EXHAUSTED|UNAVAILABLE|DEADLINE_EXCEEDED", str(err)[:300])
    if m:  # Gemini errors carry the code in the message ("429 RESOURCE_EXHAUSTED", "504 DEADLINE_EXCEEDED")
        return int(m.group(1)) if m.group(1) else (429 if "EXHAUSTED" in m.group(0) else 503)
    return None


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


def _quota_wait(err: Exception) -> float:
    """How long a used-up quota stays used up, from the error text (Gemini: 'retryDelay': '27s', a PerDay quota)."""
    text = str(err)
    if re.search(r"per ?day", text, re.I):
        return 3600.0  # a daily quota: try again in an hour, not on every request (51ff16b4: 4 calls, then "all failed")
    m = re.search(r"retryDelay\W+(\d+(?:\.\d+)?)s", text)
    return float(m.group(1)) if m else config.LLM_COOLDOWN_S


def user_text(err: Exception) -> str:
    """What the owner hears when every model failed (not the raw error: 11-01 18:14 showed '401 Invalid API Key')."""
    low = str(err).lower()
    if "401" in low or "invalid api key" in low or "invalid_api_key" in low:
        return "My AI key was refused (wrong or revoked key in .env). Put the new key in .env and restart me."
    if any(w in low for w in ("rate", "429", "busy", "quota", "budget", "exhausted")):
        return "Sorry, my AI service is busy or rate-limited right now — please try again in a few seconds."
    return "Sorry, something went wrong on my side. Please try again."


def _backoff(attempt: int) -> float:
    return min(config.LLM_MAX_WAIT_S, config.LLM_BACKOFF_BASE_S * (2 ** attempt) + random.uniform(0, 0.25))


def _chain(tier: str) -> list[str]:
    if tier not in config.TIER_CHAIN:
        raise ValueError(f"unknown tier {tier!r}; use one of {list(config.TIER_CHAIN)}")
    from jarvis.core import modes
    level = modes.ai_level()
    if level == "off":
        raise LLMError("AI is off (No AI mode); switch the mode on the dashboard")
    if level == "fast" and tier == "smart":  # Light / Laptop only: the small model only
        tier = "fast"
    chain = config.TIER_CHAIN[tier]
    now = time.time()
    allowed = [m for m in chain if budget.allow(m) and _cool.get(m, 0) <= now]  # a used-up model isn't tried
    if not allowed:  # every model cooling down: still try them (a limit may have reset early)
        allowed = [m for m in chain if budget.allow(m)]
    if not allowed:  # all self-budgets spent: still try the cheapest; Groq enforces real limits
        log.warning("daily token budget exhausted for %s; trying %s anyway", chain, chain[-1])
        allowed = [chain[-1]]
    return allowed


def _plan_retry(err: Exception, attempt: int, retries: int) -> float | None:
    """Seconds to sleep before retrying the same model, or None to move on/stop."""
    if not _retryable(err) or attempt >= retries:
        return None
    wait = _retry_after(err)
    if wait is None and _status(err) == 429 and "quota" in str(err).lower():
        return None  # Gemini's "You exceeded your current quota" has no Retry-After: retrying wasted 2 calls a turn
    if wait is None:
        return _backoff(attempt)
    if wait > config.LLM_MAX_WAIT_S:
        return None  # too long: fall back (or fail) instead of hanging
    return wait


def _plan(models: list[str]) -> Iterator[tuple[int, str, int]]:
    """(index, model, retries) for each model in the chain, logging fallbacks."""
    for i, model in enumerate(models):
        if i:
            log.warning("falling back %s -> %s", models[i - 1], model)
        yield i, model, config.LLM_RETRIES_BEFORE_FALLBACK if i < len(models) - 1 else config.LLM_MAX_RETRIES


def _on_error(e: Exception, model: str, attempt: int, retries: int) -> bool:
    """Sleep and return True to retry this model; False to fall back to the NEXT model in the chain.
    We never raise here: a non-retryable error on one model (e.g. a 400, or that model being down) should
    still let the next model try. _complete/_stream raise LLMError only after every model has failed."""
    wait = _plan_retry(e, attempt, retries)
    if _status(e) == 429 and wait is None:  # its daily (or minute) limit is used up: skip it for a while instead
        cool = min(max(_retry_after(e) or _quota_wait(e), config.LLM_COOLDOWN_S), 3600)  # of failing first
        _cool[model] = time.time() + cool  # on every request (2 wasted calls per turn on 11-01 evening)
        log.warning("%s is rate-limited: skipped for %.0f s", model, cool)
        return False
    if wait is None:
        if not _retryable(e):
            log.warning("%s failed (%s): %s — trying the next model", model, type(e).__name__, str(e)[:120])
        return False  # move on to the next model in the chain
    log.info("retry %s in %.1fs (%s)", model, wait, type(e).__name__)
    _sleep(wait)
    return True


# --- requests ---
def _bound(model: str, tools: Sequence | None, max_tokens: int | None, temperature: float | None,
           extra: dict) -> Any:
    extra = dict(extra)
    tool_choice = extra.pop("tool_choice", None)
    m: Any = model_for(model)
    if tools:
        m = m.bind_tools(list(tools), tool_choice=tool_choice or "auto")
    if is_gemini(model):  # its own names; Groq-only settings (timeout per call, reasoning) are dropped
        kw = {"max_output_tokens": max_tokens or config.LLM_MAX_TOKENS}
        if temperature is not None:
            kw["temperature"] = temperature
        return m.bind(**kw)
    kw: dict[str, Any] = {"max_tokens": max_tokens or config.LLM_MAX_TOKENS, **extra}
    if temperature is not None:
        kw["temperature"] = temperature
    return m.bind(**kw)


def _reply(msg: Any, model: str) -> Reply:
    if msg is None:
        msg = AIMessage(content="")
    if not isinstance(msg, AIMessage):
        msg = AIMessage(content=msg.content, tool_calls=getattr(msg, "tool_calls", []) or [],
                        usage_metadata=getattr(msg, "usage_metadata", None))
    usage = msg.usage_metadata or {}
    calls = [{"id": tc.get("id") or "", "name": tc["name"],
              "arguments": json.dumps(tc.get("args") or {}, ensure_ascii=False)}
             for tc in msg.tool_calls]
    return Reply(_content_text(msg.content), model, calls, usage.get("input_tokens", 0),
                 usage.get("output_tokens", 0), not usage, msg)


def to_messages(messages: Sequence[Any]) -> list[BaseMessage]:
    return convert_to_messages(list(messages))


# --- public API ---
def chat(messages: Sequence[Any], tier: str = "fast", stream: bool = False, tools: Sequence | None = None,
         purpose: str = "", max_tokens: int | None = None, temperature: float | None = None,
         priority: str | None = None, **extra: Any) -> Reply | Iterator[str]:
    """Chat on Groq via ChatGroq. tier: "fast" | "smart" | "voice" | "vision".
    tools: LangChain tools (or OpenAI-format dicts); extra may hold tool_choice.
    priority: "interactive" | "background" for the rate limiter (default: the thread's context)."""
    models = _chain(tier)
    if tier == "voice":
        extra.setdefault("timeout", config.VOICE_TIMEOUT_S)
    msgs = to_messages(messages)
    rate = (priority or ratelimit.current_priority(), _estimate_prompt(msgs),
            max_tokens or config.LLM_MAX_TOKENS)
    if stream:
        return _stream(models, msgs, tools, purpose, max_tokens, temperature, extra, rate)
    return _complete(models, msgs, tools, purpose, max_tokens, temperature, extra, rate)


def _acquire(model: str, rate: tuple) -> ratelimit.Ticket:
    priority, prompt_est, max_tok = rate
    return ratelimit.acquire(model, prompt_est + max_tok, priority)


def _settle(ticket: ratelimit.Ticket, reply: Reply | None, rate: tuple) -> None:
    if reply is None:
        used = 0  # failed request: refund (a 429's headers already set the real level)
    elif reply.estimated:
        used = rate[1] + _estimate_tokens(reply.text)
    else:
        used = reply.prompt_tokens + reply.completion_tokens
    ratelimit.settle(ticket, used)


def _complete(models, msgs, tools, purpose, max_tokens, temperature, extra, rate) -> Reply:
    last: Exception | None = None
    for _, model, retries in _plan(models):
        for attempt in range(retries + 1):
            ticket = _acquire(model, rate)
            try:
                msg = _bound(model, tools, max_tokens, temperature, extra).invoke(
                    msgs, config=_cfg(purpose))
            except Exception as e:
                last = e
                _settle(ticket, None, rate)
                if _on_error(e, model, attempt, retries):
                    continue
                break
            reply = _reply(msg, model)
            _settle(ticket, reply, rate)
            return reply
    raise LLMError(f"all models failed ({', '.join(models)}): {last}") from last


def _stream(models, msgs, tools, purpose, max_tokens, temperature, extra, rate):
    last: Exception | None = None
    for _, model, retries in _plan(models):
        for attempt in range(retries + 1):
            acc = None
            started = False
            ticket = _acquire(model, rate)
            try:
                for chunk in _bound(model, tools, max_tokens, temperature, extra).stream(
                        msgs, config=_cfg(purpose)):
                    acc = chunk if acc is None else acc + chunk
                    text = _content_text(chunk.content)
                    if text:
                        started = True
                        yield text
            except GeneratorExit:  # consumer stopped early; closing propagates to ChatGroq (logged)
                raise
            except Exception as e:
                last = e
                if started:
                    raise LLMError(f"{model}: stream broke mid-reply: {e}") from e
                _settle(ticket, None, rate)
                if _on_error(e, model, attempt, retries):
                    continue
                break
            reply = _reply(acc, model)
            _settle(ticket, reply, rate)
            return reply
    raise LLMError(f"all models failed ({', '.join(models)}): {last}") from last


def structured(messages: Sequence[Any], schema: type, tier: str = "fast", purpose: str = "",
               max_tokens: int | None = None, priority: str | None = None) -> Any:
    """with_structured_output(schema) on the tier's chain (no retries: callers have a fallback).
    Returns the parsed Pydantic object; raises LLMError when every model failed."""
    msgs = to_messages(messages)
    rate = (priority or ratelimit.current_priority(), _estimate_prompt(msgs),
            max_tokens or config.LLM_MAX_TOKENS)
    last: Exception | None = None
    for _, model, _retries in _plan(_chain(tier)):
        ticket = _acquire(model, rate)
        try:
            base = model_for(model)
            if "max_tokens" in type(base).model_fields:
                base = base.model_copy(update={"max_tokens": rate[2]})
            elif "max_output_tokens" in type(base).model_fields:
                base = base.model_copy(update={"max_output_tokens": rate[2]})
            # Strict json_schema = constrained decoding: the reply is always valid JSON.
            # (function_calling on gpt-oss occasionally emits broken JSON -> Groq 400.)
            method = config.STRUCTURED_METHOD.get(model, "function_calling")
            kw = {"method": method, "strict": True} if method == "json_schema" else {"method": method}
            out = base.with_structured_output(schema, include_raw=True, **kw).invoke(
                msgs, config=_cfg(purpose))
        except Exception as e:
            last = e
            _settle(ticket, None, rate)
            log.debug("structured output failed on %s: %s", model, e)
            continue
        _settle(ticket, _reply(out.get("raw"), model), rate)
        if out.get("parsed") is None:
            last = out.get("parsing_error") or ValueError("no structured output")
            log.debug("structured output unparsable on %s: %s", model, last)
            continue
        return out["parsed"]
    raise LLMError(f"structured output failed ({tier}): {last}") from last
