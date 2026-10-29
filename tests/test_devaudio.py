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
