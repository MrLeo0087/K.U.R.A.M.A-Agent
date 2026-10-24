"""n8n inbound bridge (worker "n8n_inbound"): a stdlib HTTP server on 127.0.0.1:N8N_INBOUND_PORT.

    POST /jarvis   header X-Jarvis-Token: <JARVIS_INBOUND_TOKEN>
      {"text": "..."}                         -> agent.run(text) -> {"ok": true, "reply": "..."}
      {"notify": "..."} or {"notify": {"title", "text", "level"}} -> notify() -> {"ok": true}

Disabled unless JARVIS_INBOUND_TOKEN is set; every request without the exact token gets 401.
Confirm-level tools are denied (nobody is there to say yes); blocked tools never run.
"""
from __future__ import annotations

import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from jarvis.core import config, notify
from jarvis.workers.base import Worker

PATH = "/jarvis"


def token() -> str:
    return config.JARVIS_INBOUND_TOKEN or ""


def token_ok(given: str | None) -> bool:
    expected = token()
    return bool(expected) and hmac.compare_digest((given or "").encode(), expected.encode())


class Bridge:
    """Request logic, separate from the socket server so tests can call it directly."""

    def __init__(self, log):
        self.log = log
        self._agent = None
        self._lock = threading.Lock()

    def agent(self):
        if self._agent is None:
            from jarvis.core import agent, safety  # lazy: LangChain only when a text request comes

            self._agent = agent.Agent(confirm=safety.deny_all, channel="n8n")
        return self._agent

    def handle(self, path: str, headers: dict, body: bytes) -> tuple[int, dict]:
        if path.rstrip("/") != PATH:
            return 404, {"ok": False, "error": "not found"}
        if not token_ok(headers.get("X-Jarvis-Token") or headers.get("X-Kurama-Token")):
            self.log.warning("refused request with a missing or wrong token")
            return 401, {"ok": False, "error": "unauthorized"}
        if len(body) > config.N8N_INBOUND_MAX_BYTES:
            return 413, {"ok": False, "error": "body too large"}
        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, ValueError):
            return 400, {"ok": False, "error": "body must be JSON"}
        if not isinstance(data, dict):
            return 400, {"ok": False, "error": "body must be a JSON object"}
        if "notify" in data:
            n = data["notify"]
            if isinstance(n, dict):
                sent = notify.notify(str(n.get("title") or "n8n"), str(n.get("text") or ""),
                                     str(n.get("level") or "info"), source="n8n")
            else:
                sent = notify.notify("n8n", str(n), "info", source="n8n")
            return 200, {"ok": True, "channels": sent}
        text = str(data.get("text") or "").strip()
        if not text:
            return 400, {"ok": False, "error": "expected {\"text\": ...} or {\"notify\": ...}"}
        with self._lock:  # one agent conversation at a time
            try:
                reply = self.agent().run(text[:2000], mode="text")
            except Exception as e:
                self.log.exception("agent failed")
                return 500, {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
        return 200, {"ok": True, "reply": reply}


def make_handler(bridge: Bridge):
    class Handler(BaseHTTPRequestHandler):
        server_version = "KURAMA"

        def _send(self, code: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # noqa: N802
            try:
                n = min(int(self.headers.get("Content-Length") or 0), config.N8N_INBOUND_MAX_BYTES + 1)
            except ValueError:
                n = 0
            body = self.rfile.read(n) if n else b""
            self._send(*bridge.handle(self.path, dict(self.headers), body))

        def do_GET(self):  # noqa: N802
            self._send(405, {"ok": False, "error": "use POST /jarvis"})

        def log_message(self, fmt, *args):  # route access logs to the worker log
            bridge.log.info("%s %s", self.address_string(), fmt % args)

    return Handler


class N8nInbound(Worker):
    name = "n8n_inbound"
    interval_s = 30.0

    def __init__(self, interval_s: float | None = None):
        super().__init__(interval_s)
        self.bridge = Bridge(self.log)
        self.server: ThreadingHTTPServer | None = None
        self._serve: threading.Thread | None = None

    def available(self) -> str | None:
        return None if token() else "not configured (JARVIS_INBOUND_TOKEN unset)"

    def setup(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", config.N8N_INBOUND_PORT), make_handler(self.bridge))
        self.server.daemon_threads = True
        self._serve = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 1.0},
                                       name="n8n-inbound-http", daemon=True)
        self._serve.start()
        self.log.info("listening on 127.0.0.1:%d%s", config.N8N_INBOUND_PORT, PATH)

    def tick(self) -> None:
        if self._serve is not None and not self._serve.is_alive():
            raise RuntimeError("http server thread died")

    def info(self) -> dict:
        return {"port": config.N8N_INBOUND_PORT}

    def teardown(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
