"""Basic web test UI for Jarvis: `python -m jarvis.server [--port 8000]` -> http://127.0.0.1:8000

Localhost only (the agent can run tools on this laptop). The page lives in jarvis/ui/web (vanilla JS).
The agent is imported lazily (first request, or a background warm-up shortly after startup) so the
server itself stays light. Each chat turn runs the blocking agent in its own thread and streams
Server-Sent Events back:
  {type:"delta", text} {type:"tool", name, ok, ms} {type:"confirm", id, prompt}
  {type:"confirm_timeout", id} {type:"error", text} {type:"done", text, route, tier, tokens, ms}
Confirmations: a "web" confirm hook (also used for text/voice modes in this process, where stdin
is not the user) parks the agent thread on an Event until POST /api/confirm or the timeout (deny).
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import logging
import subprocess
import sys
import threading
import time
import uuid
import wave
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from jarvis.ui import settings

log = logging.getLogger("jarvis.server")
LANGS = ("en", "ne", "hi")
STATIC = {"app.js": "application/javascript", "style.css": "text/css"}


# --- turn + confirmation plumbing (agent thread <-> event loop) ---
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


_turn_lock = threading.Lock()  # one agent turn at a time (the agent keeps one conversation)
_load_lock = threading.Lock()
_current: Turn | None = None
_pending: dict[str, Pending] = {}
_hooked = False
_ready = False  # agent imported + warmed


def web_confirm(prompt: str) -> bool:
    """safety confirm hook: ask the browser of the running turn; no answer in time -> deny."""
    turn = _current
    if turn is None or turn.closed:
        return False
    cid = uuid.uuid4().hex[:12]
    p = Pending(prompt)
    _pending[cid] = p
    turn.confirm_ids.append(cid)
    turn.push({"type": "confirm", "id": cid, "prompt": prompt})
    try:
        answered = p.event.wait(settings.CONFIRM_TIMEOUT_S)
        if not answered:
            turn.push({"type": "confirm_timeout", "id": cid})
        return bool(answered and p.answer)
    finally:
        _pending.pop(cid, None)


def _deny_pending(turn: Turn) -> None:
    for cid in turn.confirm_ids:
        p = _pending.get(cid)
        if p is not None:
            p.answer = False
            p.event.set()


def _agent() -> Any:
    """Import the agent on first use and route confirmations to the browser."""
    global _hooked
    with _load_lock:
        from jarvis.core import agent as agent_mod
        from jarvis.core import safety
        if not _hooked:
            for mode in ("web", "text", "voice"):  # stdin is not the user in this process
                safety.set_confirm_hook(mode, web_confirm)
            _hooked = True
    return agent_mod.get_agent()


def _warm() -> None:
    global _ready
    time.sleep(settings.WARM_DELAY_S)
    try:
        a = _agent()
        if hasattr(a, "warm"):
            a.warm()
        _ready = True
    except Exception as e:  # warm-up is best effort; the first chat retries
        log.warning("agent warm-up failed: %s", e)


# --- chat turn (runs in a worker thread) ---
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


def _emit_tools(turn: Turn, ag: Any, seen: int, ts0: float, used: set[int]) -> int:
    tools = (getattr(ag, "last", None) or {}).get("tools") or []
    for t in tools[seen:]:
        turn.push({"type": "tool", "name": t.get("name"), "ok": bool(t.get("ok")),
                   "ms": t.get("ms", _tool_ms(str(t.get("name")), ts0, used))})
    return max(seen, len(tools))


def _run_turn(turn: Turn, text: str, mode: str, lang: str | None) -> None:
    global _current
    t0, ts0 = time.monotonic(), time.time()
    with _turn_lock:
        _current = turn
        try:
            ag = _agent()
            seen, used, parts = 0, set(), []
            for delta in ag.stream(text, mode=mode, lang=lang):
                seen = _emit_tools(turn, ag, seen, ts0, used)
                if turn.closed:
                    break  # closing the generator tells the agent to stop
                if delta:
                    parts.append(delta)
                    turn.push({"type": "delta", "text": delta})
            _emit_tools(turn, ag, seen, ts0, used)
            last = getattr(ag, "last", None) or {}
            tier = last.get("tier") or ("fastpath" if last.get("fastpath") else "")
            turn.push({"type": "done", "text": "".join(parts).strip(), "route": _route(last.get("route")),
                       "tier": tier, "tokens": _turn_tokens(ts0), "ms": int((time.monotonic() - t0) * 1000)})
        except Exception as e:
            log.exception("chat turn failed")
            turn.push({"type": "error", "text": f"Something went wrong: {type(e).__name__}: {str(e)[:200]}"})
            turn.push({"type": "done", "text": "", "route": None, "tier": "", "tokens": _turn_tokens(ts0),
                       "ms": int((time.monotonic() - t0) * 1000)})
        finally:
            _current = None
            _deny_pending(turn)
            turn.push(None)


# --- status ---
def _rss_mb() -> float:
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 1048576, 1)
    except Exception:
        return 0.0


def _status() -> dict:
    from jarvis.core import config, store
    out: dict[str, Any] = {"rss_mb": _rss_mb(), "agent_loaded": "jarvis.core.agent" in sys.modules,
                           "agent_ready": _ready, "busy": _turn_lock.locked(),
                           "pending_confirms": len(_pending), "refresh_s": settings.STATUS_REFRESH_S,
                           "jobs": [], "alerts": [], "workers": None, "tokens": {}, "profile_facts": 0}
    with contextlib.suppress(Exception):
        out["jobs"] = [{k: j.get(k) for k in ("id", "title", "kind", "status", "progress", "created")}
                       for j in store.jobs_list(settings.STATUS_JOBS, ("queued", "running"))]
    with contextlib.suppress(Exception):
        out["alerts"] = [{k: a.get(k) for k in ("id", "ts", "title", "text", "level", "source")}
                         for a in store.alerts_recent(settings.STATUS_ALERTS)]
    with contextlib.suppress(Exception):
        p = config.WORKERS_STATUS_PATH
        if p.exists():
            out["workers"] = json.loads(p.read_text())
    with contextlib.suppress(Exception):
        from jarvis.core import usage
        s = usage.summary("today")
        out["tokens"] = {"today": s.get("tokens", 0), "calls": s.get("calls", 0),
                         "fastpath_hits": s.get("fastpath_hits", 0), "saved_est": s.get("tokens_saved_est", 0),
                         "budget_pct": s.get("budget_pct_today", {})}
    with contextlib.suppress(Exception):
        out["profile_facts"] = len(store.profile_all())
    return out


# --- audio ---
def _is_wav16k_mono(data: bytes) -> bool:
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return False
    try:
        with wave.open(io.BytesIO(data)) as w:
            return w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2
    except Exception:
        return False


def to_wav16k(data: bytes) -> bytes:
    """Any browser recording (webm/ogg/wav) -> 16 kHz mono 16-bit wav via ffmpeg (skipped if already)."""
    if _is_wav16k_mono(data):
        return data
    proc = subprocess.run([settings.FFMPEG, "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                           "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", "-f", "wav", "pipe:1"],
                          input=data, capture_output=True, timeout=settings.FFMPEG_TIMEOUT_S, check=False)
    if proc.returncode != 0 or len(proc.stdout) < 44:
        raise ValueError(f"ffmpeg could not decode the audio: {proc.stderr.decode(errors='replace')[:200]}")
    return proc.stdout


# --- app ---
@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.WARM_ON_START:
        threading.Thread(target=_warm, name="jarvis-warm", daemon=True).start()
    yield


app = FastAPI(title="Jarvis test UI", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


async def _body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _lang(v: Any) -> str | None:
    return v if isinstance(v, str) and v in LANGS else None


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(settings.WEB_DIR / "index.html", media_type="text/html",
                        headers={"Cache-Control": "no-cache"})


@app.get("/{name}")
async def static(name: str) -> Any:
    if name not in STATIC:
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(settings.WEB_DIR / name, media_type=STATIC[name], headers={"Cache-Control": "no-cache"})


@app.post("/api/chat")
async def chat(request: Request) -> Any:
    body = await _body(request)
    text = str(body.get("text") or "").strip()[:settings.MAX_TEXT_CHARS]
    if not text:
        return JSONResponse({"error": "empty text"}, status_code=400)
    mode = body.get("mode") if body.get("mode") in ("text", "voice") else "text"
    turn = Turn(asyncio.get_running_loop(), asyncio.Queue())
    threading.Thread(target=_run_turn, args=(turn, text, mode, _lang(body.get("lang"))),
                     name="jarvis-turn", daemon=True).start()

    async def events():
        try:
            while True:
                ev = await turn.queue.get()
                if ev is None:
                    break
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        finally:
            turn.closed = True
            _deny_pending(turn)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/confirm")
async def confirm(request: Request) -> Any:
    body = await _body(request)
    p = _pending.get(str(body.get("id") or ""))
    if p is None:
        return JSONResponse({"ok": False, "error": "unknown or expired confirmation"}, status_code=404)
    p.answer = body.get("yes") is True
    p.event.set()
    return {"ok": True, "yes": p.answer}


@app.get("/api/status")
async def status() -> Any:
    return await run_in_threadpool(_status)


@app.post("/api/stt")
async def stt_endpoint(request: Request) -> Any:
    data = await request.body()
    if not data:
        return JSONResponse({"error": "no audio"}, status_code=400)
    if len(data) > settings.MAX_AUDIO_BYTES:
        return JSONResponse({"error": "audio too large"}, status_code=413)
    try:
        wav = await run_in_threadpool(to_wav16k, data)
    except (ValueError, OSError, subprocess.SubprocessError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    from jarvis.core import stt
    try:
        tr = await run_in_threadpool(stt.transcribe, wav, _lang(request.query_params.get("lang")))
    except Exception as e:
        return JSONResponse({"error": f"transcription failed: {str(e)[:200]}"}, status_code=502)
    return {"text": getattr(tr, "text", str(tr)), "lang": getattr(tr, "lang", "en")}


@app.post("/api/speak")
async def speak(request: Request) -> Any:
    body = await _body(request)
    text = str(body.get("text") or "").strip()[:settings.MAX_TEXT_CHARS]
    if not text:
        return JSONResponse({"error": "empty text"}, status_code=400)
    from jarvis.core import tts
    lang = _lang(body.get("lang"))
    kw = {"lang": lang} if lang else {}
    try:
        await run_in_threadpool(lambda: tts.speak(text, block=False, **kw))
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=500)
    return {"ok": True}


@app.post("/api/speak/stop")
async def speak_stop() -> Any:
    from jarvis.core import tts
    with contextlib.suppress(Exception):
        await run_in_threadpool(tts.stop)
    return {"ok": True}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m jarvis.server", description="Jarvis web test UI (localhost only)")
    ap.add_argument("--port", type=int, default=settings.PORT)
    ap.add_argument("--no-warm", action="store_true", help="don't preload the agent after startup")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.no_warm:
        settings.WARM_ON_START = False
    import uvicorn
    print(f"Jarvis web UI: http://{settings.HOST}:{args.port}", flush=True)
    uvicorn.run(app, host=settings.HOST, port=args.port, log_level=settings.LOG_LEVEL, access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
