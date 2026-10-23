"""Wake word (core/wake.py) and the wake-mode voice loop, with mocked audio and recognizers."""
import struct
import threading

import pytest

from jarvis.core import config, wake

SR = 16000
FRAME = SR * 30 // 1000  # samples per 30 ms frame


def frame(level: int) -> bytes:
    """A 30 ms frame of constant-magnitude square wave (RMS == level)."""
    return struct.pack(f"<{FRAME}h", *([level, -level] * (FRAME // 2)))


class LoudVad:
    def is_speech(self, f, sr):
        return True


def detector(**kw):
    return wake.BurstDetector(vad=LoudVad(), sample_rate=SR, frame_ms=30, **kw)


def feed(det, spec):
    """spec: list of (level, n_frames). Returns the bursts emitted."""
    out = []
    for level, n in spec:
        for _ in range(n):
            b = det.push(frame(level))
            if b is not None:
                out.append(b)
    return out


# --- phrase matching ---
@pytest.mark.parametrize("text", ["Hey Jarvis", "hello jarvis", "Hi Jarvis.", "OK Jarvis", "okay kurama",
                                  "hey jar vis", "hey service", "hi travis", "hey karama", "hello corama",
                                  "uh hey jarvis", "Jarvis", "service", "Kurama"])
def test_wake_positives(text):
    hit = wake.match_wake(text, name_alone=True)
    assert hit is not None and hit.command == ""


@pytest.mark.parametrize("text", ["hey Siri", "service charge", "the service is bad", "hello",
                                  "I told Jarvis", "hey jar", "what time is it", ""])
def test_wake_negatives(text):
    assert wake.match_wake(text, name_alone=True) is None


def test_name_alone_switch():
    assert wake.match_wake("service", name_alone=False) is None
    assert wake.match_wake("hey service", name_alone=False) is not None


def test_wake_with_command():
    assert wake.match_wake("Hey Jarvis, what's the time?").command == "what's the time"
    assert wake.match_wake("Jarvis open YouTube", name_alone=True).command == "open YouTube"
    assert wake.strip_wake("hey jarvis open youtube") == "open youtube"
    assert wake.strip_wake("open youtube") == "open youtube"


@pytest.mark.parametrize("text,kind", [
    ("sleep Jarvis", "sleep"), ("go to sleep", "sleep"), ("stop listening", "sleep"), ("bye Jarvis", "sleep"),
    ("so jao", "sleep"), ("sut", "sleep"), ("okay jarvis you can sleep now", "sleep"),
    ("exit Jarvis", "exit"), ("shut down Jarvis", "exit"), ("stop", "stop"), ("stop Jarvis", "stop"),
    ("shut down", None), ("put the computer to sleep", None), ("stop the music", None), ("what is sleep", None),
])
def test_classify(text, kind):
    assert wake.classify(text) == kind


# --- burst filter ---
def test_burst_accepts_short_speech():
    det = detector()
    bursts = feed(det, [(100, 20), (5000, 30), (100, 20)])  # 0.9 s of speech
    assert len(bursts) == 1 and 0.8 <= bursts[0].dur_s <= 1.0


def test_burst_rejects_too_short_and_too_long():
    det = detector(max_s=2.5)
    assert feed(det, [(100, 20), (5000, 8), (100, 20)]) == [] and det.rejected == "short"  # 0.24 s
    assert feed(det, [(100, 10), (5000, 120), (100, 20)]) == [] and det.rejected == "long"  # 3.6 s
    assert len(feed(det, [(5000, 30), (100, 20)])) == 1  # recovers after the long one


def test_burst_ignores_quiet_room():
    det = detector()
    assert feed(det, [(400, 200)]) == []  # below VAD_MIN_RMS: never a burst, VAD never consulted


def test_burst_noise_gate_adapts():
    det = detector()
    feed(det, [(800, 50)])  # learned floor 800 -> gate 2400
    assert feed(det, [(1500, 30), (800, 20)]) == []
    assert len(feed(det, [(5000, 30), (800, 20)])) == 1


# --- rate guard ---
def test_rate_guard():
    t = [0.0]
    g = wake.RateGuard(per_min=3, clock=lambda: t[0])
    assert [g.allow() for _ in range(4)] == [True, True, True, False]
    t[0] = 59.9
    assert not g.allow()
    t[0] = 60.1
    assert g.allow()


# --- recognizer fallback ---
def test_google_falls_back_to_groq_and_backs_off():
    calls = []

    def google(pcm):
        calls.append("g")
        raise OSError("offline")

    def groq(pcm):
        calls.append("q")
        return "hey jarvis"

    t = [0.0]
    r = wake.WakeRecognizer("google", google=google, groq=groq, clock=lambda: t[0])
    assert r.text(b"x") == "hey jarvis" and calls == ["g", "q"]
    assert r.text(b"x") == "hey jarvis" and calls == ["g", "q", "q"]  # google skipped while down
    t[0] = config.WAKE_GOOGLE_RETRY_S + 1
    r.text(b"x")
    assert calls[-2:] == ["g", "q"]


def test_google_unknown_is_not_failure():
    r = wake.WakeRecognizer("google", google=lambda p: "", groq=lambda p: pytest.fail("no fallback"))
    assert r.text(b"x") == ""


def test_groq_engine_and_total_failure():
    def boom(p):
        raise RuntimeError("down")
    assert wake.WakeRecognizer("groq", google=lambda p: pytest.fail("x"), groq=lambda p: "hi").text(b"") == "hi"
    assert wake.WakeRecognizer("google", google=boom, groq=boom).text(b"") is None


def test_google_audio_data_from_pcm(monkeypatch):
    import speech_recognition as sr
    seen = {}

    def fake(self, data, language=None, **kw):
        seen["rate"], seen["width"], seen["lang"] = data.sample_rate, data.sample_width, language
        return "hey jarvis"
    monkeypatch.setattr(sr.Recognizer, "recognize_google", fake)
    assert wake.WakeRecognizer._google(frame(1000) * 10) == "hey jarvis"
    assert seen == {"rate": 16000, "width": 2, "lang": config.WAKE_GOOGLE_LANG}


# --- listener check ---
class FakeRec:
    def __init__(self, text):
        self.text_val, self.calls, self.last_engine = text, 0, "fake"

    def text(self, pcm):
        self.calls += 1
        return self.text_val


def test_check_wake_and_command():
    lst = wake.WakeListener(FakeRec("hey jarvis"), wake.RateGuard(99), command_stt=lambda p: pytest.fail("x"))
    ev = lst.check(wake.Burst(b"\0" * 100, 0.8))
    assert ev and ev.command == ""
    lst = wake.WakeListener(FakeRec("hey jarvis what time"), wake.RateGuard(99),
                            command_stt=lambda p: ("Hey Jarvis, what's the time?", "en"))
    assert lst.check(wake.Burst(b"\0" * 100, 1.5)).command == "what's the time"
    lst = wake.WakeListener(FakeRec("hey jarvis what time"), wake.RateGuard(99), command_stt=lambda p: None)
    assert lst.check(wake.Burst(b"\0" * 100, 1.5)).command == "what time"  # Whisper failed: Google text


def test_check_long_burst_uses_head_then_whisper():
    rec = FakeRec("hey jarvis")
    seen = []
    lst = wake.WakeListener(rec, wake.RateGuard(99),
                            command_stt=lambda p: seen.append(len(p)) or ("Jarvis, kitchen light kaha cha?", "ne"))
    pcm = b"\0" * (SR * 2 * 4)  # 4 s
    ev = lst.check(wake.Burst(pcm, 4.0))
    assert ev.command == "kitchen light kaha cha" and ev.lang == "ne" and seen == [len(pcm)]


def test_check_rate_guard_and_busy():
    rec = FakeRec("hey jarvis")
    lst = wake.WakeListener(rec, wake.RateGuard(1))
    assert lst.check(wake.Burst(b"", 1.0)) is not None
    assert lst.check(wake.Burst(b"", 1.0)) is None and lst.skipped == 1 and rec.calls == 1
    busy = wake.WakeListener(rec, wake.RateGuard(99), busy=lambda: True)
    assert busy.check(wake.Burst(b"", 1.0)) is None and rec.calls == 1  # skipped while TTS plays


def test_check_no_match():
    assert wake.WakeListener(FakeRec("hey siri"), wake.RateGuard(99)).check(wake.Burst(b"", 1.0)) is None
    assert wake.WakeListener(FakeRec(None), wake.RateGuard(99)).check(wake.Burst(b"", 1.0)) is None


class FakeStream:
    def __init__(self, frames):
        self.frames = frames

    def __call__(self, cb, sr, fms):
        self.cb = cb
        return self

    def __enter__(self):
        for f in self.frames:
            self.cb(f, FRAME, None, None)
        return self

    def __exit__(self, *a):
        return False


def test_listen_end_to_end_mocked():
    frames = [frame(100)] * 20 + [frame(5000)] * 30 + [frame(100)] * 20
    lst = wake.WakeListener(FakeRec("ok jarvis"), wake.RateGuard(99), stream_factory=FakeStream(frames),
                            detector=detector())
    ev = lst.listen(threading.Event())
    assert ev is not None and ev.heard == "ok jarvis"


def test_listen_stops_on_event():
    stop = threading.Event()
    stop.set()
    lst = wake.WakeListener(FakeRec("hey jarvis"), stream_factory=FakeStream([]), detector=detector())
    assert lst.listen(stop) is None


def test_stop_watcher_check():
    hits = []
    w = wake.StopWatcher(lambda: hits.append(1), FakeRec("stop"), wake.RateGuard(99))
    assert w.check(wake.Burst(b"", 0.4)) and w.triggered and hits == [1]
    w2 = wake.StopWatcher(lambda: hits.append(2), FakeRec("stop the music"), wake.RateGuard(99))
    assert not w2.check(wake.Burst(b"", 0.4)) and hits == [1]


def test_beep_wav_is_short_wav():
    data = wake.beep_wav()
    assert data[:4] == b"RIFF" and 3000 < len(data) < 8000


# --- voice loop in wake mode (no audio, no agent) ---
class FakeSpeaker:
    error = None
    first_audio_s = None
    is_speaking = False

    def __init__(self):
        self.said = []

    def speak(self, text, lang="en", block=True):
        self.said.append(text)

    def stop(self):
        pass


def make_loop(monkeypatch):
    from jarvis import voice
    loop = voice.VoiceLoop.__new__(voice.VoiceLoop)
    loop.wake_mode, loop.barge_in, loop.lang = True, False, "en"
    loop.state = "idle"
    loop.trigger, loop.cancel, loop.quit = threading.Event(), threading.Event(), threading.Event()
    loop.speaker, loop._greeter = FakeSpeaker(), None
    loop._guard, loop._recognizer = wake.RateGuard(99), FakeRec("")
    loop.responded = []
    monkeypatch.setattr(loop, "respond", lambda text, lang: loop.responded.append(text) or False, raising=False)
    monkeypatch.setattr(loop, "announce_jobs", lambda: False, raising=False)
    monkeypatch.setattr(config, "WAKE_ACK", "none")
    return loop


def test_awake_sleep_phrase_costs_no_agent(monkeypatch):
    loop = make_loop(monkeypatch)
    from jarvis.core import stt
    heard = iter([stt.Transcript("what's the time", "en", "m"), stt.Transcript("sleep Jarvis", "en", "m")])
    monkeypatch.setattr(loop, "listen", lambda **kw: next(heard), raising=False)
    assert loop.awake() == "sleep"
    assert loop.responded == ["what's the time"] and loop.speaker.said == ["Okay, going to sleep."]


def test_awake_runs_wake_command_first(monkeypatch):
    loop = make_loop(monkeypatch)
    from jarvis.core import stt
    monkeypatch.setattr(loop, "listen", lambda **kw: stt.Transcript("go to sleep", "en", "m"), raising=False)
    assert loop.awake("open youtube", "en") == "sleep" and loop.responded == ["open youtube"]


def test_awake_idle_timeout_goes_to_sleep(monkeypatch):
    loop = make_loop(monkeypatch)
    monkeypatch.setattr(config, "WAKE_IDLE_S", 0.05)
    calls = []
    monkeypatch.setattr(loop, "listen", lambda **kw: calls.append(kw) or None, raising=False)
    assert loop.awake() == "sleep" and calls and loop.responded == []


def test_awake_exit_needs_confirm(monkeypatch):
    loop = make_loop(monkeypatch)
    from jarvis.core import stt
    answers = iter([False, True])
    monkeypatch.setattr(loop, "confirm", lambda prompt: next(answers), raising=False)
    monkeypatch.setattr(loop, "listen", lambda **kw: stt.Transcript("exit Jarvis", "en", "m"), raising=False)
    assert loop.awake() == "quit" and loop.responded == []


def test_awake_stop_alone_is_ignored(monkeypatch):
    loop = make_loop(monkeypatch)
    from jarvis.core import stt
    heard = iter([stt.Transcript("stop", "en", "m"), stt.Transcript("bye jarvis", "en", "m")])
    monkeypatch.setattr(loop, "listen", lambda **kw: next(heard), raising=False)
    assert loop.awake() == "sleep" and loop.responded == []
