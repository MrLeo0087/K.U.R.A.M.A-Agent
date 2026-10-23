"""P5b desktop tools: volume, mute, mic, media, brightness, windows, workspace, lock/suspend/power,
screenshot, clipboard, read aloud, greeting, fast path and routing.
Every system command goes to a fake (_sys._exec): nothing real is ever changed."""
import os
import re
import threading
from datetime import datetime

import pytest

from jarvis.core import config, fastpath, greeting, llm, registry, router, safety, store
from jarvis.tools.general import _apps, _sys, open_url
from jarvis.tools.general.brightness import brightness
from jarvis.tools.general.clipboard_history import clipboard_history
from jarvis.tools.general.launch_workspace import launch_workspace
from jarvis.tools.general.list_windows import list_windows
from jarvis.tools.general.lock_screen import lock_screen
from jarvis.tools.general.media_control import media_control
from jarvis.tools.general.mic_mute import mic_mute
from jarvis.tools.general.mute_audio import mute_audio
from jarvis.tools.general.read_aloud import read_aloud
from jarvis.tools.general.read_clipboard import read_clipboard
from jarvis.tools.general.screenshot import screenshot
from jarvis.tools.general.snap_window import snap_window
from jarvis.tools.general.volume import volume
from jarvis.tools.general.write_clipboard import write_clipboard


