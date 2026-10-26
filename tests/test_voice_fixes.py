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
    st = devaudio.set_hear(False)
    assert st["cancelling"] and not st["hear"]
    assert pactl.default == {"sink": devaudio.EC_SINK, "source": HW_SRC}  # other apps keep the real mic
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
    devaudio.set_hear(False)
    pactl.sinks.append(BT)  # Bluetooth headphones connect
    devaudio._new["sink"] = BT
    devaudio._follow()
    assert f"sink_master={BT}" in next(iter(pactl.mods.values())) and pactl.default["sink"] == devaudio.EC_SINK
    devaudio._new["sink"] = devaudio.EC_SINK  # our own reload's events change nothing
    n = len(pactl.calls)
    devaudio._follow()
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


def test_mic_off_unloads_the_canceller_and_on_brings_it_back(pactl):
    """The canceller keeps the real mic RUNNING; while the mic is off (mute / text mode) other apps need it."""
    devaudio.set_hear(False)
    assert devaudio.cancelling()
    store.kv_set("mic_off", "1")
    devaudio.apply()
    assert not devaudio.cancelling() and pactl.default == {"sink": HW_SINK, "source": HW_SRC}
    store.kv_set("mic_off", "")
    devaudio.apply()
    assert devaudio.cancelling() and pactl.default["source"] == HW_SRC
