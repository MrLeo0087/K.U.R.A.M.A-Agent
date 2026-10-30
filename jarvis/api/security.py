"""Request guard for the KURAMA API (pure ASGI, so SSE streams pass through untouched).

The API can run tools on the laptop, so every /api request is checked:
  1. Host header allowlist (default: loopback names when bound to loopback): blocks DNS rebinding.
  2. Origin: a browser request from another site is refused unless that origin is in
     JARVIS_CORS_ORIGINS (or is this same host). Stops random web pages from driving KURAMA.
  3. Content-Type: JSON endpoints need application/json and /stt needs an audio type, so a
     cross-site "simple" form/text POST can never reach the agent without a CORS preflight.
  4. Bearer token (JARVIS_API_TOKEN, optional): `Authorization: Bearer <t>` or `?token=<t>` (for
     EventSource, which cannot send headers). /api/v1/health stays open for container healthchecks.
CORSMiddleware wraps this guard (added after it), so even 401/403 replies carry CORS headers.
"""
from __future__ import annotations

import hmac
import json
from urllib.parse import parse_qs, urlsplit

from jarvis.api.settings import Settings

OPEN_PATHS = ("/api/v1/health", "/api/v1/context/tab", "/api/v1/context/selection", "/api/v1/coding/terminal")  # the browser extension (no token)
EXT_PATHS = ("/api/v1/context/tab", "/api/v1/context/selection")  # browser-extension origins may call these
RAW_BODY_PATHS = ("/api/v1/stt",)
_SIMPLE_TYPES = ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data")


def _host_only(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("["):  # [::1]:8000
        return host[1:].split("]", 1)[0]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


class Guard:
    def __init__(self, app, settings: Settings) -> None:
        self.app = app
        self.s = settings
        self.origins = {o.rstrip("/") for o in settings.cors_origins}
        self.hosts = {h.lower() for h in settings.allowed_hosts}

    async def _deny(self, send, status: int, error: str) -> None:
        body = json.dumps({"error": error}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    def _token_ok(self, headers: dict, query: bytes) -> bool:
        want = self.s.token
        auth = headers.get("authorization", "")
        if auth[:7].lower() == "bearer " and hmac.compare_digest(auth[7:].strip().encode(), want.encode()):
            return True
        got = (parse_qs(query.decode("latin-1")).get("token") or [""])[0]
        return bool(got) and hmac.compare_digest(got.encode(), want.encode())

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        host = headers.get("host", "")
        if "*" not in self.hosts and _host_only(host) not in self.hosts:
            return await self._deny(send, 400, "host not allowed")
        path: str = scope.get("path", "")
        if not path.startswith("/api/"):
            return await self.app(scope, receive, send)
        origin = headers.get("origin", "").rstrip("/")
        if origin and "*" not in self.origins and origin not in self.origins \
                and urlsplit(origin).netloc.lower() != host.lower() \
                and not (path in EXT_PATHS and origin.startswith(("chrome-extension://", "moz-extension://"))):
            return await self._deny(send, 403, "origin not allowed")
        method = scope.get("method", "GET")
        if method == "OPTIONS":
            return await self.app(scope, receive, send)
        if self.s.token and path not in OPEN_PATHS and not self._token_ok(headers, scope.get("query_string", b"")):
            return await self._deny(send, 401, "missing or wrong API token")
        if method == "POST":
            ctype = headers.get("content-type", "").split(";")[0].strip().lower()
            if path in RAW_BODY_PATHS:
                if ctype in _SIMPLE_TYPES:
                    return await self._deny(send, 415, "send the recording with an audio/* content type")
            elif ctype != "application/json":
                return await self._deny(send, 415, "content-type must be application/json")
        return await self.app(scope, receive, send)
