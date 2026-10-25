"""Tiny LAN file server for KURAMA's Wi-Fi share (stdlib only, run as its own process).

Usage: wifi_share_server.py <path> <port> <token> <idle_minutes>
Serves ONE file or ONE folder (listing + per-file download + 'download all as zip') under /<token>/ only;
anything else is 404. Exits by itself after <idle_minutes> without a request.
"""
import html
import os
import sys
import threading
import time
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
PORT, TOKEN, IDLE_S = int(sys.argv[2]), sys.argv[3], float(sys.argv[4]) * 60
SKIP = {".git", "venv", ".venv", "node_modules", "__pycache__"}
last = time.time()

PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>KURAMA share</title><style>body{{font:16px system-ui,sans-serif;margin:16px;background:#0f1115;color:#e8e8e8}}
a{{color:#7cc4ff;text-decoration:none}}li{{padding:8px 0;border-bottom:1px solid #222}}small{{color:#888}}
.btn{{display:inline-block;padding:10px 14px;background:#1f6feb;color:#fff;border-radius:8px;margin:8px 0}}</style>
<h3>{title}</h3>{body}"""


def _size(n: float) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _404(self):
        self.send_error(404)

    def do_GET(self):
        global last
        last = time.time()
        u = urllib.parse.urlparse(self.path)
        parts = [urllib.parse.unquote(p) for p in u.path.split("/") if p]
        if not parts or parts[0] != TOKEN:
            return self._404()
        rel = "/".join(parts[1:])
        target = (ROOT / rel).resolve() if ROOT.is_dir() else ROOT
        if ROOT.is_dir() and ROOT not in (target, *target.parents):
            return self._404()
        if not target.exists():
            return self._404()
        if target.is_dir():
            if "zip=1" in (u.query or ""):
                return self._zip(target)
            return self._list(target, rel)
        if ROOT.is_file() and not rel:  # single file: a small landing page so the phone shows name + size
            return self._page(target.name, f"<p><small>{_size(target.stat().st_size)}</small></p>"
                              f"<a class=btn href='/{TOKEN}/{urllib.parse.quote(target.name)}'>Download</a>")
        return self._file(target)

    def _page(self, title, body):
        data = PAGE.format(title=html.escape(title), body=body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _list(self, d, rel):
        items = sorted((p for p in d.iterdir() if p.name not in SKIP and not p.name.startswith(".")),
                       key=lambda p: (p.is_file(), p.name.lower()))
        base = f"/{TOKEN}/" + (urllib.parse.quote(rel) + "/" if rel else "")
        rows = "".join(
            f"<li><a href='{base}{urllib.parse.quote(p.name)}{'/' if p.is_dir() else ''}'>"
            f"{'&#128193; ' if p.is_dir() else ''}{html.escape(p.name)}</a> "
            f"<small>{'' if p.is_dir() else _size(p.stat().st_size)}</small></li>" for p in items)
        body = f"<a class=btn href='{base}?zip=1'>Download all (zip)</a><ul style='list-style:none;padding:0'>{rows}</ul>"
        self._page(d.name, body)

    def _file(self, f):
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(f.stat().st_size))
        self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(f.name))
        self.end_headers()
        with open(f, "rb") as fh:
            while chunk := fh.read(1 << 20):
                self.wfile.write(chunk)
                global last
                last = time.time()

    def _zip(self, d):
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(d.name + ".zip"))
        self.send_header("Connection", "close")
        self.end_headers()
        with zipfile.ZipFile(self.wfile, "w", zipfile.ZIP_STORED, allowZip64=True) as z:  # streamed, no temp file
            for dirpath, dirnames, filenames in os.walk(d):
                dirnames[:] = [x for x in dirnames if x not in SKIP and not x.startswith(".")]
                for fn in filenames:
                    p = Path(dirpath) / fn
                    try:
                        z.write(p, p.relative_to(d.parent))
                    except OSError:
                        continue
                    global last
                    last = time.time()
        self.close_connection = True


def _idle_watch(srv):
    while True:
        time.sleep(15)
        if time.time() - last > IDLE_S:
            srv.shutdown()
            return


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    threading.Thread(target=_idle_watch, args=(srv,), daemon=True).start()
    srv.serve_forever()
