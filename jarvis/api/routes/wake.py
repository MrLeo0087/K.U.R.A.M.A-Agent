"""Wake word for the dashboard: while KURAMA sleeps, the API listens with a cheap Python loop (sounddevice +
webrtcvad + short-burst recognition, jarvis.core.wake.WakeListener) instead of the browser's microphone, which
costs ~20% CPU in WebKitGTK. "wake up KURAMA" sends a `wake` event to the page; the page then opens its own mic
(with echo cancellation) for the conversation and the server listener stops.

  POST /api/v1/wake/sleep    start listening for the wake phrase
  POST /api/v1/wake/awake    stop it (the page has the mic now)
  GET  /api/v1/wake/events   SSE: {"type":"wake","heard","command","lang"} | {"type":"error","text"}
  GET  /api/v1/wake/status
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading

from pydantic import BaseModel
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from jarvis.api.routes.chat import SSE_HEADERS

router = APIRouter(prefix="/api/v1/wake", tags=["wake"])
log = logging.getLogger("jarvis.api.wake")


class WakeService:
    def __init__(self) -> None:
        self.stop_ev = threading.Event()
        self.thread: threading.Thread | None = None
        self.subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self.lock = threading.Lock()

    @property
    def listening(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def publish(self, ev: dict) -> None:
        for loop, q in list(self.subs):
            loop.call_soon_threadsafe(q.put_nowait, ev)

    def start(self) -> None:
        with self.lock:
            if self.listening:
                return
            self.stop_ev = threading.Event()
            self.thread = threading.Thread(target=self._run, args=(self.stop_ev,), name="wake", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        self.stop_ev.set()

    def _run(self, stop: threading.Event) -> None:
        try:
            from jarvis.core import wake
            ev = wake.WakeListener().listen(stop)
        except Exception as e:  # no mic / no PortAudio: the page falls back to its own listener
            log.warning("wake listener failed: %s", e)
            self.publish({"type": "error", "text": f"{type(e).__name__}: {str(e)[:160]}"})
            return
        if ev is not None and not stop.is_set():
            log.info("wake: %r command=%r", ev.heard, ev.command)
            self.publish({"type": "wake", "heard": ev.heard, "command": ev.command, "lang": ev.lang})


SERVICE = WakeService()


MIC_OFF_KEY = "mic_off"  # the user muted the mic or chose text mode: KURAMA holds NO microphone (other apps get it)


def mic_off() -> bool:
    from jarvis.core import store
    return store.kv_get(MIC_OFF_KEY) == "1"


class MicIn(BaseModel):
    off: bool


@router.post("/mic", summary="Mic off (mute / text mode): stop every KURAMA listener and refuse new ones; on = allowed again")
async def wake_mic(body: MicIn):
    from jarvis.core import store
    changed = mic_off() != body.off
    store.kv_set(MIC_OFF_KEY, "1" if body.off else "")
    if body.off:
        SERVICE.stop()
    if changed:  # the echo canceller keeps the real mic RUNNING: unload it while off, load it back after
        from fastapi.concurrency import run_in_threadpool
        from jarvis.core import devaudio
        await run_in_threadpool(devaudio.apply)
    return {"mic_off": body.off}


@router.post("/sleep", summary="Listen (server-side, cheap) for the wake phrase")
async def wake_sleep():
    from jarvis.core import modes
    if mic_off():  # muted / text mode: never open the mic, not even for the wake word
        SERVICE.stop()
        return {"listening": False, "reason": "the mic is off (muted or text mode)"}
    if not modes.wake_allowed():  # the power mode turned the wake word off (saves the mic + Whisper calls)
        SERVICE.stop()
        return {"listening": False, "reason": "wake word is off in this mode"}
    SERVICE.start()
    return {"listening": True}


@router.post("/awake", summary="Stop listening for the wake phrase (the page has the mic)")
async def wake_awake():
    SERVICE.stop()
    return {"listening": False}


@router.get("/status")
async def wake_status():
    return {"listening": SERVICE.listening, "mic_off": mic_off()}


@router.get("/events", summary="Wake events as Server-Sent Events")
async def wake_events(request: Request):
    q: asyncio.Queue = asyncio.Queue()
    sub = (asyncio.get_running_loop(), q)
    SERVICE.subs.append(sub)

    async def events():
        try:
            while not await request.is_disconnected():
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=25)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        finally:
            SERVICE.subs.remove(sub)

    return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)
