"""Web projects, seen running (0 tokens unless a look is asked for):

  server      a tiny local server for the project (http://127.0.0.1:<port>/) that adds a reporter to every page:
              JavaScript errors, failed promises, console.error and missing files are sent back and collected
  selftest    after a build: the page opened in headless Brave for a few seconds, every button clicked once ->
              its errors become problems for the fix step ("app.js:42: TypeError: ... is null")
  open        "preview it": the page in Brave; "check the page" = the errors seen while you used it
  look        "how does it look?": a screenshot read by the vision model (1 call), only when asked
The server stops by itself after 30 idle minutes.
"""
from __future__ import annotations

import base64
import functools
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

IDLE_S = 1800
_REPORTER = """<script>(function(){var s=function(m){try{navigator.sendBeacon('/__kurama/err',JSON.stringify(m))}catch(e){}};
window.addEventListener('error',function(e){if(e.target&&e.target!==window&&(e.target.src||e.target.href)){s({kind:'missing',
msg:'could not load '+(e.target.src||e.target.href)});return}s({kind:'error',msg:String(e.message),src:e.filename||'',line:e.lineno||0})},true);
window.addEventListener('unhandledrejection',function(e){s({kind:'promise',msg:String(e.reason&&e.reason.stack||e.reason)})});
var ce=console.error;console.error=function(){s({kind:'console',msg:[].slice.call(arguments).join(' ')});ce.apply(console,arguments)};
if(location.search.indexOf('kurama_selftest')>=0){window.addEventListener('load',function(){var b=[].slice.call(
document.querySelectorAll('button,[role=button],input[type=button],input[type=submit],[data-choice],[onclick]')).slice(0,25),i=0;
(function next(){if(i>=b.length){s({kind:'done'});return}try{b[i].click()}catch(e){s({kind:'error',msg:'click: '+e.message})}i++;setTimeout(next,120)})()})}
})();</script>"""


class _State:
    def __init__(self, root: Path):
        self.root, self.errors, self.used = root, [], time.time()
        self.done = threading.Event()


class _Handler(SimpleHTTPRequestHandler):
    state: _State

    def log_message(self, *a) -> None:  # quiet
        pass

    def do_POST(self) -> None:  # noqa: N802
        if self.path.startswith("/__kurama/err"):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                m = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                m = {}
            if m.get("kind") == "done":
                self.state.done.set()
            elif m:
                self.state.errors.append(m)
        self.send_response(204)
        self.end_headers()

    def send_head(self):  # pages get the reporter
        self.state.used = time.time()
        path = Path(self.translate_path(self.path))
        if path.is_dir():
            path = path / "index.html"
        if path.suffix == ".html" and path.is_file():
            body = path.read_bytes()
            low = body.lower()
            i = low.find(b"<head>")
            body = body[: i + 6] + _REPORTER.encode() + body[i + 6:] if i >= 0 else _REPORTER.encode() + body
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            import io
            return io.BytesIO(body)
        if not path.exists():
            self.state.errors.append({"kind": "missing", "msg": f"could not load {self.path}"})
        return super().send_head()


_servers: dict[str, tuple[ThreadingHTTPServer, _State]] = {}
_lock = threading.Lock()


def page_root(root: Path) -> Path | None:
    """The folder whose index.html is the app (the project, or its public/ / src/ / static/ folder)."""
    for d in (root, root / "public", root / "src", root / "static", root / "web"):
        if (d / "index.html").is_file():
            return d
    return None


def server(root: Path) -> tuple[str, _State] | None:
    """The project's server (started once), its address and its state."""
    web = page_root(root)
    if web is None:
        return None
    with _lock:
        got = _servers.get(str(web))
        if got is None:
            st = _State(web)
            handler = type("H", (_Handler,), {"state": st})
            srv = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(handler, directory=str(web)))
            threading.Thread(target=srv.serve_forever, name="coder-preview", daemon=True).start()
            _servers[str(web)] = got = (srv, st)
            threading.Thread(target=_stop_when_idle, args=(str(web),), daemon=True).start()
    srv, st = got
    return f"http://127.0.0.1:{srv.server_address[1]}/", st


