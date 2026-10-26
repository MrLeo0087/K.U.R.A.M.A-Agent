from jarvis.core import voicecfg, wake


def test_wake_sensitivity_levels_reach_the_listener():
    assert voicecfg.wake_level() == "normal"
    voicecfg.set_wake_level("high")
    assert voicecfg.wake_min_rms() < 900 and voicecfg.wake_ratio() < 0.7 and wake._ratio() == voicecfg.wake_ratio()
    voicecfg.set_wake_level("low")
    assert voicecfg.wake_min_rms() > 900
    import pytest
    with pytest.raises(ValueError):
        voicecfg.set_wake_level("max")


def test_mic_volume_uses_pactl(monkeypatch):
    calls = []

    def pactl(*a):
        calls.append(a)
        return {"get-source-volume": "Volume: front-left: 61680 /  94% / -1.58 dB", "get-default-source": "kurama_ec_source\n"}.get(a[0], "")
    monkeypatch.setattr(voicecfg, "_pactl", pactl)
    st = voicecfg.set_mic_volume(500)  # clamped
    assert ("set-source-volume", "@DEFAULT_SOURCE@", "150%") in calls
    assert st == {"volume": 94, "source": "kurama_ec_source", "echo_canceller": True}
