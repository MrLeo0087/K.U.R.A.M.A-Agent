import io
import wave

from jarvis.core import audio

FB = audio.frame_bytes(16000, 30)  # 960 bytes = 30 ms
SPEECH = b"\x10\x27" * (FB // 2)   # constant loud frame
SILENCE = b"\x00\x00" * (FB // 2)


class EnergyVad:
    def is_speech(self, frame, sr):
        return frame != SILENCE


def make(**kw):
    args = dict(vad=EnergyVad(), sample_rate=16000, frame_ms=30, silence_ms=800, max_s=5,
                min_speech_ms=250, start_timeout_s=3)
    args.update(kw)
    return audio.Endpointer(**args)


def feed(ep, frames):
    for i, f in enumerate(frames):
        if ep.push(f):
            return i
    return None


def test_endpointing_start_and_trailing_silence():
    ep = make()
    started = []
    ep.on_speech_start = lambda: started.append(True)
    frames = [SILENCE] * 20 + [SPEECH] * 30 + [SILENCE] * 40
    end = feed(ep, frames)
    assert started == [True] and ep.triggered and not ep.timed_out
    # stops after 800 ms (26 frames) of silence, not at the end of the input
    assert end == 20 + 30 + 800 // 30 - 1
    wav = ep.wav()
    with wave.open(io.BytesIO(wav)) as wf:
        assert (wf.getframerate(), wf.getnchannels(), wf.getsampwidth()) == (16000, 1, 2)
        # pre-roll (4 silent + 6 voiced frames, trigger at 6/8) + 24 more speech + silence tail
        assert wf.getnframes() * 2 == FB * (10 + 24 + 26)


def test_endpointing_timeout_short_blip_and_max_length():
    ep = make()
    assert feed(ep, [SILENCE] * 200) is not None and ep.timed_out and ep.wav() is None
    ep = make(start_window=4)
    feed(ep, [SILENCE] * 5 + [SPEECH] * 4 + [SILENCE] * 40)  # 120 ms blip < 250 ms
    assert ep.triggered and ep.wav() is None
    ep = make(max_s=1)
    end = feed(ep, [SPEECH] * 200)
    assert end is not None and end < 50 and ep.wav() is not None


def test_barge_in_needs_loud_voiced_run():
    class Always:
        def is_speech(self, f, sr):
            return True
    quiet = b"\x64\x00" * (FB // 2)  # RMS 100: echo-level
    det = audio.BargeInDetector(vad=Always(), threshold=1500, frames=3, sample_rate=16000)
    assert not any(det.push(quiet) for _ in range(10))
    assert [det.push(SPEECH) for _ in range(3)] == [False, False, True]


def test_player_cmd(monkeypatch):
    monkeypatch.setattr(audio.shutil, "which", lambda n: "/usr/bin/" + n if n == "ffplay" else None)
    assert audio.player_name() == "ffplay"
    cmd = audio.player_cmd()
    assert cmd[:3] == ["ffplay", "-nodisp", "-autoexit"] and cmd[-1] == "-"
    assert audio.player_cmd("/tmp/x.mp3")[-1] == "/tmp/x.mp3"
