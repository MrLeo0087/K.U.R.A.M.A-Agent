#!/usr/bin/python3
"""KURAMA live wallpaper: a native GTK + WebKit window that sits behind every window (X11).

Runs with the *system* Python (python3-gi, gir1.2-webkit2-4.1, optional gir1.2-wnck-3.0), not the venv:
    /usr/bin/python3 scripts/kurama_wallpaper.py                 # as wallpaper (use Super+D to reach it)
    /usr/bin/python3 scripts/kurama_wallpaper.py --window        # as a normal window (testing)
    /usr/bin/python3 scripts/kurama_wallpaper.py --url http://127.0.0.1:8000/?wallpaper=1

While a maximized / full-screen window covers the desktop (checked with libwnck every ~2 s) the page is
paused through window.kuramaPause(true): the orb loop, clock, status stream and CSS animations stop, so
the wallpaper costs ~0 CPU while you work. The page stays clickable: chat works from the desktop.

Minimize (the button in the chat header) switches the big dashboard OFF (page unloaded, window hidden; the
desktop shows its saved snapshot; WakeBridge keeps the wake word through the API) and shows mini KURAMA: a small round
button that floats above every app (drag it anywhere, right-click for a menu). Clicking it opens a small
chat-only panel (same page with ?mini=1: text, mic and conversation mode) over whatever you are using.
Talk mode keeps working when that panel is closed: the panel turns invisible and click-through instead of
hiding (a hidden WebView would stop the mic), the button's ring shows listening / thinking / speaking, and
what you said and KURAMA's reply appear in a small caption next to the button (click it to open the chat).

Instant start: a snapshot of the dashboard is saved in ~/.local/share/kurama (on the home drive, readable at
login) and used as the GNOME desktop background, so the desktop already looks like KURAMA from the first
frame; the window then shows the same snapshot until the live page has loaded, so nothing flashes. Your
real wallpaper is remembered (real-wallpaper.json) and put back by `kurama-wallpaper.sh stop`.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
gi.require_foreign("cairo")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, WebKit2  # noqa: E402

try:  # libwnck tells us when windows cover the desktop
    gi.require_version("Wnck", "3.0")
    from gi.repository import Wnck  # noqa: E402
except (ValueError, ImportError):
    Wnck = None

PORT = os.getenv("JARVIS_API_PORT", "8000")
DEFAULT_URL = os.getenv("KURAMA_UI_URL", f"http://127.0.0.1:{PORT}/?lowpower=0&wallpaper=1")
CHECK_MS = 2000
STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "mini.json"  # minimized? + button position
BUBBLE = 56  # floating button size (px)
PANEL_W, PANEL_H = 400, 600  # mini chat panel (default size; a resized panel remembers its size)
PANEL_MIN_W, PANEL_MIN_H = 300, 260
MINI_HOTKEY = os.getenv("KURAMA_MINI_HOTKEY", "<Control><Alt>k")  # opens / hides the mini chat (GNOME shortcut; '' = none)
# typing cursor to KURAMA's chat box and back again; the chat itself never hides. Ctrl+L is Brave's address bar /
# the terminal's clear, Ctrl+Shift+L VS Code's "select all occurrences", Ctrl+Alt+L clashed with hold-Alt.
FOCUS_HOTKEY = os.getenv("KURAMA_FOCUS_HOTKEY", "<Super>j")  # Super + J: home row, no app or GNOME uses it
_OLD_FOCUS_KEYS = ("<Control><Alt>l", "<Control><Shift>l")  # earlier defaults: moved to the new one (yours are kept)
ALERT_POLL_S = 5  # mini KURAMA checks for new alerts this often (one tiny local request)
PID_FILE = STATE_FILE.with_name("wallpaper.pid")  # the shortcut signals this process (SIGUSR1)
BUSY_STATES = ("listening", "capturing", "thinking", "speaking")  # closing the panel now keeps it alive
IDLE_ANIM_MS = 125  # the button's slow idle ring (0 = still)
WS_W, WS_H = 480, 620  # mini workspace window
PANEL_KEEP_S = 0  # 0 = the hidden panel's page stays loaded and is preloaded at start (owner's choice 11-01: the
#                  first hold after 20 min idle / a restart said "Getting ready… keep holding" for ~2 s while the
#                  page reloaded; kept loaded it costs the measured RAM in PROGRESS.md and ~0 CPU: its animations
#                  are frozen and its timers skip while hidden). >0 = close it after that many seconds hidden.
PANEL_PRELOAD_S = 8  # load the hidden panel this long after start (after the wallpaper's own first paint)
CAPTION_W = 340  # reply caption next to the button while talking with the panel closed
RING = {"listening": (0.25, 0.85, 0.78), "capturing": (0.25, 0.95, 0.6), "thinking": (1, 0.75, 0.25),
        "speaking": (1, 0.55, 0.15)}  # button ring colour per voice state (talk mode, panel closed)
SNAP_DIR = Path.home() / ".local/share/kurama"  # same paths in jarvis/tools/general/set_wallpaper.py
SNAP = SNAP_DIR / "desktop.png"
REAL_WALLPAPER = SNAP_DIR / "real-wallpaper.json"
SNAP_FIRST_S, SNAP_EVERY_S = 8, 600  # after the page is up (boot animation done), then every 10 min
HANG_S = float(os.getenv("KURAMA_WP_HANG_S", "25"))  # a page that doesn't answer for this long is frozen: restart it
PROBE_IN = Path(__file__).resolve().parent.parent / "data" / "wp_probe.js"  # developer probe: JS to run in the page
PROBE_OUT = PROBE_IN.with_suffix(".out")  # ...its answer (read-only checks: CPU / frame costs, no clicks)
PING_S = 10  # how often the watchdog asks the page for a tiny answer
PAUSE_RESEND_S = 15  # the covered / uncovered state is sent to the page again this often (cheap, idempotent)
FD_LIMIT = 65536  # open-file limit for this window and its web processes (the desktop's default is 1024)
FD_CHECK_S = 30  # how often the web processes' open files are counted
FD_WARN = 600  # past this (and every +300 after) hang.log gets a line with what kind of files they are
FD_RECYCLE = 6000  # past this the window restarts itself (a leak): a fresh window instead of a black, stuck one
PANEL_READY_S = 12  # the mini chat's page not loaded this long after a hold: its web process is restarted
WEB_MEM_MB = int(os.getenv("KURAMA_WP_MEM_MB", "220"))  # web process memory budget (WebKit's default: 3 GB)


def lean_context():
    """WebKit only frees caches / runs a full GC when a process nears its memory limit, and the default limit
    is 3 GB, so an all-day page just keeps growing. A small budget makes it clean up early (from ~35%),
    harder above ~55%, and never kills the page. Nothing visible changes."""
    mps = WebKit2.MemoryPressureSettings.new()
    mps.set_memory_limit(WEB_MEM_MB)
    mps.set_conservative_threshold(0.35)
    mps.set_strict_threshold(0.55)
    mps.set_kill_threshold(0)
    mps.set_poll_interval(10)
    with contextlib.suppress(Exception):  # the network process too (before any data manager exists)
        WebKit2.WebsiteDataManager.set_memory_pressure_settings(mps)
    return WebKit2.WebContext(memory_pressure_settings=mps)


def desktop_covered(screen) -> bool:
    """True when a maximized/full-screen normal window on the current workspace hides the wallpaper."""
    screen.force_update()
    workspace = screen.get_active_workspace()
    sw, sh = screen.get_width(), screen.get_height()
    for w in screen.get_windows():
        if w.get_window_type() != Wnck.WindowType.NORMAL or w.is_minimized():
            continue
        if workspace and not w.is_on_workspace(workspace):
            continue
        _, _, ww, wh = w.get_geometry()
        if w.is_maximized() or w.is_fullscreen() or (ww >= sw * 0.95 and wh >= sh * 0.9):
            return True
    return False


def configure_media(s) -> list[str]:
    """Mic + audio for voice chat: media stream, Web Audio, <audio>, MSE, autoplay; plus the MediaRecorder
    runtime feature where this WebKit exposes it (the page records WAV itself, so it is optional)."""
    applied = []
    for name, value in (("enable_media_stream", True), ("enable_webaudio", True), ("enable_media", True),
                        ("enable_mediasource", True), ("enable_media_capabilities", True),
                        ("enable_encrypted_media", False), ("media_playback_requires_user_gesture", False)):
        setter = getattr(s, "set_" + name, None)
        if setter is not None:
            try:
                setter(value)
                applied.append(name)
            except Exception:
                pass
    with contextlib.suppress(Exception):  # WebKitGTK >= 2.42
        features = WebKit2.Settings.get_all_features()
        for i in range(features.get_length()):
            f = features.get(i)
            if f.get_identifier() in ("MediaRecorderEnabled", "MediaRecorder"):
                s.set_feature_enabled(f, True)
                applied.append(f.get_identifier())
    return applied


def origin_of(uri: str) -> str:
    u = urlsplit(uri or "")
    return f"{u.scheme}://{u.netloc}".lower()


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    with contextlib.suppress(OSError):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state))


def workarea():
    display = Gdk.Display.get_default()
    return (display.get_primary_monitor() or display.get_monitor(0)).get_workarea()


def clamp(v, lo, hi):
    return max(lo, min(int(v), hi))


def message_text(res) -> str:
    """Text of a window.webkit.messageHandlers.kurama.postMessage(...) call (JavascriptResult or JSCValue)."""
    try:
        return (res.get_js_value() if hasattr(res, "get_js_value") else res).to_string()
    except Exception:
        return ""


class DesktopBackground:
    """GNOME's own background = our latest dashboard snapshot, so a fresh login shows KURAMA at once. The
    wallpaper the user (or KURAMA) sets is kept in real-wallpaper.json; the API reads it from there."""

    KEYS = ("picture-uri", "picture-uri-dark")

    def __init__(self) -> None:
        try:
            self.gs = Gio.Settings.new("org.gnome.desktop.background")
        except Exception:
            self.gs = None
            return
        self.snap_uri = SNAP.as_uri()
        self.gs.connect("changed::picture-uri", lambda *_: GLib.idle_add(self.claim))

    holding_real = False  # minimized: the desktop shows the user's own plain wallpaper, not a dashboard photo

    def show_real(self) -> None:
        """Mini mode: put the user's real wallpaper back (a still, simple picture) instead of the dashboard
        snapshot, which could even show whatever dialog was open when it was taken."""
        if self.gs is None:
            return
        self.holding_real = True
        try:
            real = json.loads(REAL_WALLPAPER.read_text())
        except (OSError, ValueError):
            real = {}
        uri = real.get("picture-uri", "")
        if not uri or uri == self.snap_uri:
            self.gs.set_string("picture-options", "none")  # no picture known: a plain dark desktop
            Gio.Settings.new("org.gnome.desktop.background").set_string("primary-color", "#0b0c14")
            return
        dark = real.get("picture-uri-dark") or uri
        for k, v in (("picture-uri", uri), ("picture-uri-dark", uri if dark == self.snap_uri else dark)):
            self.gs.set_string(k, v)
        self.gs.set_string("picture-options", real.get("picture-options") or "zoom")

    def show_snapshot(self) -> None:
        """Full KURAMA again: the desktop shows the dashboard snapshot."""
        self.holding_real = False
        self.claim()

    def claim(self) -> bool:
        """A new wallpaper was set: remember it as the real one, then show our snapshot again."""
        if self.gs is None or not SNAP.is_file():
            return False
        if self.holding_real:  # our own show_real() changed it (or the user set one while minimized): keep it
            cur = {k: self.gs.get_string(k) for k in self.KEYS}
            if cur["picture-uri"] != self.snap_uri:
                with contextlib.suppress(OSError):
                    REAL_WALLPAPER.write_text(json.dumps({**cur, "picture-options": self.gs.get_string("picture-options")}))
            return False
        cur = {k: self.gs.get_string(k) for k in self.KEYS}
        if cur["picture-uri"] != self.snap_uri:
            with contextlib.suppress(OSError):
                REAL_WALLPAPER.write_text(json.dumps({**cur, "picture-options": self.gs.get_string("picture-options")}))
            for k in self.KEYS:
                self.gs.set_string(k, self.snap_uri)
            self.gs.set_string("picture-options", "zoom")
        return False


def take_focus(win, view, stamp: int = 0) -> None:
    """Give the window the keyboard. A shortcut arrives as a signal, not a click, so there is no event time and the
    window manager refused focus (Brave kept it; you had to click the chat box). The X server's current time counts
    as a fresh user action."""
    gw = win.get_window()
    if not stamp and gw is not None:
        try:
            gi.require_version("GdkX11", "3.0")
            from gi.repository import GdkX11
            stamp = GdkX11.x11_get_server_time(gw)
        except (ValueError, ImportError, TypeError):
            stamp = 0
    win.present_with_time(stamp)
    if gw is not None:
        gw.focus(stamp)
    if view is not None:
        view.grab_focus()


def run_js(view, code: str) -> None:
    if view is None:  # the dashboard's view is gone while minimized
        return
    if hasattr(view, "evaluate_javascript"):  # WebKitGTK >= 2.40
        view.evaluate_javascript(code, -1, None, None, None, None, None)
    else:
        view.run_javascript(code, None, None, None)


def note(msg: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, file=sys.stderr, flush=True)


class Watchdog:
    """The page's main thread can freeze (an endless loop / stuck WebKit work: 100% CPU, the whole screen stuck while
    the API is fine). Every PING_S the page is asked a tiny question; no answer for HANG_S -> its web process is
    killed and the page loads again by itself. The last state the page reported is logged, to find the cause."""

    def __init__(self, name: str, get_view, reload) -> None:
        self.name, self.get_view, self.reload = name, get_view, reload
        self.sent = 0.0  # monotonic time of the ping still waiting for an answer (0 = none)
        self.last = ""  # the page's own state at its last answer (window.kuramaState)
        self.restarts = 0
        GLib.timeout_add_seconds(PING_S, self.tick)

    def tick(self) -> bool:
        v = self.get_view()
        if v is None:  # no page (minimized / still loading): nothing to watch
            self.sent = 0.0
            return True
        now = time.monotonic()
        if self.sent:
            if now - self.sent >= HANG_S:
                self.restarts += 1
                note(f"watchdog: the {self.name} page froze (no answer for {now - self.sent:.0f} s; last state: "
                     f"{self.last or '?'}); restarting it (#{self.restarts})")
                self.sent = 0.0
                with contextlib.suppress(Exception):
                    v.terminate_web_process()
                GLib.timeout_add(800, lambda: self.reload() and False)
            return True
        self.sent = token = now

        def done(view, res):
            if self.sent == token:
                self.sent = 0.0
            with contextlib.suppress(Exception):
                r = view.evaluate_javascript_finish(res) if hasattr(view, "evaluate_javascript_finish") else \
                    view.run_javascript_finish(res).get_js_value()
                self.last = str(r.to_string())[:4000] if r is not None else ""
        code = "window.kuramaState ? window.kuramaState() : 'up'"
        if PROBE_IN.is_file():  # a developer probe waits: run it instead of the ping, its answer goes to PROBE_OUT
            with contextlib.suppress(OSError):
                code = PROBE_IN.read_text(encoding="utf-8")
                PROBE_IN.unlink()

                def done(view, res, _ping=done):  # noqa: F811
                    _ping(view, res)
                    with contextlib.suppress(OSError):
                        PROBE_OUT.write_text(self.last, encoding="utf-8")
        if hasattr(v, "evaluate_javascript"):
            v.evaluate_javascript(code, -1, None, None, None, done)
        else:
            v.run_javascript(code, None, done)
        return True


class Wallpaper:
    def _make_view(self):
        v = WebKit2.WebView(web_context=self.ctx, user_content_manager=self.ucm)
        v.set_background_color(Gdk.RGBA(0.024, 0.027, 0.043, 1))
        if getattr(self, "settings", None) is None:
            s = self.settings = v.get_settings()
            # GPU compositing OFF by default: measured on this laptop, ALWAYS kept the page's main thread at 100% CPU
            # even with nothing moving (the screen lagged / looked frozen); NEVER: ~0% paused, ~5% active.
            # KURAMA_WP_GPU=1 turns it back on.
            try:
                policy = "ALWAYS" if os.getenv("KURAMA_WP_GPU", "0") == "1" else "NEVER"
                s.set_hardware_acceleration_policy(getattr(WebKit2.HardwareAccelerationPolicy, policy))
            except Exception:
                pass
            # one local page: no caches, no WebGL; keep WebAudio + mic for voice chat
            self.ctx.set_cache_model(WebKit2.CacheModel.DOCUMENT_VIEWER)
            s.set_enable_webgl(False)
            s.set_enable_page_cache(False)
            configure_media(s)
            s.set_javascript_can_open_windows_automatically(False)
        else:
            v.set_settings(self.settings)
        v.connect("permission-request", self.on_permission)
        v.connect("load-failed", self.on_failed)
        v.connect("load-changed", self.on_load)
        v.connect("decide-policy", self.on_policy)
        v.connect("web-process-terminated", self.on_crash)
        return v

    def on_crash(self, view, reason):
        """The page's web process died (crash / out of memory / the watchdog): load the page again."""
        if view is not self.view or self.asleep_page:
            return
        note(f"page process ended ({getattr(reason, 'value_nick', reason)}); reloading")
        self.reload_page()

    def reload_page(self) -> None:
        if self.view is None or self.asleep_page:
            return
        self.loaded = False
        self.view.load_uri(self.url)

    def __init__(self, url: str, as_window: bool) -> None:
        self.url = url
        self.paused: bool | None = None
        self.state = load_state()
        self.mini: Mini | None = None
        self.wake: WakeBridge | None = None
        self.asleep_page = False
        self.win = Gtk.Window(title="KURAMA")
        # the page asks for minimize / restore / hide through window.webkit.messageHandlers.kurama
        self.ucm = WebKit2.UserContentManager()
        self.ucm.register_script_message_handler("kurama")
        self.ucm.connect("script-message-received::kurama", self.on_message)
        self.ctx = lean_context()  # one context for every KURAMA view (dashboard, mini panel, workspace)
        self.view = self._make_view()
        self.view.load_uri(url)
        self.loaded = False  # the live page is up (else the snapshot cover stays)
        self.failed = False  # the current load attempt failed
        self.cover = None
        self.bg = None
        root = self.root = Gtk.Overlay()
        root.add(self.view)
        if not as_window and SNAP.is_file():  # last look of the dashboard until the live page is ready
            with contextlib.suppress(Exception):
                display = Gdk.Display.get_default()
                geo = (display.get_primary_monitor() or display.get_monitor(0)).get_geometry()
                pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(SNAP), geo.width, geo.height, False)
                self.cover = Gtk.Image.new_from_pixbuf(pix)
                root.add_overlay(self.cover)
                GLib.timeout_add_seconds(60, self.uncover)  # never hide a page that can't load forever
        self.win.add(root)

        if as_window:
            self.win.set_default_size(1440, 900)
        else:
            display = Gdk.Display.get_default()
            monitor = display.get_primary_monitor() or display.get_monitor(0)
            geo = monitor.get_geometry()
            self.win.set_type_hint(Gdk.WindowTypeHint.DESKTOP)  # below every window, like a wallpaper
            self.win.set_decorated(False)
            self.win.set_skip_taskbar_hint(True)
            self.win.set_skip_pager_hint(True)
            self.win.set_keep_below(True)
            self.win.stick()
            self.win.move(geo.x, geo.y)
            self.win.set_default_size(geo.width, geo.height)
            if Wnck is not None:
                Wnck.set_client_type(Wnck.ClientType.PAGER)
                self.screen = Wnck.Screen.get_default()
                GLib.timeout_add(CHECK_MS, self.check_covered)
        self.win.connect("destroy", Gtk.main_quit)
        self.win.show_all()
        if not as_window:
            self.bg = DesktopBackground()
            self.bg.claim()
        if self.state.get("minimized"):
            self.minimize()
        self.watchdog = Watchdog("dashboard", lambda: self.view if self.loaded and not self.asleep_page else None,
                                 self.reload_page)

    # The API may start after us at login: keep retrying until the page loads
    def on_failed(self, *_):
        self.failed = True
        GLib.timeout_add(1000, lambda: self.view is not None and self.view.load_uri(self.url) and False)
        return False

    def on_load(self, _view, event):
        if event == WebKit2.LoadEvent.STARTED:
            self.failed = False
        if event == WebKit2.LoadEvent.FINISHED and not self.failed and not self.loaded:
            self.loaded = True
            GLib.timeout_add(2200, self.uncover)  # after the page's boot animation, hidden under the cover
            GLib.timeout_add_seconds(SNAP_FIRST_S, lambda: self.snapshot() and False)  # once
            if not getattr(self, "_snap_timer", 0):  # once, even after restore reloads the page
                self._snap_timer = GLib.timeout_add_seconds(SNAP_EVERY_S, self.snapshot)
        if event == WebKit2.LoadEvent.FINISHED:
            if self.paused:
                run_js(self.view, "window.kuramaPause && window.kuramaPause(true)")
            if self.mini:
                run_js(self.view, "window.kuramaMinimized && window.kuramaMinimized(true)")

    # ---------- instant start: snapshot cover + desktop background ----------
    def uncover(self):
        """Fade the snapshot out over the live page (~0.3 s), then drop it."""
        c, self.cover = self.cover, None
        if c is None:
            return False
        steps = iter(range(9, -1, -1))

        def fade():
            v = next(steps, None)
            if v is None:
                c.destroy()
                return False
            c.set_opacity(v / 10)
            return True
        GLib.timeout_add(30, fade)
        return False

    def snapshot(self):
        """Save how the dashboard looks now (one render + PNG every 10 min; skipped in window mode)."""
        if self.bg is None:
            return False
        if self.asleep_page or self.view is None:
            return True  # minimized: there is no dashboard to photograph (keep the timer for later)

        def done(view, res):
            try:
                surface = view.get_snapshot_finish(res)
                SNAP_DIR.mkdir(parents=True, exist_ok=True)
                tmp = SNAP.with_suffix(".tmp.png")
                surface.write_to_png(str(tmp))
                os.replace(tmp, SNAP)
                self.bg.claim()
            except Exception as e:
                print(f"snapshot failed: {e}", file=sys.stderr)
        def checked(view, res):  # never photograph an open picture/dialog: it would become the desktop
            try:
                busy = view.evaluate_javascript_finish(res).to_boolean()
            except Exception:
                busy = False
            if not busy:
                view.get_snapshot(WebKit2.SnapshotRegion.VISIBLE, WebKit2.SnapshotOptions.NONE, None, done)
        try:
            self.view.evaluate_javascript("!!document.querySelector('dialog[open]') || document.body.classList.contains("
                                          "'minimized')", -1, None, None, None, checked)
        except Exception:
            self.view.get_snapshot(WebKit2.SnapshotRegion.VISIBLE, WebKit2.SnapshotOptions.NONE, None, done)
        return True  # keep repeating every SNAP_EVERY_S

    def on_permission(self, view, req):
        # microphone (audio only) for Mic/Conversation mode, only for our own page's origin
        ok = (isinstance(req, WebKit2.UserMediaPermissionRequest)
              and req.get_property("is-for-audio-device") and not req.get_property("is-for-video-device")
              and origin_of(view.get_uri()) == origin_of(self.url))
        req.allow() if ok else req.deny()
        return True

    def on_policy(self, _view, decision, kind):
        # links in replies open in the normal browser, never inside the wallpaper
        if kind == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
            uri = decision.get_navigation_action().get_request().get_uri()
            if uri.startswith(("http://", "https://")):
                Gtk.show_uri_on_window(self.win, uri, Gdk.CURRENT_TIME)
            decision.ignore()
            return True
        return False

    # ---------- minimize / restore ----------
    def on_message(self, _ucm, res):
        msg = message_text(res)
        if msg == "minimize":
            self.minimize()
        elif msg == "restore":
            self.restore()
        elif msg == "hide" and self.mini:
            self.mini.hide_panel()
        elif self.mini and msg.startswith(("talk:", "state:", "caption:", "ws:", "resize:")):  # only the mini panel sends these
            self.mini.on_page(msg)

    def on_ptt(self):
        """SIGUSR2 from the server's hold-to-talk key watcher: data/ptt.state says down / up / cancel."""
        with contextlib.suppress(OSError, IndexError):
            state = STATE_FILE.with_name("ptt.state").read_text().split()[0]
            if self.mini is not None:
                self.mini.ptt(state)
        return True

    def focus_chat(self):
        """FOCUS_HOTKEY: the typing cursor goes to the mini chat's box (opening it if needed); pressed again while
        typing there, it goes back to the window you came from (the chat stays open). Your selection there is kept:
        nothing is copied or clicked."""
        if self.mini is None:
            self.toggle_mini()
            return True
        self.mini.focus_toggle()
        return True

    def toggle_mini(self):
        """Super+S: open the mini chat (minimizing the big dashboard first if it's up), or hide it."""
        if self.mini is None:
            self.minimize()
            GLib.timeout_add(700, lambda: self.mini is not None and self.mini.show_panel() and False)
        else:
            self.mini.toggle_panel()
        return True  # keep the signal handler

    def minimize(self):
        """Mini mode: the big dashboard is switched OFF (its page unloaded, its window hidden; the desktop shows the
        saved snapshot), so only the floating button, its panel and the backend run. Only "Restore full KURAMA"
        (right-click the button) brings it back."""
        if self.mini is None:
            self.mini = Mini(self)
        self.state["minimized"] = True
        save_state(self.state)
        run_js(self.view, "window.kuramaMinimized && window.kuramaMinimized(true)")  # let it stop its mic first
        GLib.timeout_add(600, self.deep_sleep)

    def deep_sleep(self):
        if not self.state.get("minimized"):
            return False
        self.asleep_page = True
        self.win.hide()
        if self.cover is not None:  # the full-screen snapshot picture shown while loading
            self.cover.destroy()
            self.cover = None
        if self.view is not None:  # destroy the dashboard's view: its web process exits, its memory is freed
            self.root.remove(self.view)
            self.view.destroy()
            self.view = None
        if self.bg is not None:
            self.bg.show_real()  # the desktop: your own still wallpaper, not a photo of the dashboard
        if self.wake is None:
            u = urlsplit(self.url)
            self.wake = WakeBridge(f"{u.scheme}://{u.netloc}", lambda cmd: self.mini and self.mini.wake(cmd))
        return False

    def restore(self):
        if self.wake is not None:
            self.wake.stop()
            self.wake = None
        if self.mini is not None:
            self.mini.close()
            self.mini = None
        self.state["minimized"] = False
        save_state(self.state)
        if self.bg is not None:
            self.bg.show_snapshot()
        if getattr(self, "asleep_page", False):
            self.asleep_page = False
            self.loaded = False
            if self.view is None:
                self.view = self._make_view()
                self.root.add(self.view)
            self.win.show_all()
            self.view.load_uri(self.url)  # back to the full dashboard
        else:
            run_js(self.view, "window.kuramaMinimized && window.kuramaMinimized(false)")

    def check_covered(self):
        if self.asleep_page:
            return True  # minimized: nothing to pause
        try:
            covered = desktop_covered(self.screen)
        except Exception:
            covered = False
        now = time.monotonic()
        # sent on a change AND again every PAUSE_RESEND_S: a pause sent before the page's script had loaded was lost,
        # and the page drew its animations behind full-screen windows all day (11-02: the web process at 25-60% CPU
        # while covered; a re-sent pause took it to 0%)
        if covered != self.paused or now - getattr(self, "_pause_sent", 0.0) >= PAUSE_RESEND_S:
            self.paused = covered
            self._pause_sent = now
            run_js(self.view, f"window.kuramaPause && window.kuramaPause({str(covered).lower()})")
        return True