def _stop_when_idle(key: str) -> None:
    while True:
        time.sleep(60)
        with _lock:
            got = _servers.get(key)
            if got is None:
                return
            if time.time() - got[1].used > IDLE_S:
                got[0].shutdown()
                del _servers[key]
                return


def browser() -> str | None:
    return next((b for b in ("brave-browser", "brave", "chromium", "chromium-browser", "google-chrome") if shutil.which(b)), None)


def problems_of(errors: list[dict], web: Path) -> list[str]:
    """Collected errors as problem lines for the fix step ('app.js:42: TypeError: x is null')."""
    out = []
    for e in errors:
        src = re.sub(r"^https?://[^/]+/", "", str(e.get("src") or "")).split("?")[0]
        if e.get("kind") == "missing":
            what = re.sub(r"^could not load (?:https?://[^/]+)?/?", "", str(e.get("msg") or ""))
            if what and not what.startswith("favicon.ico"):  # (browsers ask for it by themselves)
                out.append(f"index.html: asks for {what}, which is missing")
        elif src and (web / src).exists():
            rel = (web / src).relative_to(web).as_posix()
            out.append(f"{rel}:{e.get('line') or '?'}: browser error: {str(e.get('msg'))[:200]}")
        else:
            out.append(f"index.html: browser error: {str(e.get('msg'))[:200]}")
    return list(dict.fromkeys(out))[:10]


def selftest(root: Path, seconds: float = 6) -> list[str] | None:
    """Open the page headless, click its buttons, return its errors as problem lines (None = can't test here)."""
    b, got = browser(), server(root)
    if b is None or got is None:
        return None
    url, st = got
    st.errors.clear()
    st.done.clear()
    with tempfile.TemporaryDirectory() as prof:
        try:
            p = subprocess.Popen([b, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={prof}",
                                  "--window-size=1200,900", url + "?kurama_selftest=1"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return None
        st.done.wait(seconds)
        time.sleep(0.5)
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
    return problems_of(st.errors, page_root(root) or root)


def open_page(root: Path) -> str:
    got = server(root)
    if got is None:
        return f"{root.name} has no index.html to preview (a React app runs with 'npm install && npm run dev')."
    url, st = got
    st.errors.clear()
    b = browser()
    try:
        subprocess.Popen([b or "xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass
    return f"Preview of {root.name}: {url} (opened in your browser). Use it, then say 'check the page' and I'll fix any errors it showed."


def seen(root: Path) -> list[str]:
    """Errors the page showed while the owner used it."""
    web = page_root(root)
    got = _servers.get(str(web)) if web else None
    return problems_of(got[1].errors, web) if got and web else []


def screenshot(root: Path) -> bytes | None:
    b, got = browser(), server(root)
    if b is None or got is None:
        return None
    with tempfile.TemporaryDirectory() as d:
        shot = Path(d) / "s.png"
        try:
            # (no own --user-data-dir: with a fresh profile Brave's headless screenshot hangs until killed, 11-06)
            subprocess.run([b, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1280,860",
                            f"--screenshot={shot}", got[0]], capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return shot.read_bytes() if shot.exists() else None


def look(root: Path, request: str = "") -> str:
    """The vision model's honest look at the page (1 call)."""
    png = screenshot(root)
    if png is None:
        return "I couldn't take a picture of the page here."
    from jarvis.core import llm
    ask = ("This is a screenshot of a web app the user is building" + (f" ({request})" if request else "") + ". Judge "
           "the UI honestly as a designer: what looks broken or unfinished (overlaps, cut text, bad contrast, empty "
           "areas, misaligned parts), then 3 concrete improvements. Short bullet points.")
    r = llm.chat([{"role": "user", "content": [{"type": "text", "text": ask}, {"type": "image_url", "image_url": {
        "url": "data:image/png;base64," + base64.b64encode(png).decode()}}]}], tier="vision", purpose="coder_look",
        max_tokens=600)
    return (r.text or "").strip() or "The vision model gave no answer."
