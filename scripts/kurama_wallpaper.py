#!/usr/bin/python3
"""KURAMA live wallpaper: a native GTK + WebKit window that sits behind every window (X11).

Runs with the *system* Python (python3-gi, gir1.2-webkit2-4.1, optional gir1.2-wnck-3.0), not the venv:
    /usr/bin/python3 scripts/kurama_wallpaper.py                 # as wallpaper (use Super+D to reach it)
    /usr/bin/python3 scripts/kurama_wallpaper.py --window        # as a normal window (testing)
    /usr/bin/python3 scripts/kurama_wallpaper.py --url http://127.0.0.1:8000/?wallpaper=1

While a maximized / full-screen window covers the desktop (checked with libwnck every ~2 s) the page is
paused through window.kuramaPause(true): the orb loop, clock, status stream and CSS animations stop, so
the wallpaper costs ~0 CPU while you work. The page stays clickable: chat works from the desktop.
"""
from __future__ import annotations

import argparse
import contextlib
import os
import sys
from urllib.parse import urlsplit

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, GLib, Gtk, WebKit2  # noqa: E402

try:  # libwnck tells us when windows cover the desktop
    gi.require_version("Wnck", "3.0")
    from gi.repository import Wnck  # noqa: E402
except (ValueError, ImportError):
    Wnck = None

PORT = os.getenv("JARVIS_API_PORT", "8000")
DEFAULT_URL = os.getenv("KURAMA_UI_URL", f"http://127.0.0.1:{PORT}/?lowpower=0&wallpaper=1")
CHECK_MS = 2000


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


def run_js(view, code: str) -> None:
    if hasattr(view, "evaluate_javascript"):  # WebKitGTK >= 2.40
        view.evaluate_javascript(code, -1, None, None, None, None, None)
    else:
        view.run_javascript(code, None, None, None)


class Wallpaper:
    def __init__(self, url: str, as_window: bool) -> None:
        self.url = url
        self.paused: bool | None = None
        self.win = Gtk.Window(title="KURAMA")
        self.view = WebKit2.WebView()
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

    # The API may start after us at login: keep retrying until the page loads
    def on_failed(self, *_):
        GLib.timeout_add_seconds(3, lambda: self.view.load_uri(self.url) and False)
        return False

    def on_load(self, _view, event):
        if event == WebKit2.LoadEvent.FINISHED and self.paused:
            run_js(self.view, "window.kuramaPause && window.kuramaPause(true)")

    def on_permission(self, _view, req):
        # microphone (audio only) for Mic/Conversation mode, only for our own page's origin
        ok = (isinstance(req, WebKit2.UserMediaPermissionRequest)
              and req.get_property("is-for-audio-device") and not req.get_property("is-for-video-device")
              and origin_of(self.view.get_uri()) == origin_of(self.url))
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

    def check_covered(self):
        try:
            covered = desktop_covered(self.screen)
        except Exception:
            covered = False
        if covered != self.paused:
            self.paused = covered
            run_js(self.view, f"window.kuramaPause && window.kuramaPause({str(covered).lower()})")
        return True


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