def _api_token() -> str:
    """JARVIS_API_TOKEN from KURAMA's .env (empty = the API needs none)."""
    env = Path(__file__).resolve().parent.parent / ".env"
    with contextlib.suppress(OSError):
        for line in env.read_text().splitlines():
            if line.startswith("JARVIS_API_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"\'')
    return os.getenv("JARVIS_API_TOKEN", "")


_TOKEN: str | None = None


def api_get(page_url: str, path: str, timeout: float = 5) -> dict:
    global _TOKEN
    u = urlsplit(page_url)
    token = _TOKEN = _TOKEN if _TOKEN is not None else _api_token()
    r = urllib.request.Request(f"{u.scheme}://{u.netloc}{path}",
                               headers={"Authorization": f"Bearer {token}"} if token else {})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


class WakeBridge:
    """While minimized, the big dashboard page is unloaded, so THIS process keeps the wake word: it asks the API
    to listen (cheap, server-side) and, on "KURAMA / wake up", opens the mini panel in talk mode."""

    def __init__(self, base: str, on_wake) -> None:
        self.base, self.on_wake = base.rstrip("/"), on_wake
        self.stop_ev = threading.Event()
        self.armed = threading.Event()
        self.token = _api_token()
        threading.Thread(target=self._run, daemon=True, name="wake-bridge").start()

    def _req(self, path: str, method: str = "GET", timeout: float = 10):
        r = urllib.request.Request(self.base + path, method=method, data=b"{}" if method == "POST" else None,
                                   headers={"Content-Type": "application/json",
                                            **({"Authorization": f"Bearer {self.token}"} if self.token else {})})
        return urllib.request.urlopen(r, timeout=timeout)

    def arm(self) -> None:
        """Listen for the wake phrase again (after a conversation in the panel ended)."""
        self.armed.set()

    def disarm(self) -> None:
        self.armed.clear()
        with contextlib.suppress(Exception):
            self._req("/api/v1/wake/awake", "POST").close()

    def stop(self) -> None:
        self.stop_ev.set()
        self.disarm()

    def _run(self) -> None:
        # not armed by itself: listening for the wake phrase holds the mic, so only talk mode's sleep does it
        # (the page asks the API); text / voice mode leave the laptop's mic free
        while not self.stop_ev.is_set():
            if not self.armed.wait(1):
                continue
            try:
                self._req("/api/v1/wake/sleep", "POST").close()
                with self._req("/api/v1/wake/events", timeout=3600) as resp:
                    for raw in resp:
                        if self.stop_ev.is_set() or not self.armed.is_set():
                            break
                        line = raw.decode(errors="replace").strip()
                        if not line.startswith("data:"):
                            continue
                        with contextlib.suppress(ValueError):
                            ev = json.loads(line[5:])
                            if ev.get("type") == "wake":
                                self.armed.clear()  # the panel has the mic now; re-armed when talk ends
                                GLib.idle_add(self.on_wake, ev.get("command") or "")
                                break
            except Exception:  # API restarting / offline: try again shortly
                time.sleep(5)


