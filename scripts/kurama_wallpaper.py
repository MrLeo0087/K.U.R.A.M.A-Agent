#!/usr/bin/python3
"""KURAMA live wallpaper: a native GTK + WebKit window that sits behind every window (X11).

Runs with the *system* Python (python3-gi, gir1.2-webkit2-4.1, optional gir1.2-wnck-3.0), not the venv:
    /usr/bin/python3 scripts/kurama_wallpaper.py                 # as wallpaper (use Super+D to reach it)
    /usr/bin/python3 scripts/kurama_wallpaper.py --window        # as a normal window (testing)
    /usr/bin/python3 scripts/kurama_wallpaper.py --url http://127.0.0.1:8000/?wallpaper=1

While a maximized / full-screen window covers the desktop (checked with libwnck every ~2 s) the page is
paused through window.kuramaPause(true): the orb loop, clock, status stream and CSS animations stop, so
the wallpaper costs ~0 CPU while you work. The page stays clickable: chat works from the desktop.

Minimize (the button in the chat header) hides the dashboard panels and shows mini KURAMA: a small round
button that floats above every app (drag it anywhere, right-click for a menu). Clicking it opens a small
chat-only panel (same page with ?mini=1: text, mic and conversation mode) over whatever you are using.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
gi.require_foreign("cairo")
from gi.repository import Gdk, GLib, Gtk, WebKit2  # noqa: E402

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
PANEL_W, PANEL_H = 400, 600  # mini chat panel
PANEL_KEEP_S = 180  # a hidden panel is closed after this long (frees its page); reopening restores the chat
WEB_MEM_MB = int(os.getenv("KURAMA_WP_MEM_MB", "320"))  # web process memory budget (WebKit's default: 3 GB)


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


def run_js(view, code: str) -> None:
    if hasattr(view, "evaluate_javascript"):  # WebKitGTK >= 2.40
        view.evaluate_javascript(code, -1, None, None, None, None, None)
    else:
        view.run_javascript(code, None, None, None)


class Wallpaper:
    def __init__(self, url: str, as_window: bool) -> None:
        self.url = url
        self.paused: bool | None = None
        self.state = load_state()
        self.mini: Mini | None = None
        self.win = Gtk.Window(title="KURAMA")
        # the page asks for minimize / restore / hide through window.webkit.messageHandlers.kurama
        self.ucm = WebKit2.UserContentManager()
        self.ucm.register_script_message_handler("kurama")
        self.ucm.connect("script-message-received::kurama", self.on_message)
        self.view = WebKit2.WebView(web_context=lean_context(), user_content_manager=self.ucm)
        self.view.set_background_color(Gdk.RGBA(0.024, 0.027, 0.043, 1))
        s = self.view.get_settings()
        try:  # GPU compositing keeps the orb and bars smooth with little CPU (KURAMA_WP_GPU=0 to disable)
            policy = "NEVER" if os.getenv("KURAMA_WP_GPU", "1") == "0" else "ALWAYS"
            s.set_hardware_acceleration_policy(getattr(WebKit2.HardwareAccelerationPolicy, policy))
        except Exception:
            pass
        # one local page: no caches, no WebGL; keep WebAudio + mic for voice chat
        self.view.get_context().set_cache_model(WebKit2.CacheModel.DOCUMENT_VIEWER)
        s.set_enable_webgl(False)
        s.set_enable_page_cache(False)
        configure_media(s)
        s.set_javascript_can_open_windows_automatically(False)
        self.view.connect("permission-request", self.on_permission)
        self.view.connect("load-failed", self.on_failed)
        self.view.connect("load-changed", self.on_load)
        self.view.connect("decide-policy", self.on_policy)
        self.view.load_uri(url)
        self.win.add(self.view)

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
        if self.state.get("minimized"):
            self.minimize()

    # The API may start after us at login: keep retrying until the page loads
    def on_failed(self, *_):
        GLib.timeout_add_seconds(3, lambda: self.view.load_uri(self.url) and False)
        return False

    def on_load(self, _view, event):
        if event == WebKit2.LoadEvent.FINISHED:
            if self.paused:
                run_js(self.view, "window.kuramaPause && window.kuramaPause(true)")
            if self.mini:
                run_js(self.view, "window.kuramaMinimized && window.kuramaMinimized(true)")

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

    def minimize(self):
        if self.mini is None:
            self.mini = Mini(self)
        self.state["minimized"] = True
        save_state(self.state)
        run_js(self.view, "window.kuramaMinimized && window.kuramaMinimized(true)")

    def restore(self):
        if self.mini is not None:
            self.mini.close()
            self.mini = None
        self.state["minimized"] = False
        save_state(self.state)
        run_js(self.view, "window.kuramaMinimized && window.kuramaMinimized(false)")

    def check_covered(self):
        try:
            covered = desktop_covered(self.screen)
        except Exception:
            covered = False
        if covered != self.paused:
            self.paused = covered
            run_js(self.view, f"window.kuramaPause && window.kuramaPause({str(covered).lower()})")
        return True


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

    @property
    def open(self) -> bool:
        return self.panel is not None and self.panel.get_visible()

    # ---------- the button ----------
    def on_draw(self, _w, cr):
        c = BUBBLE / 2
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        cr.arc(c, c, c - 1, 0, 2 * math.pi)
        cr.set_source_rgba(0.035, 0.037, 0.06, 0.94)
        cr.fill()
        glow = cairo.RadialGradient(c, c, c * 0.3, c, c, c)
        glow.add_color_stop_rgba(0, 1, 0.43, 0.08, 0.38 if self.hover or self.open else 0.22)
        glow.add_color_stop_rgba(1, 1, 0.43, 0.08, 0)
        cr.arc(c, c, c - 1, 0, 2 * math.pi)
        cr.set_source(glow)
        cr.fill()
        core = cairo.RadialGradient(c * 0.86, c * 0.8, 1, c, c, c * 0.42)  # the KURAMA orb
        core.add_color_stop_rgb(0, 1, 0.82, 0.6)
        core.add_color_stop_rgb(0.5, 1, 0.48, 0.1)
        core.add_color_stop_rgb(1, 0.64, 0.23, 0)
        cr.arc(c, c, c * 0.36, 0, 2 * math.pi)
        cr.set_source(core)
        cr.fill()
        cr.set_line_width(1.6)
        cr.set_dash([c * 0.62, c * 0.22])
        cr.set_source_rgba(1, 0.48, 0.1, 1 if self.hover or self.open else 0.7)
        cr.arc(c, c, c - 4, -math.pi / 2, 1.5 * math.pi)
        cr.stroke()
        return True

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
    def ensure_panel(self) -> None:
        if self.panel is not None:
            return
        p = self.panel = Gtk.Window(title="KURAMA")
        p.set_decorated(False)
        p.set_skip_taskbar_hint(True)
        p.set_skip_pager_hint(True)
        p.set_keep_above(True)
        p.stick()
        p.set_default_size(PANEL_W, min(PANEL_H, workarea().height - 40))
        p.connect("delete-event", lambda *_: self.hide_panel() or True)
        v = self.view = WebKit2.WebView(related_view=self.wp.view, user_content_manager=self.wp.ucm)
        v.set_settings(self.wp.view.get_settings())
        v.set_background_color(Gdk.RGBA(0.024, 0.027, 0.043, 1))
        v.connect("permission-request", self.wp.on_permission)
        v.connect("decide-policy", self.wp.on_policy)
        u = urlsplit(self.wp.url)
        v.load_uri(f"{u.scheme}://{u.netloc}/?mini=1")
        p.add(v)

    def place_panel(self) -> None:
        bx, by = self.bubble.get_position()
        wa = workarea()
        w, h = self.panel.get_size()
        left = bx + BUBBLE / 2 > wa.x + wa.width / 2  # open towards the middle of the screen
        x = bx - w - 10 if left else bx + BUBBLE + 10
        self.panel.move(clamp(x, wa.x + 8, wa.x + wa.width - w - 8), clamp(by + BUBBLE - h, wa.y + 8, wa.y + wa.height - h - 8))

    def show_panel(self, time: int = 0) -> None:
        if self.reaper:
            GLib.source_remove(self.reaper)
            self.reaper = 0
        self.ensure_panel()
        self.panel.show_all()
        self.place_panel()
        self.panel.present_with_time(time or Gtk.get_current_event_time())
        run_js(self.view, "window.kuramaMiniShown && window.kuramaMiniShown(true)")
        self.bubble.queue_draw()

    def hide_panel(self) -> None:
        if self.open:
            run_js(self.view, "window.kuramaMiniShown && window.kuramaMiniShown(false)")  # stops the mic, saves the chat
            self.panel.hide()
            if not self.reaper:
                self.reaper = GLib.timeout_add_seconds(PANEL_KEEP_S, self.drop_panel)
        self.bubble.queue_draw()

    def drop_panel(self):
        """Hidden for a while: close the panel's page (~45 MB); the next click reopens it with the chat restored."""
        self.reaper = 0
        if self.panel is not None and not self.panel.get_visible():
            self.panel.destroy()
            self.panel = self.view = None
        return False

    def close(self) -> None:
        if self.reaper:
            GLib.source_remove(self.reaper)
        if self.panel is not None:
            self.panel.destroy()
        self.bubble.destroy()
        self.panel = self.view = None


def main() -> int:
    ap = argparse.ArgumentParser(description="KURAMA live wallpaper (GTK + WebKit)")
    ap.add_argument("--window", action="store_true", help="normal window instead of wallpaper (testing)")
    ap.add_argument("--url", default=DEFAULT_URL, help=f"page to show (default {DEFAULT_URL})")
    a = ap.parse_args()
    if not Gdk.Display.get_default():
        print("no display (needs an X11 session)", file=sys.stderr)
        return 1
    Wallpaper(a.url, a.window)
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
