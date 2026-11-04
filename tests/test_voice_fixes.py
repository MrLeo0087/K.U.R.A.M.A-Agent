"""Device-sound echo canceller (mocked pactl), timers that reach the phone, one timer not two, and RAM names."""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from jarvis.core import agent, config, devaudio, fastpath, planner, reminders, store
from jarvis.tools.general.set_timer import set_timer

HW_SINK, HW_SRC, BT = "alsa_output.speaker", "alsa_input.mic", "bluez_output.headset"


class FakePactl:
    """Just enough of pactl: modules, sinks, sources, defaults."""

    def __init__(self):
        self.sinks, self.sources = [HW_SINK], [HW_SRC]
        self.default = {"sink": HW_SINK, "source": HW_SRC}
        self.mods: dict[str, str] = {}
        self.calls: list[tuple] = []

    def __call__(self, *a, timeout=5):
        self.calls.append(a)
        if a[:2] == ("list", "short"):
            if a[2] == "modules":
                return "".join(f"{i}\tmodule-echo-cancel\t{args}\n" for i, args in self.mods.items())
            names = self.sinks if a[2] == "sinks" else self.sources
            return "".join(f"{i}\t{n}\tPipeWire\n" for i, n in enumerate(names))
        if a[0] == "get-default-sink":
            return self.default["sink"] + "\n"
        if a[0] == "get-default-source":
            return self.default["source"] + "\n"
        if a[0] == "set-default-sink":
            self.default["sink"] = a[1]
        elif a[0] == "set-default-source":
            self.default["source"] = a[1]
        elif a[0] == "load-module":
            mid = str(100 + len(self.calls))
            self.mods[mid] = " ".join(a[2:])
            self.sinks.append(devaudio.EC_SINK)
            self.sources.append(devaudio.EC_SOURCE)
        elif a[0] == "unload-module":
            self.mods.pop(a[1], None)
            self.sinks = [s for s in self.sinks if s != devaudio.EC_SINK]
            self.sources = [s for s in self.sources if s != devaudio.EC_SOURCE]
            for k, real in (("sink", HW_SINK), ("source", HW_SRC)):  # the audio server falls back by itself
                if self.default[k].startswith("kurama_ec"):
                    self.default[k] = real
        return ""


@pytest.fixture
def pactl(monkeypatch, tmp_path):
    fake = FakePactl()
    monkeypatch.setattr(devaudio, "_pactl", fake)
    monkeypatch.setattr(devaudio, "available", lambda: True)
    monkeypatch.setattr(devaudio, "watch", lambda: None)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    return fake


def test_device_sound_off_routes_everything_through_the_canceller(pactl):
    devaudio._users.add("test")  # a page records: the canceller runs only meanwhile
    st = devaudio.set_hear(False)
    assert st["cancelling"] and not st["hear"]
    assert pactl.default == {"sink": devaudio.EC_SINK, "source": devaudio.EC_SOURCE}
    args = next(iter(pactl.mods.values()))
    assert f"sink_master={HW_SINK}" in args and f"source_master={HW_SRC}" in args
    assert devaudio.raw_source() == HW_SRC  # the sleeping wake listener reads the cheap raw mic
    devaudio.apply()  # again: nothing reloaded
    assert len([c for c in pactl.calls if c[0] == "load-module"]) == 1


def test_device_sound_on_gives_the_real_devices_back(pactl):
    devaudio.set_hear(False)
    st = devaudio.set_hear(True)
    assert not st["cancelling"] and st["hear"] and pactl.mods == {}
    assert pactl.default == {"sink": HW_SINK, "source": HW_SRC}
    assert devaudio.raw_source() is None


def test_canceller_follows_new_headphones(pactl):
    devaudio._users.add("test")  # a page records: the canceller runs only meanwhile
    devaudio.set_hear(False)
    pactl.sinks.append(BT)  # Bluetooth headphones connect
    devaudio._follow(BT)
    assert f"sink_master={BT}" in next(iter(pactl.mods.values())) and pactl.default["sink"] == devaudio.EC_SINK
    n = len(pactl.calls)  # our own reload's events change nothing
    devaudio._follow(None)
    assert not [c for c in pactl.calls[n:] if c[0] == "load-module"]


