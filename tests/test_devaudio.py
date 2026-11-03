from jarvis.core import devaudio


def test_echo_canceller_only_while_a_page_records(monkeypatch):
    calls, state = [], {"on": False}
    monkeypatch.setattr(devaudio, "available", lambda: True)
    monkeypatch.setattr(devaudio, "hear", lambda: False)
    monkeypatch.setattr(devaudio, "cancelling", lambda: state["on"])
    monkeypatch.setattr(devaudio, "cancel_on", lambda *a: calls.append("on") or state.update(on=True))
    monkeypatch.setattr(devaudio, "cancel_off", lambda: calls.append("off") or state.update(on=False))
    monkeypatch.setattr(devaudio, "watch", lambda: None)
    monkeypatch.setattr(devaudio, "status", lambda: {})
    timers = []

    class T:
        daemon = False

        def __init__(self, s, fn):
            self.fn = fn
            timers.append(self)

        def start(self):
            pass

        def cancel(self):
            timers.remove(self)
    monkeypatch.setattr(devaudio.threading, "Timer", T)
    devaudio._users.clear()
    devaudio.apply()  # startup with nobody recording: plain speaker + mic (mic free, normal volume)
    assert calls == ["off"]
    devaudio.mic_use(True, "main")
    devaudio.mic_use(True, "mini")
    assert calls == ["off", "on"]
    devaudio.mic_use(False, "main")
    assert not timers  # the mini page still records
    devaudio.mic_use(False, "mini")
    assert len(timers) == 1
    devaudio.mic_use(True, "main")  # back within the linger time: no flapping
    assert not timers and calls == ["off", "on"]
    devaudio.mic_use(False, "main")
    timers[0].fn()
    assert calls[-1] == "off" and not state["on"]


# ---- 11-03: with KURAMA the sound went to the laptop speaker while a Bluetooth speaker was on ----
import pytest  # noqa: E402

SPK = "alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__hw_sofhdadsp__sink"
HDMI = "alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__hw_sofhdadsp_3__sink"
BT = "bluez_output.F7_0F_9C_F3_20_70.1"
MIC = "alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__hw_sofhdadsp_6__source"
DESC = {SPK: "Raptor Lake-P/U/H cAVS Speaker + Headphones", HDMI: "Raptor Lake-P/U/H cAVS HDMI / DisplayPort 1 Output",
        BT: "U-2500BT", devaudio.EC_SINK: "Echo-Cancel Sink"}


class FakePactl:
    """A tiny audio server: sinks, sources, the default sink, our module."""

    def __init__(self, sinks, default):
        self.sinks, self.default, self.loaded, self.calls = list(sinks), default, None, []

    def __call__(self, *args, timeout=5):
        self.calls.append(args)
        a = args
        if a[:2] == ("list", "short") and a[2] == "sinks":
            return "".join(f"{i}\t{n}\tPipeWire\n" for i, n in enumerate(self.sinks + ([devaudio.EC_SINK] if self.loaded else [])))
        if a[:2] == ("list", "short") and a[2] == "sources":
            return f"1\t{MIC}\n" + (f"2\t{devaudio.EC_SOURCE}\n" if self.loaded else "")
        if a[:2] == ("list", "short") and a[2] == "modules":
            return f"7\tmodule-echo-cancel\tsink_name={devaudio.EC_SINK} sink_master={self.loaded}\n" if self.loaded else ""
        if a == ("list", "sinks"):
            return "".join(f"Name: {n}\n\tDescription: {DESC.get(n, n)}\n" for n in self.sinks)
        if a[0] == "get-default-sink":
            return self.default
        if a[0] == "get-default-source":
            return devaudio.EC_SOURCE if self.loaded else MIC
        if a[0] == "load-module":
            self.loaded = next(x.split("=", 1)[1] for x in a if x.startswith("sink_master="))
        if a[0] == "unload-module":
            self.loaded = None
        if a[0] == "set-default-sink":
            self.default = a[1]
        return ""


@pytest.fixture
def pa(monkeypatch, tmp_path):
    from jarvis.core import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(devaudio, "hear", lambda: False)
    monkeypatch.setattr(devaudio.time, "sleep", lambda s: None)

    def make(sinks, default, saved=None, configured=None):
        fake = FakePactl(sinks, default)
        fake.configured = {"sink": configured}
        monkeypatch.setattr(devaudio, "_pactl", fake)
        monkeypatch.setattr(devaudio, "_configured", lambda kind: fake.configured.get(kind))
        monkeypatch.setattr(devaudio, "_set_configured", lambda kind, name: fake.configured.update({kind: name}))
        if saved:
            devaudio._save(saved)
        return fake
    return make


def test_the_canceller_sends_sound_to_the_bluetooth_speaker(pa):
    """The live case: saved = the laptop speaker from long ago, our canceller already the default, U-2500BT on."""
    fake = pa([HDMI, SPK, BT], devaudio.EC_SINK, {"sink": SPK, "source": MIC})
    devaudio.cancel_on()
    assert fake.loaded == BT and fake.default == devaudio.EC_SINK
    devaudio.cancel_off()
    assert fake.loaded is None and fake.default == BT  # the sound stays on the Bluetooth speaker after


def test_startup_with_nothing_of_ours_loaded_never_touches_the_speaker(pa):
    fake = pa([SPK, BT], BT, {"sink": SPK, "source": MIC})
    devaudio.cancel_off()
    assert fake.default == BT and not any(c[0] == "set-default-sink" for c in fake.calls)


def test_the_systems_own_choice_is_respected(pa):
    fake = pa([SPK, BT], SPK, {"sink": BT, "source": MIC})  # the owner picked the laptop speaker in Settings
    devaudio.cancel_on()
    assert fake.loaded == SPK
    devaudio.cancel_off()
    assert fake.default == SPK


def test_a_bluetooth_speaker_connecting_while_kurama_listens_gets_the_sound(pa, monkeypatch):
    fake = pa([SPK], SPK)
    devaudio.cancel_on()
    assert fake.loaded == SPK
    fake.sinks.append(BT)
    devaudio._follow(BT)
    assert fake.loaded == BT


def test_hdmi_is_never_preferred(pa):
    pa([HDMI, SPK], devaudio.EC_SINK, {"sink": HDMI, "source": MIC})
    assert devaudio._best({"sink": HDMI}) == SPK  # a monitor's speakers only when nothing else exists



def test_the_remembered_choice_comes_back_exactly(pa):
    """Before KURAMA the system remembered the Bluetooth speaker; KURAMA's canceller replaces the default while it
    listens; after, the same remembered choice is back, even when the speaker went off meanwhile."""
    fake = pa([SPK, BT], BT, configured=BT)
    devaudio.cancel_on()
    fake.configured["sink"] = devaudio.EC_SINK  # what set-default-sink does to the remembered choice
    fake.sinks.remove(BT)  # the speaker is switched off while KURAMA listens
    devaudio.cancel_off()
    assert fake.configured["sink"] == BT and not any(c[0] == "set-default-sink" and c[1] == SPK for c in fake.calls)