def pttlog(line: str) -> None:
    """data/logs/ptt.log (shared with the server's key watcher): what the window did for hold-to-talk."""
    try:
        path = STATE_FILE.parent / "logs" / "ptt.log"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(time.strftime("%m-%d %H:%M:%S.") + f"{time.time() % 1:.2f}"[2:] + " window " + line + "\n")
    except OSError:
        pass


def clear_window(_w, cr) -> bool:
    """Paint a transparent window clear, then let its child (the page) draw on top."""
    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.set_source_rgba(0, 0, 0, 0)
    cr.paint()
    cr.set_operator(cairo.OPERATOR_OVER)
    return False


class Mini:
    """Mini KURAMA: a round button above every window (drag to move, click = chat, right-click = menu) and a
    small chat panel. The panel's WebView shares the wallpaper's web process (related-view), so it adds little
    RAM; it is created on first click and dropped on restore. The button itself is a few lines of cairo."""

    def __init__(self, wp: Wallpaper) -> None:
        self.wp = wp
        self.panel = self.view = None
        self.drag = None  # [root x, root y, window x, window y, moved]
        self.reaper = 0  # timer that closes the hidden panel
        self.hover = False
        self.talking = False  # the panel's page is in talk mode
        self.size_timer = 0
        self.anim, self.phase = 0, 0.0  # the busy animation's timer and step
        self.anim_ms, self.fader = 0, 0
        self.ptt_active = False  # a hold-to-talk key is down right now
        if not PANEL_KEEP_S:  # the first hold-to-talk never waits for the page to load
            GLib.timeout_add_seconds(PANEL_PRELOAD_S, self._preload)
        self.logo = None
        with contextlib.suppress(Exception):  # KURAMA's fox on the button (frontend/kurama-logo.svg)
            self.logo = GdkPixbuf.Pixbuf.new_from_file_at_size(
                str(Path(__file__).resolve().parent.parent / "frontend" / "kurama-logo.svg"), 24, 24)
        self.ghost = False  # panel "closed" but still alive (invisible, click-through) so talk mode keeps going
        self.state = "idle"  # voice state shown by the ring while ghosted
        self.caption = None  # Caption window, made on first use
        self.ws = self.ws_view = None  # the workspace window, made when needed
        self.ws_hidden = False  # the shortcut hid the workspace along with the chat: it comes back with it
        self.alert_last = 0  # newest alert already seen; new ones pop up beside the button (download done, reminder...)
        self.alert_busy = False
        self.alert_timer = GLib.timeout_add_seconds(ALERT_POLL_S, self.poll_alerts)
        b = self.bubble = Gtk.Window(title="KURAMA mini")
        b.set_decorated(False)
        b.set_resizable(False)
        b.set_skip_taskbar_hint(True)
        b.set_skip_pager_hint(True)
        b.set_type_hint(Gdk.WindowTypeHint.DOCK)  # above normal and keep-above windows, never focused
        b.set_keep_above(True)
        b.set_accept_focus(False)
        b.stick()
        b.set_size_request(BUBBLE, BUBBLE)
        visual = b.get_screen().get_rgba_visual()
        if visual is not None:  # transparent corners = a round button (needs a compositor)
            b.set_visual(visual)
        b.set_app_paintable(True)
        b.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                     | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK
                     | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        b.connect("draw", self.on_draw)
        b.connect("button-press-event", self.on_press)
        b.connect("motion-notify-event", self.on_motion)
        b.connect("button-release-event", self.on_release)
        b.connect("enter-notify-event", lambda *_: self.set_hover(True))
        b.connect("leave-notify-event", lambda *_: self.set_hover(False))
        wa = workarea()
        x, y = wp.state.get("x"), wp.state.get("y")
        if x is None or y is None:  # first time: right edge, a bit below the middle
            x, y = wa.x + wa.width - BUBBLE - 18, wa.y + int(wa.height * 0.62)
        b.move(clamp(x, wa.x, wa.x + wa.width - BUBBLE), clamp(y, wa.y, wa.y + wa.height - BUBBLE))
        b.show_all()
        GLib.idle_add(lambda: self.animate(False) and False)  # the button's slow idle ring

    @property
    def open(self) -> bool:
        return self.panel is not None and self.panel.get_visible() and not self.ghost

    # ---------- messages from the panel's page ----------
    def on_page(self, msg: str) -> None:
        kind, _, rest = msg.partition(":")
        if kind == "talk":
            self.talking = rest == "on"
            if not self.talking and self.ghost:  # talk mode ended while closed: really hide now
                self.end_ghost()
        elif kind == "state":
            if rest != self.state:
                self.state = rest
                self.bubble.queue_draw()
                self.animate(rest in BUSY_STATES)
            if self.ghost and not self.talking and rest not in BUSY_STATES:
                # closed while a reply was on its way (any mode): it's done; wait a moment (the reply's caption
                # arrives right after, or it starts speaking), then really hide, keeping the caption up
                GLib.timeout_add(1500, self.end_ghost_if_idle)
        elif kind == "resize" and self.panel is not None:  # the page's edge was dragged: let the WM resize it
            edge = {"n": Gdk.WindowEdge.NORTH, "s": Gdk.WindowEdge.SOUTH, "e": Gdk.WindowEdge.EAST,
                    "w": Gdk.WindowEdge.WEST, "ne": Gdk.WindowEdge.NORTH_EAST, "nw": Gdk.WindowEdge.NORTH_WEST,
                    "se": Gdk.WindowEdge.SOUTH_EAST, "sw": Gdk.WindowEdge.SOUTH_WEST}.get(rest)
            if edge is not None:
                _, x, y = Gdk.Display.get_default().get_default_seat().get_pointer().get_position()
                self.panel.begin_resize_drag(edge, 1, x, y, Gtk.get_current_event_time())
        elif kind == "ws":  # the panel asks for its workspace window (button, or a finished job with a result)
            self.open_ws(focus=rest != "quiet")
        elif kind == "pttlog":
            pttlog("page " + rest)
        elif kind == "caption" and self.ghost:
            with contextlib.suppress(ValueError, TypeError):
                d = json.loads(rest)
                if self.caption is None:
                    self.caption = Caption(self)
                self.caption.show(d.get("who", "bot"), str(d.get("text", "")), bool(d.get("done")))

    # ---------- the button ----------
    def on_draw(self, _w, cr):
        """A glass disc (translucent indigo, light from the top-left, thin rim), the fox logo, and a gradient ring
        that slowly turns (idle) or runs in the state's colour (listening / thinking / speaking)."""
        c = BUBBLE / 2
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        busy = self.state in BUSY_STATES
        lit = self.hover or self.open
        pulse = 0.5 + 0.5 * math.sin(self.phase * (1 if busy else 0.5))
        halo = cairo.RadialGradient(c, c, c * 0.55, c, c, c)  # soft outer glow, breathing
        halo.add_color_stop_rgba(0, 0.43, 0.48, 1, 0)
        halo.add_color_stop_rgba(0.75, 0.48, 0.42, 1, (0.16 if lit else 0.08) + 0.10 * pulse)
        halo.add_color_stop_rgba(1, 0.48, 0.42, 1, 0)
        cr.arc(c, c, c, 0, 2 * math.pi)
        cr.set_source(halo)
        cr.fill()
        r = c - 5
        body = cairo.LinearGradient(0, 0, 0, BUBBLE)  # the glass: see-through indigo
        body.add_color_stop_rgba(0, 0.16, 0.17, 0.34, 0.72)
        body.add_color_stop_rgba(1, 0.06, 0.07, 0.16, 0.80)
        cr.arc(c, c, r, 0, 2 * math.pi)
        cr.set_source(body)
        cr.fill()
        shine = cairo.RadialGradient(c * 0.7, c * 0.45, 1, c * 0.7, c * 0.45, r)  # light on the glass
        shine.add_color_stop_rgba(0, 1, 1, 1, 0.22 if lit else 0.15)
        shine.add_color_stop_rgba(1, 1, 1, 1, 0)
        cr.arc(c, c, r, 0, 2 * math.pi)
        cr.set_source(shine)
        cr.fill()
        if self.logo is not None:  # KURAMA's fox
            lw = self.logo.get_width()
            Gdk.cairo_set_source_pixbuf(cr, self.logo, c - lw / 2, c - lw / 2 + 1)
            cr.paint_with_alpha(1 if lit else 0.92)
        ring = RING.get(self.state) if self.ghost or busy else None
        a = self.phase * (0.9 if busy else 0.35)
        grad = cairo.LinearGradient(c + r * math.cos(a), c + r * math.sin(a), c - r * math.cos(a), c - r * math.sin(a))
        if ring:
            grad.add_color_stop_rgba(0, *ring, 1)
            grad.add_color_stop_rgba(1, *ring, 0.15)
        else:
            grad.add_color_stop_rgba(0, 0.55, 0.64, 1, 0.95 if lit else 0.8)
            grad.add_color_stop_rgba(0.5, 0.62, 0.4, 1, 0.55)
            grad.add_color_stop_rgba(1, 1, 1, 1, 0.12)
        cr.set_line_width(2.2 if ring or lit else 1.6)
        cr.arc(c, c, r, 0, 2 * math.pi)
        cr.set_source(grad)
        cr.stroke()
        return True

    def animate(self, on: bool) -> None:
        """Busy (listening / thinking / speaking): ~20 redraws a second. Idle: the ring turns slowly at ~8 a second
        (a 56 px drawing: negligible CPU)."""
        want = 50 if on else IDLE_ANIM_MS
        if self.anim and self.anim_ms == want:
            return
        if self.anim:
            GLib.source_remove(self.anim)
            self.anim = 0
        if want:
            self.anim, self.anim_ms = GLib.timeout_add(want, self._tick), want
        self.bubble.queue_draw()

    def _tick(self) -> bool:
        self.phase = (self.phase + (0.16 if self.anim_ms == 50 else 0.1)) % (2 * math.pi * 20)
        self.bubble.queue_draw()
        return True

    def fade(self, win, show: bool, then=None) -> None:
        """A short fade (~140 ms) when the panel opens / closes."""
        if self.fader:
            GLib.source_remove(self.fader)
            self.fader = 0
        step = [0]

        def tick():
            step[0] += 1
            t = min(1.0, step[0] / 7)
            win.set_opacity(t if show else 1 - t)
            if t >= 1:
                self.fader = 0
                if then:
                    then()
                return False
            return True
        win.set_opacity(0 if show else 1)
        self.fader = GLib.timeout_add(20, tick)

    def set_hover(self, on: bool) -> None:
        self.hover = on
        self.bubble.queue_draw()

    def on_press(self, _w, ev):
        if ev.type != Gdk.EventType.BUTTON_PRESS:  # ignore the extra double-click event
            return True
        if ev.button == 3:
            self.menu(ev)
        elif ev.button == 1:
            x, y = self.bubble.get_position()
            self.drag = [ev.x_root, ev.y_root, x, y, False]
        return True

    def on_motion(self, _w, ev):
        d = self.drag
        if not d:
            return False
        dx, dy = ev.x_root - d[0], ev.y_root - d[1]
        if not d[4] and abs(dx) + abs(dy) < 5:  # a click, not a drag (yet)
            return True
        d[4] = True
        wa = workarea()
        self.bubble.move(clamp(d[2] + dx, wa.x, wa.x + wa.width - BUBBLE), clamp(d[3] + dy, wa.y, wa.y + wa.height - BUBBLE))
        if self.open:
            self.place_panel()
        if self.caption is not None and self.caption.win.get_visible():
            self.caption.place()
        return True

    def on_release(self, _w, ev):
        d, self.drag = self.drag, None
        if ev.button != 1 or not d:
            return True
        if d[4]:
            self.wp.state["x"], self.wp.state["y"] = self.bubble.get_position()
            save_state(self.wp.state)
        else:
            self.hide_panel() if self.open else self.show_panel(ev.time)
        return True

    def menu(self, ev):
        m = Gtk.Menu()
        for label, fn in (("Hide chat" if self.open else "Open chat", lambda *_: self.hide_panel() if self.open else self.show_panel()),
                          ("Restore full KURAMA", lambda *_: self.wp.restore())):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", fn)
            m.append(item)
        m.show_all()
        m.attach_to_widget(self.bubble)
        m.popup_at_pointer(ev)

    # ---------- the chat panel ----------
    def wake(self, command: str = "") -> bool:
        """The wake phrase was heard while minimized: open the panel and talk (the panel's page wakes up)."""
        fresh = self.panel is None
        self.show_panel()
        js = f"window.kuramaMiniWake && window.kuramaMiniWake({json.dumps(command)})"
        if fresh:  # the page is still loading: wake it once it is there
            def loaded(view, event):
                if event == WebKit2.LoadEvent.FINISHED:
                    view.disconnect(hid)
                    GLib.timeout_add(400, lambda: run_js(view, js) and False)
            hid = self.view.connect("load-changed", loaded)
        else:
            run_js(self.view, js)
        return False

    def ptt(self, state: str) -> None:
        """Hold-to-talk from jarvis/core/ptt.py: down = listen (panel stays closed: an invisible, click-through
        page records and the caption beside the button shows what you said and the reply), up = send, cancel."""
        if state == "dismiss":  # Super+X: close the caption now and stop the spoken reply
            if self.caption is not None:
                self.caption.hide()
            if self.view is not None:
                run_js(self.view, "window.kuramaPTT && window.kuramaPTT(-2)")
            if self.ghost and not self.ptt_active:
                GLib.timeout_add(300, self.end_ghost_if_idle)
            return
        js = {"down": 1, "up": 0, "cancel": -1}.get(state)
        if js is None:
            return
        pttlog(f"got {state}: open={self.open} ghost={self.ghost} ready={getattr(self, 'page_ready', False)} "
               f"busy={self.state}")
        was_listening = self.ptt_active
        self.ptt_active = state == "down"
        if self.open:  # the chat is open: it all happens there
            run_js(self.view, f"window.kuramaPTT && window.kuramaPTT({js})")
            return
        if state == "cancel" and was_listening and self.caption is not None:  # Alt + Shift (or any key): say so,
            self.caption.you.set_text("")  # "Listening…" used to stay on screen
            self.caption.show("bot", "Cancelled. Nothing was sent.", True)
        if state != "down" and not self.ghost:
            return
        if state == "down":
            if self.reaper:
                GLib.source_remove(self.reaper)
                self.reaper = 0
            self.ensure_panel()
            if not self.ghost:  # alive but invisible and click-through, like talk mode with the panel closed
                self.ghost = True
                self.panel.realize()  # opacity / click-through set on the real window BEFORE it maps (a new panel
                self.panel.set_opacity(0)  # flashed as a dark box for a moment on the first hold)
                self.panel.input_shape_combine_region(cairo.Region())
                self.panel.set_keep_above(False)
                self.place_panel()
                self.panel.show_all()
            if self.caption is None:
                self.caption = Caption(self)
            ready = getattr(self, "page_ready", False)
            self.caption.show("you", "Listening…" if ready else "Getting ready… keep holding", False)
            if not ready:  # never stuck on "Getting ready" (11-02: the page's web process was broken)
                GLib.timeout_add_seconds(PANEL_READY_S, self._ready_or_restart)
        self.ptt_last = state
        if getattr(self, "page_ready", False):
            run_js(self.view, f"window.kuramaMiniShown && window.kuramaMiniShown(false, true); "
                              f"window.kuramaPTT && window.kuramaPTT({js})")
        elif not getattr(self, "ptt_waiting", False):  # the page is (re)loading: when it's there, only the LATEST
            self.ptt_waiting = True  # key state counts (a release during the load was lost: a stuck recording)

            def apply():
                self.ptt_waiting = False
                last = self.ptt_last
                if last == "down":  # still held: start listening now
                    run_js(self.view, "window.kuramaMiniShown && window.kuramaMiniShown(false, true); "
                                      "window.kuramaPTT && window.kuramaPTT(1)")
                    return
                if last == "up" and self.caption is not None:
                    self.caption.show("bot", "I was just waking up. Hold the talk key again and speak.", True)
                self.ptt_active = False
                GLib.timeout_add(600, self.end_ghost_if_idle)
            self.when_ready(apply)
        if state == "cancel":
            GLib.timeout_add(600, self.end_ghost_if_idle)

    def ensure_panel(self) -> None:
        if self.panel is not None:
            return
        p = self.panel = Gtk.Window(title="KURAMA")
        p.set_wmclass("kurama-mini", "KURAMA-mini")  # its own class: Blur my Shell blurs only this window
        visual = p.get_screen().get_rgba_visual()
        if visual is not None:  # transparent window: the page draws round corners + glass (needs a compositor)
            p.set_visual(visual)
            p.set_app_paintable(True)
            p.connect("draw", clear_window)
        p.set_decorated(False)
        p.set_skip_taskbar_hint(True)
        p.set_skip_pager_hint(True)
        p.set_keep_above(True)
        p.stick()
        wa = workarea()
        p.set_size_request(PANEL_MIN_W, PANEL_MIN_H)
        p.set_default_size(min(int(self.wp.state.get("panel_w") or PANEL_W), wa.width - 40),
                           min(int(self.wp.state.get("panel_h") or PANEL_H), wa.height - 40))
        p.connect("configure-event", self.on_configure)
        p.connect("delete-event", lambda *_: self.hide_panel() or True)
        v = self.view = WebKit2.WebView(web_context=self.wp.ctx, user_content_manager=self.wp.ucm)
        v.set_settings(self.wp.settings)
        v.set_background_color(Gdk.RGBA(0, 0, 0, 0) if visual is not None else Gdk.RGBA(0.11, 0.11, 0.12, 1))
        v.connect("permission-request", self.wp.on_permission)
        v.connect("decide-policy", self.wp.on_policy)
        self.page_ready, self.on_ready = False, []
        v.connect("load-changed", self._page_loaded)
        v.connect("web-process-terminated", self._panel_crashed)
        u = urlsplit(self.wp.url)
        self.panel_url = f"{u.scheme}://{u.netloc}/?mini=1" + ("" if visual is not None else "&opaque=1")
        v.load_uri(self.panel_url)
        p.add(v)

    def _panel_crashed(self, view, reason) -> None:
        """The mini chat's web process died: load it again (it stayed blank and "Getting ready" forever)."""
        pttlog(f"panel page process ended ({getattr(reason, 'value_nick', reason)}); reloading")
        self.page_ready = False
        GLib.timeout_add(800, lambda: (view.load_uri(self.panel_url), False)[1])

    def _ready_or_restart(self) -> bool:
        """A hold showed "Getting ready" and the page still isn't there: its web process is stuck -> restart it."""
        if getattr(self, "page_ready", False) or self.view is None:
            return False
        pttlog(f"panel page not ready after {PANEL_READY_S} s: restarting its web process")
        if self.caption is not None:
            self.caption.show("bot", "The chat window got stuck, so I'm restarting it. Hold the key again in a few "
                                     "seconds.", True)
        with contextlib.suppress(Exception):
            self.view.terminate_web_process()  # -> _panel_crashed -> load again
        return False

    def _page_loaded(self, view, event) -> None:
        if event != WebKit2.LoadEvent.FINISHED or self.page_ready:
            return
        def ready():  # a moment for the first paint, then whatever waited for the page
            self.page_ready = True
            pttlog(f"panel page ready (shown={bool(self.panel and self.panel.get_visible())})")
            waiting, self.on_ready = self.on_ready, []
            for fn in waiting:
                fn()
            return False
        GLib.timeout_add(250, ready)

    def _preload(self) -> bool:
        if self.panel is None:
            self.ensure_panel()  # created hidden: nothing is shown until a click or a hold
        return False

    def when_ready(self, fn) -> None:
        """Run fn now if the panel's page is loaded, else as soon as it is."""
        if getattr(self, "page_ready", False):
            fn()
        else:
            self.on_ready.append(fn)

    def beside(self, w: int, h: int, top: bool = False) -> tuple[int, int]:
        """Where a w x h window goes next to the button without ever covering it: the side towards the middle of
        the screen first, then the other side, then above / below."""
        bx, by = self.bubble.get_position()
        wa = workarea()
        gap = 10
        cx = clamp(bx + BUBBLE // 2 - w // 2, wa.x + 8, wa.x + wa.width - w - 8)
        cy = by if top else by + BUBBLE - h
        towards_left = bx + BUBBLE / 2 > wa.x + wa.width / 2
        sides = [(bx - w - gap, cy), (bx + BUBBLE + gap, cy)]
        if not towards_left:
            sides.reverse()
        cands = sides + [(cx, by - h - gap), (cx, by + BUBBLE + gap)]
        best = None
        for x, y in cands:
            x2 = clamp(x, wa.x + 8, wa.x + wa.width - w - 8)
            y2 = clamp(y, wa.y + 8, wa.y + wa.height - h - 8)
            covers = x2 < bx + BUBBLE and bx < x2 + w and y2 < by + BUBBLE and by < y2 + h
            if not covers:
                return x2, y2
            best = best or (x2, y2)
        return best

    def place_panel(self) -> None:
        self.panel.move(*self.beside(*self.panel.get_size()))

    def show_panel(self, time: int = 0) -> None:
        if self.reaper:
            GLib.source_remove(self.reaper)
            self.reaper = 0
        if self.caption is not None:
            self.caption.hide()
        self.unghost()
        self.ensure_panel()
        stamp = time or Gtk.get_current_event_time()

        def show():  # only once its page is there: a reloaded page showed an empty glass box first
            if self.panel is None or self.ghost:
                return
            self.panel.show_all()
            self.place_panel()
            self.fade(self.panel, True)
            take_focus(self.panel, self.view, stamp)  # type at once, wherever you were (Ctrl+Alt+K came as a signal:
            run_js(self.view, "window.kuramaMiniShown && window.kuramaMiniShown(true)")  # no event time -> no focus)
            self.bubble.queue_draw()
        self.when_ready(show)
        self.bubble.queue_draw()

    def hide_panel(self) -> None:
        if self.open and (self.talking or self.state in BUSY_STATES):
            # talk mode, or a reply still on its way: keep the page alive, just invisible and click-through
            run_js(self.view, "window.kuramaMiniShown && window.kuramaMiniShown(false, true)")
            self.ghost = True
            self.panel.set_opacity(0)
            self.panel.set_keep_above(False)
            self.panel.input_shape_combine_region(cairo.Region())  # empty: clicks go through
        elif self.open:
            run_js(self.view, "window.kuramaMiniShown && window.kuramaMiniShown(false)")  # stops the mic, saves the chat

            def gone():
                if self.panel is not None:
                    self.panel.hide()
                    self.panel.set_opacity(1)
                    if not self.reaper and PANEL_KEEP_S:
                        self.reaper = GLib.timeout_add_seconds(PANEL_KEEP_S, self.drop_panel)
                    self.bubble.queue_draw()
            self.fade(self.panel, False, gone)
        self.bubble.queue_draw()

    def unghost(self, hide_caption: bool = True) -> None:
        if not self.ghost or self.panel is None:
            self.ghost = False
            return
        self.ghost = False
        self.state = "idle"
        self.animate(False)
        self.panel.input_shape_combine_region(None)  # clickable again (the Gdk call refuses None)
        self.panel.set_opacity(1)
        self.panel.set_keep_above(True)
        if hide_caption and self.caption is not None:
            self.caption.hide()

    def end_ghost(self, keep_caption: bool = False) -> None:
        """The closed-but-alive panel has nothing left to do: hide it for real (its page stops the mic, saves the chat)."""
        pttlog(f"end_ghost (keep_caption={keep_caption}, state={self.state}, ptt_active={self.ptt_active})")
        self.panel.hide()
        self.unghost(hide_caption=not keep_caption)
        run_js(self.view, "window.kuramaMiniShown && window.kuramaMiniShown(false)")
        if not self.reaper and PANEL_KEEP_S:
            self.reaper = GLib.timeout_add_seconds(PANEL_KEEP_S, self.drop_panel)
        self.bubble.queue_draw()

    def end_ghost_if_idle(self):
        if self.ptt_active:  # a new hold-to-talk started meanwhile: never hide its page mid-recording
            return False
        if self.ghost and not self.talking and self.state not in BUSY_STATES and self.panel is not None:
            self.end_ghost(keep_caption=True)
        return False

    def focus_toggle(self) -> None:
        # "am I in KURAMA?" from the window manager (any KURAMA window: the chat or the dashboard), not GTK's
        # is_active (it said no while the owner typed in the chat, so the key never went back, 11-01)
        if self.open and self.panel is not None and self._user_window(top=False) == 0:  # typing here: go back
            back = getattr(self, "came_from", 0) or self._user_window(top=True)
            if back:
                subprocess.run(["wmctrl", "-i", "-a", hex(back)], capture_output=True, timeout=3)
            self.panel.set_keep_above(True)  # the chat stays on screen; only the typing cursor moved
            return
        self.came_from = self._user_window(top=False)
        if not self.open:
            self.show_panel()
        else:
            take_focus(self.panel, self.view, 0)
            run_js(self.view, "window.kuramaMiniShown && window.kuramaMiniShown(true)")  # the box gets the cursor

    @staticmethod
    def _user_window(top: bool) -> int:
        """The window you work in: the active one (top=False), or the highest non-KURAMA one in the stack (top=True:
        the chat was opened another way, so where you came from wasn't recorded). 0 = none."""
        with contextlib.suppress(Exception):
            gi.require_version("Wnck", "3.0")
            from gi.repository import Wnck
            scr = Wnck.Screen.get_default()
            scr.force_update()
            mine = lambda w: "kurama" in (w.get_class_instance_name() or "").lower()  # noqa: E731
            if not top:
                w = scr.get_active_window()
                return w.get_xid() if w is not None and not mine(w) else 0
            for w in reversed(scr.get_windows_stacked()):
                if not mine(w) and not w.is_minimized() and w.get_window_type() == Wnck.WindowType.NORMAL:
                    return w.get_xid()
        return 0

    def toggle_panel(self) -> None:
        """The shortcut: chat and its workspace window hide together and come back together."""
        if self.open:
            self.hide_panel()
            if self.ws is not None and self.ws.get_visible():
                self.ws.hide()
                self.ws_hidden = True
        else:
            self.show_panel()
            if self.ws is not None and self.ws_hidden:
                self.ws.show()
            self.ws_hidden = False

    def poll_alerts(self) -> bool:
        """Every few seconds (in a thread): new alerts -> a bubble beside the button, unless the chat is open."""
        if self.alert_busy:
            return True
        self.alert_busy = True

        def fetch():
            try:
                d = api_get(self.wp.url, f"/api/v1/alerts/new?after={self.alert_last}")
                self.alert_last = int(d.get("last") or self.alert_last)
                for a in d.get("items", [])[-2:]:
                    GLib.idle_add(self.show_alert, a)
            except Exception:  # noqa: BLE001 - API restarting / offline: next tick
                pass
            finally:
                self.alert_busy = False
        threading.Thread(target=fetch, daemon=True, name="mini-alerts").start()
        return True

    def show_alert(self, a: dict) -> bool:
        if self.open:  # the chat is in front of the user anyway
            return False
        if self.caption is None:
            self.caption = Caption(self)
        text = f"🔔 {a.get('title', '')}" + (f"\n{a['text'][:240]}" if a.get("text") else "")
        self.caption.show("bot", text, True)
        return False

    def on_configure(self, win, _ev):
        """Remember the panel's size (saved 1 s after the last resize)."""
        if self.size_timer:
            GLib.source_remove(self.size_timer)

        def save():
            self.size_timer = 0
            if self.panel is not None and self.panel.get_visible() and not self.ghost:
                w, h = self.panel.get_size()
                if (w, h) != (self.wp.state.get("panel_w"), self.wp.state.get("panel_h")):
                    self.wp.state["panel_w"], self.wp.state["panel_h"] = w, h
                    save_state(self.wp.state)
            return False
        self.size_timer = GLib.timeout_add(1000, save)
        return False

    def drop_panel(self):
        """Hidden for a while: close the panel's page (~45 MB); the next click reopens it with the chat restored."""
        self.reaper = 0
        if self.panel is not None and not self.panel.get_visible():
            self.panel.destroy()
            self.panel = self.view = None
        return False

    # ---------- workspace: its OWN small window next to the chat (close / minimize / move it like any window) ----
    def open_ws(self, focus: bool = True) -> None:
        if self.ws is not None:
            run_js(self.ws_view, "window.kuramaWsRefresh && window.kuramaWsRefresh()")
            if focus:
                self.ws.present()
            return
        w = self.ws = Gtk.Window(title="KURAMA · Workspace")
        w.set_wmclass("kurama-mini", "KURAMA-mini")  # same glass as the chat panel (Blur my Shell)
        wsvis = w.get_screen().get_rgba_visual()
        if wsvis is not None:
            w.set_visual(wsvis)
            w.set_app_paintable(True)
            w.connect("draw", clear_window)
        w.set_default_size(WS_W, min(WS_H, workarea().height - 60))
        w.set_skip_pager_hint(True)
        with contextlib.suppress(Exception):
            w.set_icon_name("folder-documents")
        v = self.ws_view = WebKit2.WebView(web_context=self.wp.ctx, user_content_manager=self.wp.ucm)
        v.set_settings(self.wp.settings)
        v.set_background_color(Gdk.RGBA(0, 0, 0, 0) if wsvis is not None else Gdk.RGBA(0.07, 0.08, 0.16, 1))
        v.connect("decide-policy", self.wp.on_policy)
        u = urlsplit(self.wp.url)
        v.load_uri(f"{u.scheme}://{u.netloc}/?mini=1&ws=1")  # the workspace-only page: no chat, no mic
        w.add(v)
        w.connect("destroy", self._ws_closed)
        bx, by = self.bubble.get_position()  # on the other side of the button from the chat panel
        wa = workarea()
        right = bx + BUBBLE / 2 > wa.x + wa.width / 2
        x = bx - PANEL_W - WS_W - 30 if right else bx + BUBBLE + PANEL_W + 30
        w.move(clamp(x, wa.x + 8, wa.x + wa.width - WS_W - 8), clamp(by - WS_H + BUBBLE, wa.y + 8, wa.y + wa.height - WS_H))
        w.set_focus_on_map(focus)  # opened by a finished job: don't steal the keyboard from what you're typing
        w.show_all()

    def _ws_closed(self, *_):
        self.ws = self.ws_view = None  # closing frees its page

    def close(self) -> None:
        GLib.source_remove(self.alert_timer)
        self.animate(False)
        if self.ws is not None:
            self.ws.destroy()
        if self.reaper:
            GLib.source_remove(self.reaper)
        if self.panel is not None:
            self.panel.destroy()
        if self.caption is not None:
            self.caption.win.destroy()
        self.bubble.destroy()
        self.panel = self.view = self.caption = None


class Caption:
    """A small reply bubble next to mini KURAMA's button (like Gemini's): what you said, then the reply as it
    streams in; it fades out a few seconds after the reply is done. Click it to open the chat."""

    CSS = b"""
    .kcap { background-image: linear-gradient(160deg, rgba(110, 123, 255, 0.20), rgba(16, 19, 40, 0.55) 55%,
                                                      rgba(139, 92, 246, 0.16));
            background-color: rgba(16, 19, 40, 0.50); border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 15px; padding: 11px 15px; }
    .kcap .you { color: rgba(226, 230, 255, 0.62); font-size: 9.5pt; }
    .kcap .bot { color: #f4f5ff; font-size: 10.5pt; }
    .kcap label { font-family: "Ubuntu Sans", Ubuntu, "Noto Sans", sans-serif; }
    """

    def __init__(self, mini: Mini) -> None:
        self.mini = mini
        self.timer = 0
        css = Gtk.CssProvider()
        css.load_from_data(self.CSS)
        w = self.win = Gtk.Window(title="KURAMA caption")
        w.set_wmclass("kurama-mini", "KURAMA-mini")  # glass: Blur my Shell blurs behind it (a DOCK window never is)
        w.get_style_context().add_provider_for_screen(w.get_screen(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        w.set_decorated(False)
        w.set_resizable(False)
        w.set_skip_taskbar_hint(True)
        w.set_skip_pager_hint(True)
        w.set_focus_on_map(False)
        w.set_keep_above(True)
        w.set_accept_focus(False)
        w.stick()
        visual = w.get_screen().get_rgba_visual()
        if visual is not None:
            w.set_visual(visual)
        w.set_app_paintable(True)
        w.connect("draw", self.on_draw)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.get_style_context().add_class("kcap")
        self.you, self.bot = Gtk.Label(xalign=0), Gtk.Label(xalign=0)
        for lab, cls in ((self.you, "you"), (self.bot, "bot")):
            lab.set_line_wrap(True)
            lab.set_max_width_chars(34)
            lab.set_lines(6)
            lab.set_ellipsize(3)  # Pango.EllipsizeMode.END
            lab.get_style_context().add_class(cls)
            box.pack_start(lab, False, False, 0)
        ev = Gtk.EventBox()
        ev.set_visible_window(False)
        ev.add(box)
        ev.connect("button-release-event", lambda *_: self.mini.show_panel() or True)
        w.add(ev)
        w.set_size_request(CAPTION_W, -1)

    @staticmethod
    def on_draw(_w, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        return False  # then GTK draws the rounded box

    def show(self, who: str, text: str, done: bool) -> None:
        text = " ".join(text.split())
        if not text:
            return
        if who == "you":
            self.you.set_text(text[-160:])
            self.bot.set_text("…")
        else:
            self.bot.set_text(text if len(text) <= 420 else text[:420].rsplit(" ", 1)[0] + "…")
        self.you.set_visible(bool(self.you.get_text()))
        if not self.win.get_visible():  # place it BEFORE it appears: shown first, it flashed at the screen's top-left
            self.win.get_child().show_all()
            _, nat = self.win.get_preferred_size()
            self.win.move(*self.mini.beside(CAPTION_W, max(40, nat.height)))
        self.win.show_all()
        self.win.resize(CAPTION_W, 1)  # shrink to the text
        self.place()
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        # done: long enough to read it (~15 characters a second, 5..14 s); else a safety net if no reply comes
        self.timer = GLib.timeout_add_seconds(int(clamp(len(text) / 15, 5, 14)) if done else 25, self.hide)

    def place(self) -> None:
        w, h = self.win.get_size()
        self.win.move(*self.mini.beside(w, h))

    def hide(self):
        if getattr(self.mini, "ptt_active", False):  # Ctrl is still held: "Listening…" must stay (ptt.log 01:28:05:
            pttlog("caption hide skipped: key held")  # an old timer hid it 2.7 s into a hold)
            self.timer = 0
            return False
        import traceback
        pttlog("caption hidden by " + " < ".join(f.name for f in traceback.extract_stack()[-4:-1]))
        self.timer = 0
        self.win.hide()
        self.you.set_text("")
        return False


def _custom_key(slot: str, name: str, command: str, binding: str) -> None:
    """One GNOME custom shortcut (Settings > Keyboard > Custom Shortcuts), added once; never overwrites yours."""
    base = "org.gnome.settings-daemon.plugins.media-keys"
    path = f"/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/{slot}/"
    key = f"{base}.custom-keybinding:{path}"

    def gs(*args: str) -> str:
        return subprocess.run(["gsettings", *args], capture_output=True, text=True, timeout=5).stdout.strip()
    have = gs("get", key, "binding").strip("'\"")
    if have not in ("", "''") and have not in _OLD_FOCUS_KEYS:
        return
    if have in _OLD_FOCUS_KEYS:
        gs("set", key, "binding", binding)
        note(f"shortcut {have} -> {binding}: {name}")
        return
    paths = gs("get", base, "custom-keybindings").replace("@as ", "")
    lst = json.loads(paths.replace("'", '"')) if paths.startswith("[") else []
    if path not in lst:
        gs("set", base, "custom-keybindings", json.dumps(lst + [path]).replace('"', "'"))
    gs("set", key, "name", name)
    gs("set", key, "command", command)
    gs("set", key, "binding", binding)
    note(f"shortcut {binding}: {name}")


def install_hotkey() -> None:
    """GNOME shortcut MINI_HOTKEY (Super+S) -> SIGUSR1 to this script = open / hide the mini chat. Once; idempotent.
    (Super+S was tried first: GNOME keeps it; its quick-settings binding is given back.)"""
    if not MINI_HOTKEY or "GNOME" not in os.getenv("XDG_CURRENT_DESKTOP", "").upper():
        return
    base = "org.gnome.settings-daemon.plugins.media-keys"
    path = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/kurama-mini/"
    key = f"{base}.custom-keybinding:{path}"

    def gs(*args: str) -> str:
        r = subprocess.run(["gsettings", *args], capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    try:
        if gs("get", key, "binding").strip("'\"") not in ("", "''"):  # already there (maybe changed by you
            if FOCUS_HOTKEY:  # in Settings > Keyboard > Custom Shortcuts): never overwrite it
                _custom_key("kurama-focus", "KURAMA chat box: type here / back",
                            f"sh -c 'kill -WINCH $(cat {PID_FILE})'", FOCUS_HOTKEY)
            return
        if gs("get", "org.gnome.shell.keybindings", "toggle-quick-settings") == "@as []":
            gs("set", "org.gnome.shell.keybindings", "toggle-quick-settings", "['<Super>s']")
        paths = gs("get", base, "custom-keybindings").replace("@as ", "")
        lst = json.loads(paths.replace("'", '"')) if paths.startswith("[") else []
        if path not in lst:
            gs("set", base, "custom-keybindings", json.dumps(lst + [path]).replace('"', "'"))
        gs("set", key, "name", "KURAMA mini chat")
        gs("set", key, "command", f"sh -c 'kill -USR1 $(cat {PID_FILE})'")
        gs("set", key, "binding", MINI_HOTKEY)
        note(f"shortcut {MINI_HOTKEY} opens / hides the mini chat")
        if FOCUS_HOTKEY:
            _custom_key("kurama-focus", "KURAMA chat box: type here / back", f"sh -c 'kill -WINCH $(cat {PID_FILE})'",
                        FOCUS_HOTKEY)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        note(f"couldn't set the {MINI_HOTKEY} shortcut: {e}")


def raise_fd_limit() -> None:
    """The page's web process inherits this process's open-file limit. The desktop gives 1024; on 11-02 07:54 the
    web process used them all after ~5 min of voice use ("per-process limit on the number of open file descriptors
    has been reached", GStreamer "cannot create wakeup pipe", pulse "Too many open files"): the wallpaper went black
    and the mini chat hung on "Getting ready". Raised to the hard limit (capped), before any web process starts."""
    import resource
    with contextlib.suppress(ValueError, OSError):
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        want = min(hard, FD_LIMIT) if hard != resource.RLIM_INFINITY else FD_LIMIT
        if soft < want:
            resource.setrlimit(resource.RLIMIT_NOFILE, (want, hard))


_fd_seen = {"max": 0}


def _web_pids() -> list[int]:
    """WebKit processes started by this window (their parent is us)."""
    out = []
    for d in Path("/proc").glob("[0-9]*"):
        with contextlib.suppress(OSError, ValueError, IndexError):
            stat = (d / "stat").read_text()
            if int(stat.rsplit(")", 1)[1].split()[1]) == os.getpid():
                out.append(int(d.name))
    return out


def fd_guard() -> bool:
    """Every FD_CHECK_S: the web processes' open files. Growing past FD_WARN (and every +FD_WARN after) is logged to
    hang.log with what kind of files they are (evidence for the leak); past FD_RECYCLE the window restarts itself
    cleanly (kurama-wallpaper.sh starts a fresh one) instead of going black and stuck."""
    worst, kinds = 0, {}
    for pid in _web_pids():
        with contextlib.suppress(OSError):
            fds = list(Path(f"/proc/{pid}/fd").iterdir())
            if len(fds) > worst:
                worst, kinds = len(fds), {}
                for f in fds:
                    with contextlib.suppress(OSError):
                        k = os.readlink(f).split("[")[0].split(":")[0]
                        k = k if not k.startswith("/") else "/" + k.strip("/").split("/")[0]
                        kinds[k] = kinds.get(k, 0) + 1
    if worst >= FD_WARN and worst >= _fd_seen["max"] + FD_WARN // 2:
        _fd_seen["max"] = worst
        top = ", ".join(f"{k} {n}" for k, n in sorted(kinds.items(), key=lambda x: -x[1])[:6])
        with contextlib.suppress(OSError), (STATE_FILE.parent / "logs" / "hang.log").open("a") as fh:
            fh.write(time.strftime("%m-%d %H:%M:%S") + f" web process has {worst} open files ({top})\n")
    if worst >= FD_RECYCLE:
        with contextlib.suppress(OSError), (STATE_FILE.parent / "logs" / "hang.log").open("a") as fh:
            fh.write(time.strftime("%m-%d %H:%M:%S") + f" {worst} open files: restarting the window before it breaks\n")
        os._exit(1)  # kurama-wallpaper.sh starts a fresh window (its respawn loop)
    return True


def main() -> int:
    raise_fd_limit()
    ap = argparse.ArgumentParser(description="KURAMA live wallpaper (GTK + WebKit)")
    ap.add_argument("--window", action="store_true", help="normal window instead of wallpaper (testing)")
    ap.add_argument("--url", default=DEFAULT_URL, help=f"page to show (default {DEFAULT_URL})")
    a = ap.parse_args()
    if not Gdk.Display.get_default():
        print("no display (needs an X11 session)", file=sys.stderr)
        return 1
    wp = Wallpaper(a.url, a.window)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, wp.toggle_mini)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2, wp.on_ptt)  # hold-to-talk (jarvis/core/ptt.py)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGWINCH, wp.focus_chat)  # FOCUS_HOTKEY: type here / back
    with contextlib.suppress(OSError):
        PID_FILE.write_text(str(os.getpid()))
    threading.Thread(target=install_hotkey, daemon=True).start()
    hang_guard()
    GLib.timeout_add_seconds(FD_CHECK_S, fd_guard)
    Gtk.main()
    return 0


HANG_S = 20  # the window's main loop stuck this long ("KURAMA-mini is not responding") -> stacks logged, exit, relaunch


def hang_guard() -> None:
    """Never stay frozen. A C-level timer thread (faulthandler) is re-armed every 2 s by the GTK main loop; if the loop
    stops for HANG_S, every thread's Python stack goes to data/logs/hang.log (the evidence: which call froze, which
    thread held the lock) and the process exits with code 1, so kurama-wallpaper.sh starts a fresh window at once.
    11-01 09:17: the window froze after a burst of hold-to-talk presses (main thread blocked on a lock, another thread
    at 100% CPU) and stayed frozen until restarted by hand."""
    import faulthandler
    try:
        fh = (STATE_FILE.parent / "logs" / "hang.log").open("a", encoding="utf-8")
    except OSError:
        return

    def rearm() -> bool:
        faulthandler.dump_traceback_later(HANG_S, repeat=False, file=fh, exit=True)
        return True
    fh.write(time.strftime("%m-%d %H:%M:%S") + f" window started (pid {os.getpid()}); a freeze of {HANG_S} s is "
             "logged here with every thread's stack, then the window restarts\n")
    fh.flush()
    rearm()
    GLib.timeout_add_seconds(2, rearm)


if __name__ == "__main__":
    sys.exit(main())