def test_timer_can_message_the_phone(monkeypatch):
    out = set_timer(seconds=40, phone=True)
    assert "phone too" in out
    row = store.schedules_list(enabled_only=True, limit=5)[0]
    sent = []
    monkeypatch.setattr("jarvis.core.sound.play", lambda *a, **k: None)
    monkeypatch.setattr("jarvis.core.notify.notify", lambda title, text="", **k: sent.append(k) or [])
    reminders.fire(row)
    assert sent[-1]["telegram"] is True
    reminders.fire({**row, "note": ""})
    assert sent[-1]["telegram"] is None  # a plain timer stays on the laptop


def test_timer_with_telegram_tail_is_one_request(monkeypatch):
    text = "set timer for 40 second and when timer complete send messgage to telegra as well"
    assert not planner.is_multi(text)  # no planner call, no second timer
    monkeypatch.setattr(config, "FASTPATH", True)
    it = fastpath.match(text)
    assert it.tool == "set_timer" and it.args == {"seconds": 40.0, "phone": True}
    tasks = planner.merge_tails([{"text": "set a timer for 40 seconds", "kind": "quick"},
                                 {"text": "when the timer completes tell me on telegram", "kind": "quick",
                                  "depends_on": [0]}])
    assert len(tasks) == 1


def test_same_tool_call_twice_runs_once(monkeypatch):
    calls = []

    def chat(msgs, **kw):
        calls.append(kw)
        if len(calls) == 1:
            tc = [{"id": f"t{i}", "name": "set_timer", "args": {"seconds": 40}} for i in (1, 2)]
            return agent.llm.Reply("", "", [], message=AIMessage(content="", tool_calls=tc))
        return agent.llm.Reply("Timer set.", "", [], message=AIMessage(content="Timer set."))

    monkeypatch.setattr(agent.llm, "chat", chat)
    monkeypatch.setattr(agent.router, "route", lambda *a, **k: agent.router.Route(["clock"], "rules", False, 0))
    agent.Agent().run("set two timers by mistake")
    assert len(store.schedules_list(enabled_only=True, limit=10)) == 1


def test_wallpaper_processes_are_one_name():
    from jarvis.core import doctor

    class P:
        def __init__(self, name, cmd, parent=None):
            self._n, self._c, self._p = name, cmd, parent

        def name(self):
            return self._n

        def cmdline(self):
            return self._c

        def parent(self):
            return self._p

    host = P("python3", ["/usr/bin/python3", "scripts/kurama_wallpaper.py", "--url"])
    assert doctor.app_name(host) == "KURAMA screen"
    assert doctor.app_name(P("WebKitWebProcess", ["/usr/lib/webkit/WebKitWebProcess", "7"], host)) == "KURAMA screen"
    assert doctor.app_name(P("WebKitWebProcess", ["/usr/lib/webkit/WebKitWebProcess"], P("evolution", ["evolution"]))) == "WebKit"


def test_the_window_moves_webkits_gc_signal_off_its_hotkey_signals():
    """The window takes SIGUSR1 / SIGUSR2 for hotkeys; WebKit's JS engine pauses threads for garbage collection with
    SIGUSR1 unless JSC_SIGNAL_FOR_GC says otherwise: the pause was never answered and every window froze (11-02)."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "scripts" / "kurama_wallpaper.py").read_text()
    assert src.index('os.environ.setdefault("JSC_SIGNAL_FOR_GC"') < src.index('gi.require_version("WebKit2"')
    assert "signal.SIGUSR1" in src  # (the hotkey still uses it: the engine must not)


def test_the_chat_size_is_never_saved_from_the_shrunk_invisible_panel():
    """The 1 x 1 invisible panel (holds, preload) saved itself as the owner's chat size (mini.json 1 x 1, 11-02):
    the saver skips it and anything under the minimum, and a broken saved size falls back to the default."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "scripts" / "kurama_wallpaper.py").read_text()
    saver = src[src.index("def on_configure"):src.index("def drop_panel")]
    assert 'getattr(self, "shrunk", False)' in saver and "PANEL_MIN_W" in saver
    assert "def saved_size" in src and "self.saved_size()" in src


