"""KURAMA API app factory + runner.

    python -m jarvis.api [--host H] [--port P] [--no-warm]     (python -m jarvis.server is a shim)

Routers (all under /api/v1, OpenAPI docs at /docs):
  chat    POST /chat (SSE), POST /confirm
  voice   POST /stt, POST /tts (audio/mpeg stream)
  info    GET /health, /status, /status/stream (SSE), /jobs, /alerts, /profile, /tools;
          POST /jobs/{id}/cancel, /alerts/read
Laptop-local (must stay on the laptop in a future server split): /status*, and the agent's
desktop-control tools reached through /chat. Everything else can run in a container.

The frontend (frontend/) is plain static files that only call this API; serving it at / is a
convenience (JARVIS_SERVE_FRONTEND=1, default) - it works the same from any static host.
"""
from __future__ import annotations

import argparse
import contextlib
import logging
import sys
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from jarvis.api import settings as settings_mod
from jarvis.api.routes import chat, dash, info, voice, wake
from jarvis.api.security import Guard
from jarvis.api.settings import Settings
from jarvis.api.status import StatusCollector
from jarvis.api.turns import Engine
from jarvis.core import config

log = logging.getLogger("jarvis.api")


class _Frontend(StaticFiles):
    """Static files with revalidation, so an edited frontend shows up on reload."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


def _share_token(token: str) -> None:
    """The VS Code extension (same user) reads the API token from a 0600 file to call protected routes."""
    import os
    from pathlib import Path
    f = Path.home() / ".local" / "share" / "kurama" / "api_token"
    try:
        if token:
            f.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(token)
        else:
            f.unlink(missing_ok=True)
    except OSError:
        pass


def _recover_long_jobs() -> None:
    """Long jobs a crash / restart left unfinished continue from their last checkpoint (0 work when none)."""
    try:
        from jarvis.core import longjobs
        longjobs.recover()
    except Exception as e:
        logging.getLogger("jarvis.api").warning("long job recovery failed: %s", e)


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or settings_mod.from_env()
    engine = Engine(s)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        if s.warm_on_start:
            threading.Thread(target=engine.warm, name="jarvis-warm", daemon=True).start()
            from jarvis.core import devaudio  # "hear device sound" off: the echo canceller (system audio)
            threading.Thread(target=devaudio.apply, name="kurama-devaudio-apply", daemon=True).start()
            if config.WORKERS_IN_SERVER:
                from jarvis.workers import inproc
                inproc.start()
            threading.Thread(target=_recover_long_jobs, name="kurama-longjobs", daemon=True).start()
            try:  # hold Right Ctrl anywhere, speak, let go (captions beside the KURAMA button)
                from jarvis.core import ptt
                ptt.start()
            except Exception as e:  # noqa: BLE001
                logging.getLogger("jarvis.api").warning("hold-to-talk not started: %s", e)
        yield
        if config.WORKERS_IN_SERVER:
            from jarvis.workers import inproc
            inproc.stop()

    app = FastAPI(title="KURAMA (KURAMA) API", version=info.API_VERSION, lifespan=lifespan,
                  description="Backend for the KURAMA holographic UI. Optional bearer token "
                              "(JARVIS_API_TOKEN); SSE endpoints also accept ?token=.")
    app.state.settings = s
    app.state.engine = engine
    _share_token(s.token)
    app.state.status = StatusCollector(s, engine)
    for r in (chat.router, voice.router, info.router, wake.router, dash.router):
        app.include_router(r)

    # Guard first, CORS last = CORS outermost: preflights answered, and 401/403 still carry CORS headers.
    app.add_middleware(Guard, settings=s)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Authorization", "Content-Type"],
                       expose_headers=["X-Voice"], max_age=600)

    @app.get("/map/{name}", include_in_schema=False)  # not under /api, so the browser needs no token
    async def saved_map(name: str):
        import re as _re

        from fastapi.responses import FileResponse
        from jarvis.core import config as _cfg
        if not _re.fullmatch(r"[\w.\-]+\.html", name):  # no path traversal
            return JSONResponse({"error": "bad name"}, status_code=400)
        path = _cfg.OUTPUTS_DIR / "maps" / name
        if not path.is_file():
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(str(path), media_type="text/html")

    if s.serve_frontend and (s.frontend_dir / "index.html").is_file():
        app.mount("/", _Frontend(directory=str(s.frontend_dir), html=True), name="frontend")
    else:
        @app.get("/", include_in_schema=False)
        async def root():
            return JSONResponse({"name": "KURAMA API", "docs": "/docs", "health": "/api/v1/health"})
    return app


def parse_args(argv: list[str] | None = None, prog: str = "python -m jarvis.api") -> argparse.Namespace:
    env = settings_mod.from_env()
    ap = argparse.ArgumentParser(prog=prog, description="KURAMA API + KURAMA UI")
    ap.add_argument("--host", default=env.host, help="bind address (default JARVIS_API_HOST or 127.0.0.1)")
    ap.add_argument("--port", type=int, default=env.port, help="port (default JARVIS_API_PORT or 8000)")
    ap.add_argument("--no-warm", action="store_true", help="don't preload the agent after startup")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None, prog: str = "python -m jarvis.api") -> int:
    args = parse_args(argv, prog)
    s = settings_mod.from_env(host=args.host, port=args.port)
    if args.no_warm:
        s.warm_on_start = False
    if not s.loopback and not s.token and not s.allow_no_token:
        print("Refusing to listen on a non-loopback address without JARVIS_API_TOKEN "
              "(the API can control this computer). Set a token, or JARVIS_API_ALLOW_NO_TOKEN=1.",
              file=sys.stderr)
        return 2
    import uvicorn
    shown = "127.0.0.1" if s.host in ("0.0.0.0", "::") else s.host
    print(f"KURAMA API + KURAMA UI: http://{shown}:{s.port}  (docs: /docs)", flush=True)
    uvicorn.run(create_app(s), host=s.host, port=s.port, log_level=s.log_level, access_log=False)
    return 0
