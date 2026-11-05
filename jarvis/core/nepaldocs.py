"""The owner's Nepal documents service (a RAG API over thousands of Nepal legal and general-knowledge documents:
citizenship, passport, marriage and divorce, traffic rules and fines, land, the constitution, districts...). It
answers a question with a ready answer and its sources, in 5-15 s, so KURAMA asks it in a background job and the
answer arrives in the chat by itself.

    POST {KURAMA_RAG_API_URL}/ask   {"query": "..."}   header X-API-Key: KURAMA_RAG_API_KEY (both in .env)
    -> server-sent events: status {stage, message} ... token {token} ... done {answer, sources} (or error {detail})

Answers are cached for a few hours (the documents don't change by the hour). 0 KURAMA tokens: the service pays.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Callable

from jarvis.core import config

_cache: dict[str, tuple[float, str]] = {}
_lock = threading.Lock()


def settings() -> tuple[str, str]:
    """(url, key) from the environment / .env ('' when not set)."""
    url, key = os.getenv("KURAMA_RAG_API_URL", ""), os.getenv("KURAMA_RAG_API_KEY", "")
    if not url:
        try:
            from dotenv import dotenv_values
            env = dotenv_values(config.ROOT / ".env")
            url, key = env.get("KURAMA_RAG_API_URL") or "", env.get("KURAMA_RAG_API_KEY") or ""
        except Exception:  # noqa: BLE001
            pass
    return url.rstrip("/"), key


def ask(question: str, status: Callable[[str], None] | None = None) -> str:
    """The service's full answer (+ its sources in one line), or a sentence saying what went wrong."""
    q = " ".join((question or "").split())
    key = q.lower()
    with _lock:
        hit = _cache.get(key)
    if hit and time.time() - hit[0] < config.NEPAL_DOCS_CACHE_S:
        return hit[1]
    url, api_key = settings()
    if not url:
        return "error: the Nepal documents service isn't set up (KURAMA_RAG_API_URL in .env)."
    import httpx  # lazy
    parts: list[str] = []
    answer, sources = "", []
    try:
        with httpx.Client(timeout=httpx.Timeout(config.NEPAL_DOCS_TIMEOUT_S, connect=10.0)) as c, \
                c.stream("POST", f"{url}/ask", json={"query": q}, headers={"X-API-Key": api_key}) as r:
            r.raise_for_status()
            if "text/event-stream" not in r.headers.get("content-type", ""):
                data = json.loads(r.read() or b"{}")
                answer, sources = data.get("answer") or "", data.get("sources") or []
            else:
                event = None
                for line in r.iter_lines():
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("data:") and event:
                        data = json.loads(line[5:].strip() or "{}")
                        if event == "status" and status:
                            status(str(data.get("message") or ""))
                        elif event == "token":
                            parts.append(data.get("token", ""))
                        elif event == "done":
                            answer = "".join(parts) or data.get("answer") or ""
                            sources = data.get("sources") or []
                            break
                        elif event == "error":
                            return f"error: the Nepal documents service said: {data.get('detail', 'unknown error')}"
                    elif not line:
                        event = None
                answer = answer or "".join(parts)
    except httpx.TimeoutException:
        return "error: the Nepal documents service didn't answer in time. Try again in a minute."
    except httpx.HTTPError as e:
        return f"error: couldn't reach the Nepal documents service ({type(e).__name__})."
    answer = answer.strip()
    if not answer:
        return "I couldn't find that in the Nepal documents."
    names = []
    for s in sources[:3]:
        n = s.get("title") or s.get("document") or s.get("source") or s.get("name") if isinstance(s, dict) else str(s)
        if n and n not in names:
            names.append(str(n)[:80])
    out = answer + (f"\n\nSources: {'; '.join(names)}" if names else "")
    with _lock:
        _cache[key] = (time.time(), out)
        if len(_cache) > 100:
            _cache.pop(next(iter(_cache)))
    return out