def test_gesture_control_lets_go_of_the_camera_during_a_call():
    """11-03: a Facebook call couldn't get the camera while hand-gesture control held it."""
    import importlib.util
    import numpy as np
    spec = importlib.util.spec_from_file_location("gesture_runner", config.ROOT / "scripts" / "gesture_runner.py")
    gr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gr)
    opened, call, t = [], [False], [0.0]

    class Cam:
        def __init__(self, *a):
            opened.append("open")
        def set(self, *a):
            return True
        def read(self):
            return True, np.ones((4, 6, 3), np.uint8)
        def release(self):
            opened.append("release")
    Shared = gr.shared_capture(Cam, is_call=lambda: call[0], now=lambda: t[0], sleep=lambda s: None)
    cap = Shared(0)
    cap.set(3, 1280)
    assert cap.read()[1].sum() > 0
    call[0], t[0] = True, 2.0
    ok, frame = cap.read()
    assert ok and frame.sum() == 0 and opened == ["open", "release"]  # the call has the camera; gestures pause
    call[0], t[0] = False, 4.0
    assert cap.read()[1].sum() > 0 and opened == ["open", "release", "open"]  # back after the call
    assert gr.CALL_URL.search("https://www.facebook.com/groupcall/ROOM:/?call_id=2170452144&has_video=true")
    assert gr.CALL_URL.search("https://meet.google.com/abc-defg-hij") and not gr.CALL_URL.search("https://www.facebook.com/")


def test_mini_window_startup_and_size_regressions():
    """11-05: (1) the chat page loaded before the server listened -> its error page counted as ready -> Alt did
    nothing after a start; (2) the 1 x 1 hold-to-talk window grew back to the minimum and that was saved as the
    owner's chat size ("squished" after every Alt)."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "scripts" / "kurama_wallpaper.py").read_text()
    assert 'v.connect("load-failed", self._panel_load_failed)' in src
    assert "if self.page_ready or self.panel_failed:" in src  # an error page is never ready
    assert "if (w, h) == (PANEL_MIN_W, PANEL_MIN_H):" in src  # a clamped size is not the owner's size
    assert src.count("self.hold_size()") >= 2 and "time.monotonic() < getattr(self, \"size_hold_until\"" in src


def test_mini_window_opens_at_full_size_and_is_ready_soon():
    """11-05: after an Alt hold the chat opened small and jumped to its size a moment later (the mapped 1 x 1 window
    was resized in place); after start-up the invisible page took ~15 s to say "ready" (no animation frames there)."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    src = (root / "scripts" / "kurama_wallpaper.py").read_text()
    unshrink = src[src.index("def unshrink_ghost"):src.index("def unghost")]
    assert unshrink.index("self.panel.hide()") < unshrink.index("self.panel.resize(")  # resized while unmapped
    assert "PANEL_PRELOAD_S = 1 " in src
    assert 'msg == "ready" or msg.startswith(' in src  # the page's "ready" reaches the panel (it never did)
    js = (root / "frontend" / "app.js").read_text()
    assert 'setTimeout(ready, 400);' in js


def _beside_pos():
    """scripts/kurama_wallpaper.py's beside_pos + clamp, loaded without GTK."""
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "scripts" / "kurama_wallpaper.py").read_text()
    tree = ast.parse(src)
    code = "\n\n".join(ast.get_source_segment(src, n) for n in tree.body
                       if isinstance(n, ast.FunctionDef) and n.name in ("clamp", "beside_pos"))
    ns = {"BUBBLE": 56}
    exec(compile(code, "beside_pos", "exec"), ns)  # noqa: S102 - our own source
    return ns["beside_pos"]


def test_chat_position_is_one_fixed_rule():
    """11-05: the chat opened above / below / left / right at random from the same button position."""
    from types import SimpleNamespace as NS
    pos = _beside_pos()
    wa = NS(x=0, y=27, width=1920, height=1053)
    w, h, b = 400, 600, 56
    # same button place -> same chat place, every time
    assert len({pos(1800, 900, w, h, wa) for _ in range(5)}) == 1
    # button bottom-right: chat to its LEFT, bottoms level
    x, y = pos(1800, 900, w, h, wa)
    assert x + w <= 1800 and y + h == 900 + b
    # button top-left: chat to its RIGHT, tops level
    x, y = pos(40, 60, w, h, wa)
    assert x >= 40 + b and y == 60
    # button bottom-left: right side, bottoms level; top-right: left side, tops level
    x, y = pos(30, 980, w, h, wa)
    assert x >= 30 + b and y + h <= 27 + 1053 - 8
    x, y = pos(1850, 40, w, h, wa)
    assert x + w <= 1850 and y == 40
    # never outside the screen, never over the button
    for bx in range(0, 1920 - b, 97):
        for by in range(27, 1080 - b, 89):
            x, y = pos(bx, by, w, h, wa)
            assert 0 <= x and x + w <= 1920 and 27 <= y and y + h <= 1080
            assert not (x < bx + b and bx < x + w and y < by + b and by < y + h), (bx, by)