class FakeDesktop:
    """Stateful stand-in for pactl/playerctl/brightnessctl/xdotool/wmctrl/xclip/screenshot/lock."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.vol, self.muted, self.mic_muted = 50, False, False
        self.player: str | None = "Playing"
        self.bright, self.bright_denied = 50, False
        self.clip = ""
        self.fail: set[str] = set()
        self.missing: set[str] = set()

    def which(self, b):
        return None if b in self.missing else f"/usr/bin/{b}"

    def __call__(self, argv, timeout, input_text, capture):
        import subprocess
        a = [os.path.basename(argv[0]), *argv[1:]]
        self.calls.append(a)
        rc, out, err = 0, "", ""
        name = a[0]
        if name in self.fail:
            return subprocess.CompletedProcess(argv, 1, "", f"{name} failed")
        if name == "pactl":
            kind = "sink" if "sink" in a[1] else "source"
            attr = "muted" if kind == "sink" else "mic_muted"
            if a[1] == "get-sink-volume":
                out = f"Volume: front-left: 1 / {self.vol}% / -1 dB,   front-right: 1 / {self.vol}% / -1 dB"
            elif a[1] == "set-sink-volume":
                self.vol = int(a[3].rstrip("%"))
            elif a[1].startswith("get-") and a[1].endswith("-mute"):
                out = f"Mute: {'yes' if getattr(self, attr) else 'no'}"
            elif a[1].startswith("set-") and a[1].endswith("-mute"):
                v = a[3]
                setattr(self, attr, (not getattr(self, attr)) if v == "toggle" else v == "1")
        elif name == "playerctl":
            cmd = a[-1] if a[1] != "metadata" else "metadata"
            if self.player is None:
                rc, err = 1, "No players found"
            elif cmd == "status":
                out = self.player + "\n"
            elif cmd == "metadata":
                out = "Artist - Song\n"
            elif cmd == "play-pause":
                self.player = "Paused" if self.player == "Playing" else "Playing"
            elif cmd in ("play", "pause"):
                self.player = "Playing" if cmd == "play" else "Paused"
        elif name == "brightnessctl":
            if a[-1] == "-m":
                out = f"intel_backlight,backlight,{self.bright * 960},{self.bright}%,96000\n"
            elif self.bright_denied:
                rc, err = 1, "Can't modify brightness: Permission denied"
            else:
                self.bright = int(a[-1].rstrip("%"))
        elif name == "xdotool":
            out = {"getactivewindow": "62914566\n", "getdisplaygeometry": "1920 1200\n"}.get(a[1], "")
        elif name == "wmctrl" and a[1] == "-d":
            out = "0  * DG: 1920x1200  VP: 0,0  WA: 0,32 1920x1168  Workspace 1\n"
        elif name == "xclip":
            if "-o" in a:
                rc, out = (0, self.clip) if self.clip else (1, "")
            else:
                self.clip = input_text
        elif name in ("gnome-screenshot", "scrot"):
            path = a[a.index("-f") + 1] if "-f" in a else a[-1]
            with open(path, "wb") as f:
                f.write(b"\x89PNG")
        return subprocess.CompletedProcess(argv, rc, out if capture else None, err if capture else None)

    def ran(self, *prefix):
        return [c for c in self.calls if c[: len(prefix)] == list(prefix)]


@pytest.fixture
def desk(monkeypatch, tmp_path):
    d = FakeDesktop()
    monkeypatch.setattr(_sys, "_exec", d)
    monkeypatch.setattr(_sys, "which", d.which)
    monkeypatch.setattr(config, "SCREENSHOT_DIR", tmp_path / "shots")
    return d


# --- registration / groups ---
NEW = {"volume": ("audio", "safe"), "mute_audio": ("audio", "safe"), "mic_mute": ("audio", "safe"),
       "media_control": ("media", "safe"), "brightness": ("display", "safe"),
       "snap_window": ("windows", "safe"), "list_windows": ("windows", "safe"),
       "launch_workspace": ("apps", "safe"), "lock_screen": ("power", "safe"),
       "suspend_computer": ("power", "confirm"), "power_off": ("power", "blocked"),
       "screenshot": ("screen", "safe"), "read_clipboard": ("clipboard", "safe"),
       "write_clipboard": ("clipboard", "safe"), "clipboard_history": ("clipboard", "safe"),
       "read_aloud": ("speech", "safe")}


def test_tools_registered_and_groups_small():
    for name, (group, level) in NEW.items():
        t = registry.get(name)
        assert t is not None and registry.group_of(t) == group and registry.safety_of(t) == level, name
    for g in {g for g, _ in NEW.values()}:
        assert 1 <= len(registry.schemas_for([g])) <= 5, g
        assert g in config.ROUTER_RULES and g in config.TOOL_GROUP_DESCRIPTIONS, g


def test_missing_cli_gives_clear_message(desk):
    desk.missing.add("playerctl")
    assert media_control("pause") == "error: playerctl not found: sudo apt install playerctl"
    with pytest.raises(_sys.SysError, match="not an allowed"):
        _sys.run(["rm", "-rf", "/"])


# --- audio ---
def test_volume_get_set_step_and_clamp(desk):
    assert volume() == "volume 50%"
    assert volume("set", 30) == "volume 30%" and desk.vol == 30
    assert volume("up") == "volume 40%"
    assert volume("down", step=5) == "volume 35%"
    assert volume("set", 150) == "volume 100%"
    assert volume("set").startswith("error")
    desk.muted = True
    assert volume() == "volume 100% (muted)"
    assert volume("up", step=0) == "volume 100%" and desk.muted is False  # louder unmutes
    assert desk.ran("pactl", "set-sink-volume", "@DEFAULT_SINK@", "100%")


def test_mute_audio(desk):
    assert mute_audio() == "sound muted" and desk.muted
    assert mute_audio("status") == "sound is muted"
    assert mute_audio("unmute") == "sound unmuted" and not desk.muted
    assert desk.ran("pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle")


def test_mic_mute(desk):
    assert mic_mute("mute") == "microphone muted" and desk.mic_muted and not desk.muted
    assert mic_mute() == "microphone unmuted"
    assert desk.ran("pactl", "set-source-mute", "@DEFAULT_SOURCE@", "1")


# --- media ---
def test_media_control(desk):
    assert media_control("status") == "playing: Artist - Song"
    assert media_control() == "paused" and desk.player == "Paused"
    assert media_control("next") == "next track" and desk.ran("playerctl", "next")
    assert media_control("previous", player="spotify") == "previous track"
    assert desk.ran("playerctl", "-p", "spotify", "previous")
    desk.player = None
    assert media_control("play") == "error: no media player is running"


# --- brightness ---
def test_brightness(desk):
    assert brightness() == "brightness 50%"
    assert brightness("set", 70) == "brightness 70%" and desk.bright == 70
    assert brightness("down", step=80) == f"brightness {config.BRIGHTNESS_MIN}%"  # never black
    assert brightness("up") == f"brightness {config.BRIGHTNESS_MIN + 10}%"
    desk.bright = 1
    assert brightness("down") == "brightness 1%"  # already below the floor: never brighter on "down"
    assert brightness("set", 0) == "brightness 1%"
    desk.bright_denied = True
    out = brightness("set", 40)
    assert out.startswith("error: no permission") and "usermod -aG video" in out
    assert not desk.ran("sudo")


# --- windows ---
WINS = [{"id": "0x03c00006", "wmclass": "code.Code", "title": "main.py - Visual Studio Code"},
        {"id": "0x04a00003", "wmclass": "Navigator.firefox", "title": "GitHub - Mozilla Firefox"}]


def test_snap_window_active_and_named(desk, monkeypatch):
    monkeypatch.setattr(_apps, "list_windows", lambda: WINS)
    assert snap_window("left") == "snapped the active window to the left half"
    active = hex(62914566)
    assert desk.ran("wmctrl", "-i", "-r", active, "-e", "0,0,32,960,1168")  # below the top bar
    out = snap_window("right", "firefox")
    assert out.endswith("to the right half") and desk.ran("wmctrl", "-i", "-r", "0x4a00003", "-e", "0,960,32,960,1168")
    assert snap_window("maximize", "vs code").startswith("maximized")
    assert desk.ran("wmctrl", "-i", "-r", "0x3c00006", "-b", "add,maximized_vert,maximized_horz")
    assert snap_window("minimize") == "minimized the active window"
    assert desk.ran("xdotool", "windowminimize", "62914566")
    assert snap_window("restore", "firefox").startswith("restored")
    assert desk.ran("wmctrl", "-i", "-a", "0x4a00003")
    assert snap_window("left", "notepad++").startswith("error: no open window")


def test_work_area_falls_back_to_panel_offset(desk, monkeypatch):
    from jarvis.tools.general import snap_window as mod
    orig = desk.__call__

    def full_wa(argv, *a):
        cp = orig(argv, *a)
        if argv[1:] == ["-d"]:
            cp.stdout = "0  * DG: 1920x1200  VP: 0,0  WA: 0,0 1920x1200  Workspace 1\n"
        return cp
    monkeypatch.setattr(_sys, "_exec", full_wa)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "ubuntu:GNOME")
    assert mod.work_area() == (0, config.SNAP_PANEL_OFFSET, 1920, 1200 - config.SNAP_PANEL_OFFSET)


def test_list_windows(monkeypatch):
    monkeypatch.setattr(_apps, "list_windows", lambda: WINS)
    out = list_windows()
    assert out.startswith("2 open windows:") and "[firefox]" in out and "[Code]" in out


# --- workspace ---
def test_launch_workspace(monkeypatch):
    apps = {"vs code": {"id": "code", "name": "Visual Studio Code"},
            "terminal": {"id": "org.gnome.Terminal", "name": "Terminal"}}
    launched, opened = [], []
    monkeypatch.setattr(_apps, "find_app", lambda n: (apps.get(n), 100) if n in apps else (None, 0))
    monkeypatch.setattr(_apps, "launch", lambda e: launched.append(e["id"]))
    monkeypatch.setattr(open_url, "_open", opened.append)
    out = launch_workspace("coding workspace")
    assert out == "started the coding workspace: Visual Studio Code, Terminal, https://github.com"
    assert launched == ["code", "org.gnome.Terminal"] and opened == ["https://github.com"]
    assert "could not open: text editor" in launch_workspace("studdy")
    assert launch_workspace("list").startswith("workspaces: coding")
    assert launch_workspace("gaming").startswith("error: no workspace")


# --- power ---
def test_lock_screen_with_fallback(desk):
    assert lock_screen() == "screen locked" and desk.ran("loginctl", "lock-session")
    desk.fail.add("loginctl")
    assert lock_screen() == "screen locked" and desk.ran("gnome-screensaver-command", "-l")


def test_suspend_needs_confirm_and_power_off_blocked(desk):
    res = safety.execute("suspend_computer", {}, confirm=lambda p: False)
    assert not res.ok and not desk.ran("systemctl")
    res = safety.execute("suspend_computer", {}, confirm=lambda p: True)
    assert res.ok and res.output == "suspending now" and desk.ran("systemctl", "suspend")
    res = safety.execute("power_off", {"action": "shutdown"}, confirm=lambda p: True)
    assert not res.ok and "blocked" in res.output
    assert not desk.ran("shutdown") and len(desk.ran("systemctl")) == 1


# --- screenshot ---
def test_screenshot_modes_and_scrot_fallback(desk):
    out = screenshot()
    m = re.fullmatch(r"saved screenshot to (.+/jarvis-\d{8}-\d{6}(?:-\d+)?\.png)", out)
    assert m and os.path.exists(m.group(1)) and str(config.SCREENSHOT_DIR) in out
    assert desk.calls[-1][:2] == ["gnome-screenshot", "-f"]
    screenshot("window")
    assert desk.calls[-1][-1] == "-w"
    desk.missing.add("gnome-screenshot")
    out = screenshot("area")
    assert out.startswith("saved screenshot") and desk.calls[-1][:2] == ["scrot", "-s"]
    desk.missing.add("scrot")
    assert screenshot().startswith("error: no screenshot tool")


# --- clipboard ---
def test_clipboard_read_write_history(desk):
    assert read_clipboard() == "the clipboard is empty (or holds no text)"
    desk.clip = "x" * 2000
    out = read_clipboard()
    assert out.startswith("clipboard (2000 chars (first 500 shown)): ") and len(out) < 560
    assert write_clipboard("hello world") == "copied 11 characters to the clipboard" and desk.clip == "hello world"
    write_clipboard("second")
    assert clipboard_history() == "clipboard history: 1) second; 2) hello world"
    assert clipboard_history(restore=2).startswith("copied item 2") and desk.clip == "hello world"
    assert clipboard_history(restore=9).startswith("error")
    assert len(store.clip_recent(10)) == 3  # restoring re-adds it on top


def test_clipboard_history_only_jarvis_text(desk):
    desk.clip = "user copied this"
    read_clipboard()
    assert clipboard_history().startswith("no clipboard history")


# --- read aloud ---
def test_read_aloud_text_and_clipboard(desk, monkeypatch):
    from jarvis.core import tts
    spoken = []
    monkeypatch.setattr(tts, "speak", lambda text, lang="en", block=True: spoken.append((text, lang, block)))
    assert read_aloud("Hello there") == "reading 11 characters aloud from the text"
    desk.clip = "नमस्ते दुनिया"
    assert read_aloud("clipboard").endswith("from the clipboard")
    assert spoken[0] == ("Hello there", "en", False) and spoken[1][0] == "नमस्ते दुनिया" and spoken[1][2] is False
    desk.clip = ""
    assert read_aloud("the clipboard").startswith("error: nothing to read")


# --- greeting ---
def test_greeting_template(monkeypatch):
    wx = lambda place: "Kathmandu, Nepal: 21°C, feels like 20°C, partly cloudy. Humidity 60%, wind 5 km/h."
    text = greeting.build(datetime(2026, 10, 23, 7, 5), weather_fn=wx, jobs_n=1, notes_n=3)
    assert text == ("Good morning, it's 7:05 AM. It's 21°C and partly cloudy in Kathmandu. "
                    "You have 1 job running and 3 saved notes. Ready when you are.")

    def offline(place):
        raise OSError("no network")
    text = greeting.build(datetime(2026, 10, 23, 23, 30), weather_fn=offline, jobs_n=0, notes_n=0)
    assert text == "Hello, working late, it's 11:30 PM. Ready when you are."


def test_greeting_runs_in_thread_and_can_be_disabled(monkeypatch):
    said, done = [], threading.Event()
    t = greeting.start(lambda s: (said.append(s), done.set()), now=datetime(2026, 1, 1, 15, 0),
                       weather_fn=lambda p: "", jobs_n=0, notes_n=0)
    assert t is not None and done.wait(2) and said[0].startswith("Good afternoon")
    monkeypatch.setattr(config, "GREETING", False)
    assert greeting.start(said.append) is None


# --- fast path ---
POSITIVE = {
    "volume up": ("volume", {"action": "up"}),
    "turn the volume down by 5": ("volume", {"action": "down", "step": 5}),
    "set volume to 40": ("volume", {"action": "set", "level": 40}),
    "Jarvis, set the volume to 70 percent please": ("volume", {"action": "set", "level": 70}),
    "awaz badhao": ("volume", {"action": "up"}),
    "आवाज कम करो": ("volume", {"action": "down"}),
    "mute": ("mute_audio", {"action": "mute"}),
    "unmute the sound": ("mute_audio", {"action": "unmute"}),
    "mute mic": ("mic_mute", {"action": "mute"}),
    "unmute my microphone": ("mic_mute", {"action": "unmute"}),
    "pause": ("media_control", {"action": "pause"}),
    "pause the music": ("media_control", {"action": "pause"}),
    "play": ("media_control", {"action": "play"}),
    "next song": ("media_control", {"action": "next"}),
    "previous track": ("media_control", {"action": "previous"}),
    "गाना रोको": ("media_control", {"action": "pause"}),
    "अगला गाना": ("media_control", {"action": "next"}),
    "brightness up": ("brightness", {"action": "up"}),
    "brightness down": ("brightness", {"action": "down"}),
    "set brightness to 60%": ("brightness", {"action": "set", "level": 60}),
    "take a screenshot": ("screenshot", {"mode": "full"}),
    "take a screenshot of this window": ("screenshot", {"mode": "window"}),
    "स्क्रीनशॉट लो": ("screenshot", {"mode": "full"}),
    "lock the screen": ("lock_screen", {}),
    "screen lock karo": ("lock_screen", {}),
}
NEGATIVE = ["volume to 150", "set volume to loud", "play despacito", "play music", "lock the door",
            "mute the zoom call", "what is a screenshot", "next", "skip", "volume up and open youtube",
            "make the volume better", "brightness is too high for my eyes", "pause for a second and think",
            "screenshot the error and send it to my boss", "should I lock the screen"]


def test_fastpath_system_patterns():
    for text, (tool, args) in POSITIVE.items():
        it = fastpath.match(text)
        assert it is not None and (it.tool, it.args) == (tool, args), text
    for text in NEGATIVE:
        assert fastpath.match(text) is None, text


def test_fastpath_system_answers_without_llm(desk, monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)

    def boom(*a, **k):
        raise AssertionError("the fast path must not call the LLM")
    monkeypatch.setattr(llm, "chat", boom)
    assert fastpath.try_answer("volume up", lang="en").answer == "Done, the volume is at 60%."
    assert fastpath.try_answer("set volume to 25", lang="hi").answer == "आवाज़ 25% पर है।"
    assert fastpath.try_answer("mute", lang="en").answer == "Okay, sound is muted."
    assert fastpath.try_answer("mute mic", lang="ne").answer == "माइक बन्द गरें।"
    assert fastpath.try_answer("pause", lang="en").answer == "Okay, paused."
    assert fastpath.try_answer("what's playing", lang="en").answer == "Paused: Artist - Song."
    assert fastpath.try_answer("brightness to 80", lang="en").answer == "Done, brightness is at 80%."
    assert fastpath.try_answer("take a screenshot", lang="en").answer.startswith("Done! Your screenshot")
    assert fastpath.try_answer("lock the screen", lang="en").answer == "Sure, locking the screen."
    desk.bright_denied = True
    ans = fastpath.try_answer("brightness up", lang="en").answer
    assert ans.startswith("Sorry, that didn't work: no permission") and "video" in ans
    assert store.tokens_today() == 0


# --- routing ---
ROUTES = {
    "make it a bit louder than that": "audio", "is my microphone on": "audio",
    "dim the screen a little more": "display", "grab a screen shot of the error": "screen",
    "put the computer to sleep": "power", "what is on my clipboard": "clipboard",
    "read aloud what I just copied": "speech", "put vs code on the left half": "windows",
    "start my coding workspace": "apps", "skip this song": "media",
}


def test_routing_each_group():
    for text, group in ROUTES.items():
        assert group in router.route(text, log_it=False).groups, text
    assert router.route("open youtube", log_it=False).groups == ["browser"]  # media no longer joins
