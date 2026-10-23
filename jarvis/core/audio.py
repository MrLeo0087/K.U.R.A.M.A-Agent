"""Audio I/O: mic capture with webrtcvad endpointing, a stoppable player, and a barge-in monitor.

- record(): 16 kHz mono int16 from the mic; starts when speech is detected, stops after
  config.VAD_SILENCE_MS of silence (or VAD_MAX_UTTERANCE_S); returns WAV bytes or None.
- Player: plays a file or bytes (or a live byte stream on stdin) with ffplay / mpv / paplay,
  whichever `which` finds first. stop() kills it immediately (barge-in).
- BargeInMonitor: while TTS plays, watches the mic and calls on_speech() once the user talks.
  It needs loud (RMS >= BARGE_IN_RMS) AND voiced frames for BARGE_IN_FRAMES in a row, so the
  assistant's own voice leaking from the speakers rarely triggers it.

sounddevice/numpy are imported lazily so importing this module stays cheap.
"""
from __future__ import annotations

import collections
import io
import logging
import queue
import shutil
import subprocess
import threading
import time
import wave
from pathlib import Path
from typing import Callable, Protocol

from jarvis.core import config

log = logging.getLogger(__name__)


class AudioError(RuntimeError):
    """Mic or player problem with a human-readable message."""


class _VadLike(Protocol):
    def is_speech(self, frame: bytes, sample_rate: int) -> bool: ...


def make_vad(aggressiveness: int | None = None) -> _VadLike:
    import webrtcvad

    return webrtcvad.Vad(config.VAD_AGGRESSIVENESS if aggressiveness is None else aggressiveness)


def frame_bytes(sample_rate: int | None = None, frame_ms: int | None = None) -> int:
    sr = sample_rate or config.AUDIO_SAMPLE_RATE
    return sr * (frame_ms or config.VAD_FRAME_MS) // 1000 * 2  # int16 = 2 bytes/sample


def pcm_to_wav(pcm: bytes, sample_rate: int | None = None) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate or config.AUDIO_SAMPLE_RATE)
        wf.writeframes(pcm)
    return buf.getvalue()


def rms(frame: bytes) -> float:
    import numpy as np

    a = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(a * a))) if a.size else 0.0


