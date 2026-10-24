"""Warm, reusable edge-tts websockets.

A fresh edge-tts request pays ~0.5-0.8 s for TLS + websocket setup before any audio. The Edge
read-aloud service accepts several SSML requests on one socket, so we keep TTS_PARALLEL sockets
open on one long-lived event loop and send each sentence on a warm one (first audio ~0.4-0.7 s).
prewarm() is called when KURAMA starts listening, so sockets are ready by the time it speaks.

Uses edge_tts helpers (pinned version). Any protocol error falls back to edge_tts.Communicate.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import AsyncIterator
from xml.sax.saxutils import escape

from jarvis.core import config

log = logging.getLogger(__name__)

_CONFIG_MSG = (
    "X-Timestamp:{ts}\r\nContent-Type:application/json; charset=utf-8\r\nPath:speech.config\r\n\r\n"
    '{{"context":{{"synthesis":{{"audio":{{"metadataoptions":{{'
    '"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"false"}},'
    '"outputFormat":"audio-24khz-48kbitrate-mono-mp3"}}}}}}}}\r\n'
)


class _Sock:
    def __init__(self, ws) -> None:
        self.ws = ws
        self.used = time.monotonic()


class EdgePool:
    def __init__(self, size: int | None = None) -> None:
        self.size = max(1, size or config.TTS_PARALLEL)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session = None
        self._idle: list[_Sock] = []
        self._connecting = 0
        self._lock = threading.Lock()

    # --- loop management (one daemon thread owns all sockets) ---
    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                threading.Thread(target=self._loop.run_forever, name="edge-pool", daemon=True).start()
            return self._loop

    def run(self, coro, timeout: float | None = None):
        """Run a coroutine on the pool loop from any other thread and wait for it."""
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def prewarm(self) -> None:
        """Fire-and-forget: top the pool up to `size` warm sockets."""
        try:
            asyncio.run_coroutine_threadsafe(self._fill(), self.loop)
        except Exception as e:  # never let warming break the voice loop
            log.debug("edge prewarm failed: %s", e)

    # --- sockets (pool loop only) ---
    async def _connect(self) -> _Sock:
        import aiohttp
        from edge_tts import communicate as C
        from edge_tts.constants import SEC_MS_GEC_VERSION, WSS_HEADERS, WSS_URL
        from edge_tts.drm import DRM

        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(trust_env=True)
        ws = await self._session.ws_connect(
            f"{WSS_URL}&ConnectionId={C.connect_id()}&Sec-MS-GEC={DRM.generate_sec_ms_gec()}"
            f"&Sec-MS-GEC-Version={SEC_MS_GEC_VERSION}",
            compress=15, headers=DRM.headers_with_muid(WSS_HEADERS), ssl=C._SSL_CTX,
            timeout=aiohttp.ClientWSTimeout(ws_close=5), autoping=True, heartbeat=None)
        await ws.send_str(_CONFIG_MSG.format(ts=C.date_to_string()))
        return _Sock(ws)

    async def _fill(self) -> None:
        self._prune()
        need = self.size - len(self._idle) - self._connecting
        if need <= 0:
            return
        self._connecting += need

        async def one() -> None:
            try:
                self._idle.append(await self._connect())
            except Exception as e:
                log.debug("edge connect failed: %s", e)
            finally:
                self._connecting -= 1

        await asyncio.gather(*(one() for _ in range(need)))

    def _prune(self) -> None:
        now = time.monotonic()
        keep = []
        for s in self._idle:
            if s.ws.closed or now - s.used > config.TTS_WS_MAX_IDLE_S:
                asyncio.ensure_future(s.ws.close())
            else:
                keep.append(s)
        self._idle = keep

    async def _acquire(self) -> _Sock:
        self._prune()
        sock = self._idle.pop() if self._idle else await self._connect()
        asyncio.ensure_future(self._fill())  # replace it in the background
        return sock

    async def synth(self, text: str, voice: str, rate: str | None = None) -> AsyncIterator[bytes]:
        """Stream mp3 chunks for one sentence over a warm socket. Must run on self.loop."""
        import aiohttp
        from edge_tts import communicate as C
        from edge_tts.data_classes import TTSConfig

        if asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("EdgePool.synth must run on the pool loop")
        tc = TTSConfig(voice, rate or config.TTS_RATE, "+0%", "+0Hz", "SentenceBoundary")
        msg = C.ssml_headers_plus_data(C.connect_id(), C.date_to_string(),
                                       C.mkssml(tc, escape(C.remove_incompatible_characters(text))))
        for attempt in (1, 2):  # a pooled socket may have been closed by the server: retry fresh
            sock = await self._acquire() if attempt == 1 else await self._connect()
            got_audio = clean = False
            try:
                await sock.ws.send_str(msg)
                async for m in sock.ws:
                    if m.type == aiohttp.WSMsgType.TEXT:
                        if "Path:turn.end" in m.data:
                            clean = True
                            break
                    elif m.type == aiohttp.WSMsgType.BINARY:
                        hl = int.from_bytes(m.data[:2], "big")
                        data = m.data[2 + hl:]
                        if data:
                            got_audio = True
                            yield data
                    else:  # CLOSE / ERROR
                        break
            except (aiohttp.ClientError, ConnectionError, asyncio.TimeoutError) as e:
                log.debug("edge socket error: %s", e)
            finally:
                if clean:
                    sock.used = time.monotonic()
                    self._idle.append(sock)
                else:  # interrupted mid-sentence (barge-in) or broken: never reuse
                    asyncio.ensure_future(sock.ws.close())
            if clean or got_audio:
                return
        raise ConnectionError("edge-tts websocket gave no audio")


    async def _close(self) -> None:
        for s in self._idle:
            await s.ws.close()
        self._idle = []
        if self._session is not None:
            await self._session.close()

    def close(self) -> None:
        if self._loop is not None and self._loop.is_running():
            try:
                self.run(self._close(), timeout=2)
            except Exception:
                pass


_pool: EdgePool | None = None


def get_pool() -> EdgePool:
    global _pool
    if _pool is None:
        import atexit

        _pool = EdgePool()
        atexit.register(_pool.close)
    return _pool
