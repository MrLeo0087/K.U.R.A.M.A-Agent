"""P9a desktop extras: DND, night light, wallpaper, auto theme, battery, kill_app, focus mode, YouTube,
playlists, fast path and routing. Every system command goes to a fake (_sys._exec): nothing real changes."""
import os
import subprocess
from datetime import datetime, time as dtime

import pytest

from jarvis.core import config, fastpath, llm, registry, router, store
from jarvis.tools.general import _sys, open_url
from jarvis.tools.general import focus_mode as fm
from jarvis.tools.general import kill_app as ka
from jarvis.tools.general import playlist as pl
from jarvis.tools.general import youtube as yt
from jarvis.tools.general.battery_status import battery_status
from jarvis.tools.general.do_not_disturb import do_not_disturb
from jarvis.tools.general.night_light import night_light
from jarvis.tools.general.set_wallpaper import set_wallpaper

UPOWER = """  native-path:          BAT0
  power supply:         yes
  battery
    present:             yes
    state:               discharging
    percentage:          57%
    time to empty:       2.5 hours
    capacity:            80.8937%
    charge-cycles:       537
"""


class FakeGnome:
    """gsettings store + upower + wmctrl + xdotool stand-in."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.gs = {("org.gnome.desktop.notifications", "show-banners"): "true",
                   ("org.gnome.settings-daemon.plugins.color", "night-light-enabled"): "false",
                   ("org.gnome.settings-daemon.plugins.color", "night-light-temperature"): "uint32 2700",
                   ("org.gnome.settings-daemon.plugins.color", "night-light-schedule-automatic"): "false",
                   ("org.gnome.desktop.background", "picture-uri"): "'file:///nowhere/a.png'",
                   ("org.gnome.desktop.interface", "color-scheme"): "'prefer-light'"}
        self.battery = True
        self.windows = "0x01  0 host Some doc - Text Editor\n0x02  0 host Lofi beats - YouTube - Google Chrome\n"

    def which(self, b):
        return f"/usr/bin/{b}"

    def __call__(self, argv, timeout, input_text, capture):
        a = [os.path.basename(argv[0]), *argv[1:]]
        self.calls.append(a)
        out = ""
        if a[0] == "gsettings":
            if a[1] == "get":
                out = self.gs.get((a[2], a[3]), "''")
            else:
                self.gs[(a[2], a[3])] = a[4]
        elif a[0] == "upower":
            if a[1] == "-e":
                out = ("/org/freedesktop/UPower/devices/battery_BAT0\n" if self.battery else "") + \
                      "/org/freedesktop/UPower/devices/line_power_ADP1\n"
            else:
                out = UPOWER
        elif a[0] == "wmctrl" and a[1] == "-l":
            out = self.windows
        elif a[0] == "xdotool" and a[1] == "getactivewindow":
            out = "4242\n"
        return subprocess.CompletedProcess(argv, 0, out, "")

    def get(self, schema, key):
        return self.gs.get((schema, key))


@pytest.fixture
def gn(monkeypatch):
    g = FakeGnome()
    monkeypatch.setattr(_sys, "_exec", g)
    monkeypatch.setattr(_sys, "which", g.which)
    monkeypatch.setattr(yt.time, "sleep", lambda s: None)
    return g


def test_groups_small_and_registered():
    for g in ("desktop", "power", "apps", "media"):
        names = [t.name for t in registry.schemas_for([g])]
        assert 1 <= len(names) <= 5, (g, names)
    assert {t.name for t in registry.schemas_for(["desktop"])} == {
        "do_not_disturb", "night_light", "set_wallpaper", "focus_mode", "share_wifi"}
    assert registry.get("kill_app").metadata["safety"] == "confirm"


def test_do_not_disturb(gn):
    assert do_not_disturb("status") == "Do Not Disturb is off."
    assert "on" in do_not_disturb("on") and gn.get("org.gnome.desktop.notifications", "show-banners") == "false"
    assert do_not_disturb("toggle") == "Do Not Disturb is off."
    assert gn.get("org.gnome.desktop.notifications", "show-banners") == "true"


def test_night_light_clamps_temperature(gn):
    assert night_light("status") == "Night Light is off (2700 K)."
    assert night_light("on", temperature=9000) == "Night Light is on at 4700 K."
    assert gn.get("org.gnome.settings-daemon.plugins.color", "night-light-temperature") == "4700"
    assert gn.get("org.gnome.settings-daemon.plugins.color", "night-light-enabled") == "true"
    assert night_light("off") == "Night Light is off."


def test_set_wallpaper(gn, tmp_path, monkeypatch):
    for n in ("a.jpg", "b.png", "c.txt"):
        (tmp_path / n).write_text("x")
    monkeypatch.setattr(config, "WALLPAPER_DIRS", (tmp_path,))
    monkeypatch.setattr(config, "SCREENSHOT_DIR", tmp_path / "shots")
    bg = "org.gnome.desktop.background"
    assert set_wallpaper(mode="next") == "Wallpaper set to a.jpg."
    uri = (tmp_path / "a.jpg").resolve().as_uri()
    assert gn.get(bg, "picture-uri") == uri and gn.get(bg, "picture-uri-dark") == uri
    assert gn.get(bg, "picture-options") == "zoom"
    gn.gs[(bg, "picture-uri")] = f"'{uri}'"
    assert set_wallpaper(mode="next") == "Wallpaper set to b.png."
    assert "b.png" in set_wallpaper(mode="current")
    assert set_wallpaper(str(tmp_path / "c.txt")).startswith("error")
    assert set_wallpaper("/no/such.png").startswith("error")
    assert set_wallpaper("b") == "Wallpaper set to b.png."  # by name
    assert set_wallpaper(mode="random") == "Wallpaper set to a.jpg."  # anything but the current one (b)



def test_wallpaper_current_behind_desktop_snapshot(gn, tmp_path, monkeypatch):
    """The live wallpaper shows a dashboard snapshot on the GNOME desktop; current() still names the real one."""
    from jarvis.tools.general import set_wallpaper as sw
    real = tmp_path / "real.jpg"
    real.write_text("x")
    monkeypatch.setattr(sw, "REAL_WALLPAPER", tmp_path / "real-wallpaper.json")
    sw.REAL_WALLPAPER.write_text('{"picture-uri": "%s"}' % real.as_uri())
    gn.gs[("org.gnome.desktop.background", "picture-uri")] = f"'{sw.SNAP_URI}'"
    assert sw.current() == real
    sw.REAL_WALLPAPER.unlink()
    assert sw.current() is None


def test_battery_status(gn):
    out = battery_status()
    assert out.startswith("Battery 57%, discharging, 2.5 hours left, health 81%") and "537" in out
    gn.battery = False
    assert battery_status().startswith("No battery found")


class FakeProc:
    def __init__(self, pid, name, cmd=None, user=None):
        self.pid = pid
        self.info = {"pid": pid, "name": name, "cmdline": cmd or [f"/usr/bin/{name}"],
                     "username": user or ka.getpass.getuser(), "ppid": 1}
        self.terminated = self.killed = False

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def children(self, recursive=False):
        return []


def test_kill_app_skips_protected(monkeypatch):
    procs = [FakeProc(5000, "spotify"), FakeProc(5001, "spotify", user="root"), FakeProc(500, "spotify"),
             FakeProc(5002, "gnome-shell"), FakeProc(5003, "python3", ["python3", "-m", "jarvis"]),
             FakeProc(5004, "Xorg")]
    monkeypatch.setattr(ka, "_procs", lambda: procs)
    monkeypatch.setattr(ka, "_ancestors", lambda: {os.getpid()})
    monkeypatch.setattr(ka._apps, "find_app", lambda n: (None, 0))
    alive_after_term = []
    monkeypatch.setattr(ka.psutil, "wait_procs",
                        lambda ps, timeout: ([p for p in ps if p not in alive_after_term], alive_after_term[:]))
    out = ka.kill_app("spotify")
    assert out.startswith("Closed spotify: 1 process stopped") and procs[0].terminated
    assert not any(p.terminated or p.killed for p in procs[1:])
    assert ka.kill_app("gnome-shell").startswith("error") and ka.kill_app("jarvis").startswith("error")
    procs[0].terminated = False
    assert "force-killed" in ka.kill_app("spotify", force=True) and procs[0].killed and not procs[0].terminated
    # frozen -> the focused window's pid (xdotool)
    procs.append(FakeProc(4242, "chrome"))
    monkeypatch.setattr(ka, "_active_pid", lambda: 4242)
    assert ka.kill_app("the frozen app").startswith("Closed chrome")


def test_focus_mode(gn, monkeypatch):
    sent = []
    from jarvis.core import notify
    monkeypatch.setattr(notify, "notify", lambda title, text="", **k: sent.append(title))

    class FakeTimer:
        def __init__(self, secs, fn, args=()):
            self.secs, self.fn, self.args, self.daemon = secs, fn, args, False

        def start(self):
            pass

        def cancel(self):
            pass
    monkeypatch.setattr(fm.threading, "Timer", FakeTimer)
    assert fm.focus_mode(50) == "Focus mode on for 50 minutes: Do Not Disturb is on."
    assert gn.get("org.gnome.desktop.notifications", "show-banners") == "false"
    assert "50 minutes left" in fm.focus_mode(action="status")
    timer = fm._state["timer"]
    assert timer.secs == 3000
    timer.fn(*timer.args)  # the timer fires
    assert sent == ["Focus session done"] and not fm.active()
    assert gn.get("org.gnome.desktop.notifications", "show-banners") == "true"
    fm.focus_mode(10)
    assert fm.focus_mode(action="stop").startswith("Focus session stopped") and sent == ["Focus session done"]


def test_youtube_play_and_keys(gn, monkeypatch):
    opened = []
    monkeypatch.setattr(open_url, "_open", opened.append)
    monkeypatch.setattr(yt, "_ddg_video", lambda q: None)
    monkeypatch.setattr(yt, "_scrape", lambda q: "https://www.youtube.com/watch?v=abcdefghijk")
    assert yt.youtube("lofi beats") == "Playing lofi beats on YouTube."
    assert opened[-1] == "https://www.youtube.com/watch?v=abcdefghijk"
    monkeypatch.setattr(yt, "_scrape", lambda q: None)
    assert yt.youtube("lofi beats").startswith("Opened YouTube results")
    assert "search_query=lofi+beats" in opened[-1]
    assert yt.youtube(action="pause") == "Toggled play/pause on YouTube."
    assert ["wmctrl", "-i", "-a", "0x02"] in gn.calls and gn.calls[-1][-1] == "k"
    yt.youtube(action="next")
    assert gn.calls[-1][-1] == "shift+n"
    gn.windows = ""
    assert yt.youtube(action="fullscreen").startswith("error: no YouTube window")


def test_playlist(monkeypatch, tmp_path):
    opened, spawned = [], []
    monkeypatch.setattr(open_url, "_open", opened.append)
    monkeypatch.setattr(pl, "_spawn", spawned.append)
    monkeypatch.setattr(config, "PLAYLISTS", {"lofi": "https://youtu.be/x", "Workout": str(tmp_path)})
    from jarvis.core import music
    started = []
    monkeypatch.setattr(music, "launch", lambda cmds, pipe=False, env=None: started.append(cmds) or [])
    monkeypatch.setattr(music, "expand", lambda url: [{"url": url, "id": "xxxxxx", "title": "", "duration": 0}])
    assert pl.playlist("lofi playlist").startswith("Playing your lofi playlist") and not opened  # sound only, no tab
    assert started and started[-1][0][-1] == "https://youtu.be/x"
    assert pl.playlist("my workout") == "Playing your Workout playlist." and spawned
    assert spawned[0][-1] == str(tmp_path)
    assert pl.playlist("jazz").startswith("error") and "lofi" in pl.playlist("")


FAST = {
    "turn on do not disturb": ("do_not_disturb", {"action": "on"}),
    "do not disturb off": ("do_not_disturb", {"action": "off"}),
    "night light on": ("night_light", {"action": "on"}),
    "turn off the night light": ("night_light", {"action": "off"}),
    "next wallpaper": ("set_wallpaper", {"mode": "next"}),
    "how much battery is left": ("battery_status", {}),
    "battery status": ("battery_status", {}),
    "start focus mode for 45 minutes": ("focus_mode", {"action": "start", "minutes": 45}),
    "stop focus mode": ("focus_mode", {"action": "stop"}),
    "play despacito on youtube": ("youtube", {"query": "despacito", "action": "play"}),
    "youtube ma lofi bajao": ("youtube", {"query": "lofi", "action": "play"}),
}


def test_fastpath_patterns():
    for text, (tool, args) in FAST.items():
        it = fastpath.match(text)
        assert it and it.tool == tool and it.args == args, text
    for text in ("night mode", "play", "open youtube", "what is a battery made of"):
        it = fastpath.match(text)
        assert it is None or it.tool not in ("night_light", "youtube", "battery_status"), text


def test_fastpath_answers_without_llm(gn, monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    monkeypatch.setattr(llm, "chat", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM called")))
    assert fastpath.try_answer("turn on do not disturb", lang="en").answer.startswith("Do Not Disturb is on")
    assert fastpath.try_answer("battery status", lang="en").answer.startswith("Battery 57%")
    assert store.tokens_today() == 0


ROUTES = {
    "silence my notifications": "desktop", "set a nice wallpaper": "desktop", "pomodoro please": "desktop",
    "make the screen warmer with night light": "desktop", "is the laptop charging": "power",
    "ब्याट्री कति छ": "power", "chrome is frozen, force quit it": "apps",
    "put some lofi on youtube": "media", "play my workout playlist": "media",
}


def test_routing():
    for text, group in ROUTES.items():
        assert group in router.route(text, log_it=False).groups, text
    assert router.route("open youtube", log_it=False).groups == ["browser"]