# --- endpointing (pure logic, testable with synthetic frames) ---
class Endpointer:
    """Feed fixed-size PCM frames with push(); it returns True when the utterance is over.

    Speech starts when >= start_ratio of the last start_window frames are voiced. A pre-roll of
    frames before that point is kept so the first word is not clipped. Timeouts count frames,
    not wall time, so behaviour is deterministic.
    """

    def __init__(self, vad: _VadLike | None = None, sample_rate: int | None = None,
                 frame_ms: int | None = None, silence_ms: int | None = None,
                 max_s: float | None = None, min_speech_ms: int | None = None,
                 start_timeout_s: float | None = None, start_window: int = 8,
                 start_ratio: float = 0.75, preroll_frames: int = 10):
        self.vad = vad or make_vad()
        self.sample_rate = sample_rate or config.AUDIO_SAMPLE_RATE
        self.frame_ms = frame_ms or config.VAD_FRAME_MS
        self.silence_frames = max(1, (silence_ms or config.VAD_SILENCE_MS) // self.frame_ms)
        self.max_frames = int((max_s or config.VAD_MAX_UTTERANCE_S) * 1000 // self.frame_ms)
        self.min_speech_frames = (config.VAD_MIN_SPEECH_MS if min_speech_ms is None
                                  else min_speech_ms) // self.frame_ms
        timeout = config.VAD_START_TIMEOUT_S if start_timeout_s is None else start_timeout_s
        self.start_timeout_frames = int(timeout * 1000 // self.frame_ms)
        self.start_ratio = start_ratio
        self._window: collections.deque[bool] = collections.deque(maxlen=start_window)
        self._preroll: collections.deque[bytes] = collections.deque(maxlen=preroll_frames)
        self._voiced: list[bytes] = []
        self.triggered = False
        self.timed_out = False
        self.done = False
        self.speech_frames = 0
        self._end_window: collections.deque[bool] = collections.deque(maxlen=self.silence_frames)
        self._seen = 0
        # adaptive noise gate: noisy laptop mics fool webrtcvad into "speech" ~90% of the time,
        # so a frame only counts as speech if it is also clearly louder than the room floor
        self._ambient: collections.deque[float] = collections.deque(maxlen=60)
        self.noise_floor: float | None = None
        self.on_speech_start: Callable[[], None] | None = None

    def push(self, frame: bytes) -> bool:
        if self.done:
            return True
        self._seen += 1
        speech = self._is_speech(frame)
        if not self.triggered:
            self._preroll.append(frame)
            self._window.append(speech)
            w = self._window
            if len(w) == w.maxlen and sum(w) >= self.start_ratio * w.maxlen:
                self.triggered = True
                self._voiced.extend(self._preroll)
                self.speech_frames = sum(w)
                if self.on_speech_start:
                    self.on_speech_start()
            elif self._seen >= self.start_timeout_frames:
                self.timed_out = self.done = True
            return self.done
        self._voiced.append(frame)
        self._end_window.append(speech)
        if speech:
            self.speech_frames += 1
        w = self._end_window
        quiet = len(w) == w.maxlen and sum(w) <= config.VAD_END_SPEECH_RATIO * w.maxlen
        if quiet or len(self._voiced) >= self.max_frames:
            self.done = True
        return self.done

    def _is_speech(self, frame: bytes) -> bool:
        level = rms(frame)
        if not self.triggered:  # learn the room floor before the user speaks
            self._ambient.append(level)
            if len(self._ambient) >= 5:
                lv = sorted(self._ambient)
                # 20th percentile is robust to clicks; the cap stops early speech being learned
                self.noise_floor = min(lv[len(lv) // 5], config.VAD_FLOOR_CAP)
        floor = self.noise_floor if self.noise_floor is not None else 0.0
        gate = max(config.VAD_MIN_RMS, floor * config.VAD_NOISE_RATIO)
        return level >= gate and bool(self.vad.is_speech(frame, self.sample_rate))

    @property
    def speech_ms(self) -> int:
        return self.speech_frames * self.frame_ms

    def pcm(self) -> bytes | None:
        """Captured utterance (raw PCM) or None if there was no real speech."""
        if not self.triggered or self.speech_frames < self.min_speech_frames:
            return None
        return b"".join(self._voiced)

    def wav(self) -> bytes | None:
        pcm = self.pcm()
        return pcm_to_wav(pcm, self.sample_rate) if pcm else None


def _input_stream(callback: Callable, sample_rate: int, frame_ms: int):
    try:
        import sounddevice as sd

        return sd.RawInputStream(samplerate=sample_rate, blocksize=sample_rate * frame_ms // 1000,
                                 channels=1, dtype="int16", device=config.AUDIO_INPUT_DEVICE,
                                 callback=callback)
    except Exception as e:  # PortAudio missing, no mic, device busy...
        raise AudioError(f"cannot open microphone: {e}") from e


def record(max_s: float | None = None, on_speech_start: Callable[[], None] | None = None,
           stop_event: threading.Event | None = None, vad: _VadLike | None = None) -> bytes | None:
    """Block until one utterance is captured. Returns WAV bytes, or None (silence / cancelled).

    Setting stop_event ends recording early: before speech it cancels, after speech it keeps
    what was captured so far.
    """
    sr, fms = config.AUDIO_SAMPLE_RATE, config.VAD_FRAME_MS
    ep = Endpointer(vad=vad, sample_rate=sr, frame_ms=fms, max_s=max_s)
    ep.on_speech_start = on_speech_start
    frames: queue.Queue[bytes] = queue.Queue()
    need = frame_bytes(sr, fms)

    def cb(indata, n, t, status):  # PortAudio thread: only enqueue
        frames.put(bytes(indata))

    with _input_stream(cb, sr, fms):
        while not ep.done:
            if stop_event is not None and stop_event.is_set():
                break
            try:
                f = frames.get(timeout=0.2)
            except queue.Empty:
                continue
            if len(f) == need:
                ep.push(f)
    return ep.wav()


# --- playback ---
def player_name() -> str:
    for name in config.AUDIO_PLAYERS:
        if shutil.which(name):
            return name
    raise AudioError("no audio player found: install ffmpeg (ffplay) or mpv "
                     "(sudo apt install ffmpeg)")


def player_cmd(src: str | None = None, fmt: str = "mp3", name: str | None = None) -> list[str]:
    """Command to play file `src`, or stdin (format `fmt`) when src is None."""
    name = name or player_name()
    if name == "ffplay":
        base = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]
        return base + ([src] if src else ["-f", fmt, "-probesize", "32", "-i", "-"])
    if name == "mpv":
        base = ["mpv", "--no-terminal", "--no-video"]
        if src:
            return base + [src]
        return base + ["--cache=no", f"--demuxer-lavf-format={fmt}", "--demuxer-lavf-probesize=32",
                       "--demuxer-readahead-secs=0", "-"]
    if name == "paplay":  # libsndfile formats only (wav/ogg/flac); mp3 support varies
        return ["paplay", src] if src else ["paplay"]
    raise AudioError(f"unsupported player {name}")


class Player:
    """One playback process. Use play() for files/bytes, or start()/write()/finish() to stream."""

    def __init__(self, fmt: str = "mp3"):
        self.fmt = fmt
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self.stopped = False

    def start(self, src: str | None = None) -> "Player":
        with self._lock:
            if self.stopped:
                return self
            try:
                self._proc = subprocess.Popen(
                    player_cmd(src, self.fmt), stdin=None if src else subprocess.PIPE,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError as e:
                raise AudioError(f"cannot start audio player: {e}") from e
        return self

    def write(self, data: bytes) -> bool:
        """Feed audio to a streaming player. False once stopped or the player died."""
        p = self._proc
        if self.stopped or p is None or p.stdin is None:
            return False
        try:
            p.stdin.write(data)
            p.stdin.flush()
            return True
        except (BrokenPipeError, OSError, ValueError):
            return False

    def finish(self, timeout: float | None = None) -> int | None:
        """Close stdin and wait for playback to end (returns at once if stopped)."""
        p = self._proc
        if p is None:
            return None
        if p.stdin:
            try:
                p.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        if self.stopped:
            return p.poll()
        try:
            return p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.stop()
            return None

    def play(self, src: str | Path | bytes, block: bool = True) -> None:
        if isinstance(src, (bytes, bytearray)):
            self.start()
            self.write(bytes(src))
            if block:
                self.finish()
            elif self._proc and self._proc.stdin:
                try:
                    self._proc.stdin.close()
                except OSError:
                    pass
        else:
            path = Path(src)
            if not path.is_file():
                raise AudioError(f"no such audio file: {path}")
            self.start(str(path))
            if block:
                self.finish()

    def stop(self) -> None:
        with self._lock:
            self.stopped = True
            p = self._proc
            if p and p.poll() is None:
                p.kill()

    @property
    def playing(self) -> bool:
        return bool(self._proc and self._proc.poll() is None and not self.stopped)


def play(src: str | Path | bytes, block: bool = True, fmt: str = "mp3") -> Player:
    """Play a file path or encoded bytes; returns the Player (call .stop() to interrupt)."""
    p = Player(fmt)
    p.play(src, block=block)
    return p


# --- barge-in ---
class BargeInDetector:
    """Pure decision logic: loud AND voiced frames for `frames` frames in a row."""

    def __init__(self, vad: _VadLike | None = None, threshold: float | None = None,
                 frames: int | None = None, sample_rate: int | None = None):
        self.vad = vad or make_vad(3)  # most aggressive: reject non-speech hard
        self.threshold = config.BARGE_IN_RMS if threshold is None else threshold
        self.frames = frames or config.BARGE_IN_FRAMES
        self.sample_rate = sample_rate or config.AUDIO_SAMPLE_RATE
        self._run = 0

    def push(self, frame: bytes) -> bool:
        if rms(frame) >= self.threshold and self.vad.is_speech(frame, self.sample_rate):
            self._run += 1
        else:
            self._run = 0
        return self._run >= self.frames


class BargeInMonitor:
    """Watch the mic in the background and call on_speech() once when the user starts talking."""

    def __init__(self, on_speech: Callable[[], None], grace_s: float | None = None,
                 detector: BargeInDetector | None = None):
        self.on_speech = on_speech
        self.grace_s = config.BARGE_IN_GRACE_S if grace_s is None else grace_s
        self.detector = detector
        self.triggered = False
        self._frames: queue.Queue[bytes] = queue.Queue(maxsize=200)
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream = None

    def start(self) -> "BargeInMonitor":
        if not config.BARGE_IN:
            return self
        sr, fms = config.AUDIO_SAMPLE_RATE, config.VAD_FRAME_MS
        self.detector = self.detector or BargeInDetector(sample_rate=sr)

        def cb(indata, n, t, status):
            try:
                self._frames.put_nowait(bytes(indata))
            except queue.Full:
                pass

        try:
            self._stream = _input_stream(cb, sr, fms)
            self._stream.start()
        except Exception as e:
            log.warning("barge-in disabled: %s", e)
            self._stream = None
            return self
        self._thread = threading.Thread(target=self._loop, name="barge-in", daemon=True)
        self._thread.start()
        return self

    def _loop(self) -> None:
        t0 = time.monotonic()
        need = frame_bytes()
        while not self._halt.is_set():
            try:
                f = self._frames.get(timeout=0.2)
            except queue.Empty:
                continue
            if len(f) != need or time.monotonic() - t0 < self.grace_s:
                continue
            if self.detector.push(f):
                self.triggered = True
                try:
                    self.on_speech()
                finally:
                    self._halt.set()

    def stop(self) -> None:
        self._halt.set()
        s, self._stream = self._stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)
