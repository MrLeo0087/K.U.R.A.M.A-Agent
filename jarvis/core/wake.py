"""Wake word without a wake-word model: "Hey Jarvis" to wake, "sleep Jarvis" to sleep.

SLEEPING: the mic stays open and a cheap loop (RMS + webrtcvad + the adaptive noise gate from
audio.Endpointer) looks for short speech bursts (WAKE_BURST_MIN_S..WAKE_BURST_MAX_S). Only those
bursts are recognized, with the free Google Web Speech recognizer from the SpeechRecognition
package (no key, no PyAudio: we build sr.AudioData from our 16 kHz int16 PCM), falling back to
Groq Whisper when Google fails or is offline. A rate guard caps recognitions per minute.
The text is matched fuzzily (difflib) against "hey/hi/hello/ok jarvis|kurama" and common
mishearings. Words after the wake phrase are returned as a command to run at once.

Everything heavy (numpy, webrtcvad, speech_recognition) is imported lazily.
"""
from __future__ import annotations

import collections
import difflib
import logging
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from jarvis.core import audio, config

log = logging.getLogger(__name__)

GREETS = ("hey", "hi", "hello", "ok", "okay", "hay", "hai", "hei", "hallo", "helo", "yo", "oye",
          "ay", "ey", "he", "namaste", "हे", "हाय", "हेलो")
CANONICAL = {"jarvis": ("jarvis", "जार्विस", "जारविस"), "kurama": ("kurama", "कुरामा")}
MISHEARD = {"jarvis": ("jar vis", "jervis", "jarvas", "jarvish", "javis", "jaavis", "jarbis",
                       "service", "travis"),
            "kurama": ("karama", "corama", "kuruma", "ku rama", "koorama", "करामा")}
VARIANTS = tuple(v for n in CANONICAL for v in CANONICAL[n] + MISHEARD[n])
CANON = tuple(v for n in CANONICAL for v in CANONICAL[n])

SLEEP_PHRASES = ("sleep", "go to sleep", "go sleep", "stop listening", "bye", "bye bye", "goodbye",
                 "good bye", "so jao", "so ja", "sojao", "sut", "sutnus", "सो जाओ", "सो जा", "सुत",
                 "सुत्नुस")
EXIT_PHRASES = ("exit", "quit", "shut down", "shutdown", "shut yourself down", "close")
STOP_PHRASES = ("stop", "stop it", "stop talking", "ruk", "ruko", "bas", "chup", "enough",
                "रुक", "रुको", "बस", "चुप")
FILLERS = {"please", "now", "ok", "okay", "hey", "hi", "can", "you", "for", "a", "while", "just",
           "and", "the", "now", "pls"}


def normalize(text: str) -> str:
    t = re.sub(r"[^\wऀ-ॿ]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", t.replace("_", " ")).strip()


def _sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _best(cand: str, options: tuple[str, ...]) -> float:
    flat = cand.replace(" ", "")
    return max(max(_sim(cand, o), _sim(flat, o.replace(" ", ""))) for o in options)


def _is_greet(word: str) -> bool:
    return word in GREETS or (len(word) >= 4 and _best(word, GREETS) >= config.WAKE_MATCH_RATIO)


def _name_at(words: list[str], i: int, options: tuple[str, ...] = VARIANTS,
             ratio: float | None = None) -> int:
    """Number of words (1 or 2) at words[i] that form an assistant name, or 0."""
    ratio = config.WAKE_MATCH_RATIO if ratio is None else ratio
    if i >= len(words):
        return 0
    one = _best(words[i], options)
    two = 0.0  # split names ("jar vis", "ku rama"): short first word, second not a name on its own
    if i + 1 < len(words) and len(words[i]) <= 4:
        two = _best(" ".join(words[i:i + 2]), options)
        if two <= _best(words[i + 1], options):
            two = 0.0
    if two >= ratio and two > one:
        return 2
    return 1 if one >= ratio else 0


@dataclass
class WakeHit:
    command: str  # words after the wake phrase ("" = just the wake phrase)
    heard: str


LEAD_FILLERS = {"uh", "um", "umm", "so", "oh", "ok", "okay", "and", "hmm", "hm", "ah", "arey", "are"}


def _tokens(text: str) -> tuple[list[str], list[str], list[int]]:
    """Original tokens, normalized words, and the token index each word came from."""
    toks = (text or "").split()
    words: list[str] = []
    owner: list[int] = []
    for ti, tok in enumerate(toks):
        for piece in normalize(tok).split():
            words.append(piece)
            owner.append(ti)
    return toks, words, owner


def _rest(toks: list[str], owner: list[int], k: int) -> str:
    """Original text from normalized word k on (keeps "what's", punctuation, casing)."""
    if k >= len(owner):
        return ""
    ti = owner[k] + (1 if k > 0 and owner[k] == owner[k - 1] else 0)
    return " ".join(toks[ti:]).strip(" ,.!?;:-")


def match_wake(text: str, name_alone: bool | None = None) -> WakeHit | None:
    """Fuzzy wake-phrase match. Accepts "hey/hi/hello/ok <name> [command]", "<real name> [command]"
    and (name_alone) the name or a mishearing of it said on its own."""
    name_alone = config.WAKE_NAME_ALONE if name_alone is None else name_alone
    toks, w, owner = _tokens(text)
    if not w:
        return None
    for start in range(min(2, len(w))):
        if start == 1 and w[0] not in LEAD_FILLERS:  # only "uh hey jarvis", "so jarvis ..."
            break
        if _is_greet(w[start]):
            n = _name_at(w, start + 1)
            if n:
                return WakeHit(_rest(toks, owner, start + 1 + n), text)
        if name_alone:
            n = _name_at(w, start, CANON, 0.85)  # only the real name may lead a command
            if n:
                return WakeHit(_rest(toks, owner, start + n), text)
    if name_alone and len(w) <= 2:
        n = _name_at(w, 0)
        if n == len(w):
            return WakeHit("", text)
    return None


def _core(text: str) -> tuple[str, bool]:
    """Text without assistant names and filler words, and whether a name was present."""
    w = normalize(text).split()
    named = False
    out: list[str] = []
    i = 0
    while i < len(w):
        n = _name_at(w, i)
        if n and (w[i] not in FILLERS):
            named, i = True, i + n
            continue
        if w[i] not in FILLERS:
            out.append(w[i])
        i += 1
    return " ".join(out), named


def _is(core: str, phrases: tuple[str, ...], ratio: float = 0.85) -> bool:
    return bool(core) and (core in phrases or max(_sim(core, p) for p in phrases) >= ratio)


def classify(text: str) -> str | None:
    """'sleep' | 'exit' | 'stop' | None for an utterance heard while awake (checked before the agent)."""
    core, named = _core(text)
    if _is(core, SLEEP_PHRASES):
        return "sleep"
    if named and _is(core, EXIT_PHRASES):  # "shut down" alone means the computer, not Jarvis
        return "exit"
    if _is(core, STOP_PHRASES, 0.9):
        return "stop"
    return None


def strip_wake(text: str) -> str:
    """'hey jarvis open youtube' -> 'open youtube' (used while awake); other text unchanged."""
    hit = match_wake(text, name_alone=False)
    return hit.command if hit and hit.command else text


# --- rate guard ---
class RateGuard:
    """At most per_min recognitions in any 60 s window."""

    def __init__(self, per_min: int | None = None, clock: Callable[[], float] = time.monotonic):
        self.per_min = config.WAKE_MAX_CHECKS_PER_MIN if per_min is None else per_min
        self.clock = clock
        self._t: collections.deque[float] = collections.deque()

    def allow(self) -> bool:
        now = self.clock()
        while self._t and now - self._t[0] >= 60.0:
            self._t.popleft()
        if len(self._t) >= self.per_min:
            return False
        self._t.append(now)
        return True


# --- burst detection (pure logic, synthetic frames in tests) ---
@dataclass
class Burst:
    pcm: bytes
    dur_s: float


class BurstDetector:
    """push() 30 ms frames; returns a Burst when a speech burst of an accepted length ends."""

    def __init__(self, vad=None, sample_rate: int | None = None, frame_ms: int | None = None,
                 min_s: float | None = None, max_s: float | None = None, gap_ms: int | None = None,
                 min_rms: float | None = None, preroll: int = 8):
        self.vad = vad
        self.sr = sample_rate or config.AUDIO_SAMPLE_RATE
        self.fms = frame_ms or config.VAD_FRAME_MS
        self.min_s = config.WAKE_BURST_MIN_S if min_s is None else min_s
        self.max_s = (config.WAKE_LONG_MAX_S if config.WAKE_LONG_BURSTS else config.WAKE_BURST_MAX_S) \
            if max_s is None else max_s
        self.gap = max(1, (config.WAKE_GAP_MS if gap_ms is None else gap_ms) // self.fms)
        self.min_rms = config.VAD_MIN_RMS if min_rms is None else min_rms
        self._ambient: collections.deque[float] = collections.deque(maxlen=100)
        self.noise_floor: float | None = None
        self._pre: collections.deque[tuple[bytes, bool]] = collections.deque(maxlen=preroll)
        self.rejected: str | None = None  # why the last burst was dropped (tests / debug)
        self.reset()

    def reset(self) -> None:
        self._pre.clear()
        self._frames: list[bytes] = []
        self._in = False
        self._overflow = False
        self._first = self._last = 0
        self._quiet = 0

    def is_speech(self, frame: bytes) -> bool:
        level = audio.rms(frame)
        if not self._in:  # learn the room floor only between bursts
            self._ambient.append(level)
            if len(self._ambient) >= 5:
                lv = sorted(self._ambient)
                self.noise_floor = min(lv[len(lv) // 5], config.VAD_FLOOR_CAP)
        gate = max(self.min_rms, (self.noise_floor or 0.0) * config.VAD_NOISE_RATIO)
        if level < gate:
            return False  # cheap path: webrtcvad only runs on loud frames
        if self.vad is None:
            self.vad = audio.make_vad()
        return bool(self.vad.is_speech(frame, self.sr))

    def push(self, frame: bytes) -> Burst | None:
        speech = self.is_speech(frame)
        if not self._in:
            self._pre.append((frame, speech))
            flags = [s for _, s in list(self._pre)[-5:]]
            if sum(flags) >= 3:
                self._in, self._overflow, self._quiet = True, False, 0
                self._frames = [f for f, _ in self._pre]
                flags_all = [s for _, s in self._pre]
                self._first = flags_all.index(True)
                self._last = len(flags_all) - 1 - flags_all[::-1].index(True)
                self._pre.clear()
            return None
        self._frames.append(frame)
        if speech:
            self._last, self._quiet = len(self._frames) - 1, 0
        else:
            self._quiet += 1
        dur = (self._last - self._first + 1) * self.fms / 1000
        if dur > self.max_s:
            self._overflow = True  # too long (TV, conversation): drop it and wait for quiet
        if self._quiet < self.gap:
            if self._overflow:
                self._frames = self._frames[-1:]
                self._first = self._last = 0
            return None
        overflow, frames = self._overflow, self._frames[:self._last + 3]
        self.reset()
        if overflow:
            self.rejected = "long"
            return None
        if dur < self.min_s:
            self.rejected = "short"
            return None
        self.rejected = None
        return Burst(b"".join(frames), dur)


# --- recognition ---
class WakeRecognizer:
    """Burst PCM -> text. Google Web Speech first (WAKE_ENGINE=google), Groq Whisper on failure."""

    def __init__(self, engine: str | None = None, google: Callable[[bytes], str] | None = None,
                 groq: Callable[[bytes], str] | None = None, clock: Callable[[], float] = time.monotonic):
        self.engine = engine or config.WAKE_ENGINE
        self._google_fn = google or self._google
        self._groq_fn = groq or self._groq
        self.clock = clock
        self._google_down_until = 0.0
        self.last_engine = ""

    @staticmethod
    def _google(pcm: bytes) -> str:
        import speech_recognition as sr  # pure Python + bundled flac; no PyAudio needed

        r = sr.Recognizer()
        r.operation_timeout = config.WAKE_GOOGLE_TIMEOUT_S
        data = sr.AudioData(pcm, config.AUDIO_SAMPLE_RATE, 2)
        try:
            return r.recognize_google(data, language=config.WAKE_GOOGLE_LANG) or ""
        except sr.UnknownValueError:
            return ""  # heard nothing intelligible: a valid answer, not a failure

    @staticmethod
    def _groq(pcm: bytes) -> str:
        from jarvis.core import stt

        return stt.transcribe(audio.pcm_to_wav(pcm), language="en").text

    def text(self, pcm: bytes) -> str | None:
        """Recognized text ("" = nothing intelligible) or None if every engine failed."""
        if self.engine == "google" and self.clock() >= self._google_down_until:
            try:
                self.last_engine = "google"
                return self._google_fn(pcm)
            except Exception as e:  # offline, HTTP error, timeout
                log.info("google wake check failed (%s); using groq", e)
                self._google_down_until = self.clock() + config.WAKE_GOOGLE_RETRY_S
        try:
            self.last_engine = "groq"
            return self._groq_fn(pcm)
        except Exception as e:
            log.warning("wake check failed: %s", e)
            return None


@dataclass
class WakeEvent:
    heard: str
    command: str = ""
    lang: str = "en"


def transcribe_command(pcm: bytes) -> tuple[str, str] | None:
    """Accurate multilingual text of a wake+command burst (Groq Whisper): (text, lang)."""
    from jarvis.core import stt

    try:
        tr = stt.transcribe(audio.pcm_to_wav(pcm))
    except stt.STTError as e:
        log.info("command transcription failed: %s", e)
        return None
    return tr.text, tr.lang


class WakeListener:
    """Blocks in listen() until a wake phrase is heard (or stop is set)."""

    def __init__(self, recognizer: WakeRecognizer | None = None, guard: RateGuard | None = None,
                 busy: Callable[[], bool] = lambda: False,
                 command_stt: Callable[[bytes], tuple[str, str] | None] = transcribe_command,
                 stream_factory: Callable | None = None, detector: BurstDetector | None = None):
        self.recognizer = recognizer or WakeRecognizer()
        self.guard = guard or RateGuard()
        self.busy = busy
        self.command_stt = command_stt
        self.stream_factory = stream_factory or audio._input_stream
        self.detector = detector or BurstDetector(min_rms=config.WAKE_MIN_RMS)  # stricter than turn VAD: fewer noise checks
        self.checks = 0
        self.skipped = 0

    def check(self, burst: Burst) -> WakeEvent | None:
        """Recognize one burst (rate-guarded) and match the wake phrase."""
        if self.busy():
            return None
        if not self.guard.allow():
            self.skipped += 1
            return None
        self.checks += 1
        pcm = burst.pcm
        long = burst.dur_s > config.WAKE_BURST_MAX_S
        if long:  # only the head is checked; the full burst goes to Whisper if it wakes us
            pcm = pcm[:int(config.WAKE_LONG_HEAD_S * config.AUDIO_SAMPLE_RATE) * 2]
        heard = self.recognizer.text(pcm)
        if config.WAKE_DEBUG:
            print(f"[wake check {self.recognizer.last_engine}: {heard!r} {burst.dur_s:.1f}s]", flush=True)
        if not heard:
            return None
        hit = match_wake(heard)
        if hit is None:
            return None
        if not (hit.command or long):
            return WakeEvent(heard)
        full = self.command_stt(burst.pcm)  # Whisper: accurate, and Nepali/Hindi commands too
        if full and full[0]:
            text, lang = full
            again = match_wake(text)
            cmd = again.command if again else _strip_lead(text)
            return WakeEvent(heard, cmd, lang)
        return WakeEvent(heard, hit.command)

    def listen(self, stop: threading.Event, idle: Callable[[], bool] | None = None) -> WakeEvent | None:
        frames: queue.Queue[bytes] = queue.Queue(maxsize=400)
        need = audio.frame_bytes()

        def cb(indata, n, t, status):  # PortAudio thread: only enqueue
            try:
                frames.put_nowait(bytes(indata))
            except queue.Full:
                pass

        self.detector.reset()
        with self.stream_factory(cb, config.AUDIO_SAMPLE_RATE, config.VAD_FRAME_MS):
            last_idle = time.monotonic()
            while not stop.is_set():
                if idle and time.monotonic() - last_idle >= 1.0:
                    last_idle = time.monotonic()
                    if idle():  # spoke a job/alert announcement: drop the echo it left in the mic
                        _drain(frames)
                        self.detector.reset()
                try:
                    f = frames.get(timeout=0.2)
                except queue.Empty:
                    continue
                if len(f) != need:
                    continue
                if self.busy():
                    self.detector.reset()
                    continue
                burst = self.detector.push(f)
                if burst is None:
                    continue
                ev = self.check(burst)
                if ev is not None:
                    return ev
        return None


def _drain(q: queue.Queue) -> None:
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            return


def _strip_lead(text: str) -> str:
    """Drop leading greet/name words Whisper kept or misspelled ("Hey, Jarvis. What time...")."""
    words = text.split()
    i = 0
    while i < len(words) and i < 3:
        w = normalize(words[i])
        if w and (_is_greet(w) or _name_at([w], 0)):
            i += 1
        else:
            break
    return " ".join(words[i:]).strip(" ,.!?")


# --- "stop" while speaking ---
class StopWatcher:
    """While Jarvis speaks (wake mode), a short loud burst recognized as "stop" calls on_stop().
    Long bursts (Jarvis's own voice leaking from the speakers) are ignored by length."""

    def __init__(self, on_stop: Callable[[], None], recognizer: WakeRecognizer,
                 guard: RateGuard | None = None, stream_factory: Callable | None = None):
        self.on_stop = on_stop
        self.recognizer = recognizer
        self.guard = guard or RateGuard()
        self.stream_factory = stream_factory or audio._input_stream
        self.triggered = False
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None

    def check(self, burst: Burst) -> bool:
        if not self.guard.allow():
            return False
        heard = self.recognizer.text(burst.pcm) or ""
        if classify(heard) == "stop":
            self.triggered = True
            self.on_stop()
            return True
        return False

    def start(self) -> "StopWatcher":
        self._thread = threading.Thread(target=self._run, name="stop-watch", daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        frames: queue.Queue[bytes] = queue.Queue(maxsize=200)
        det = BurstDetector(min_s=0.2, max_s=1.2, min_rms=config.WAKE_STOP_RMS)
        need = audio.frame_bytes()

        def cb(indata, n, t, status):
            try:
                frames.put_nowait(bytes(indata))
            except queue.Full:
                pass

        try:
            with self.stream_factory(cb, config.AUDIO_SAMPLE_RATE, config.VAD_FRAME_MS):
                while not self._halt.is_set():
                    try:
                        f = frames.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if len(f) == need:
                        b = det.push(f)
                        if b is not None and self.check(b):
                            return
        except Exception as e:
            log.info("stop watcher off: %s", e)

    def stop(self) -> None:
        self._halt.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)


# --- wake acknowledgement ---
_BEEP: Path | None = None


def beep_wav() -> bytes:
    """A soft 120 ms two-tone chime (numpy, 16 kHz WAV)."""
    import numpy as np

    sr = config.AUDIO_SAMPLE_RATE
    t = np.arange(int(sr * 0.06)) / sr
    tone = np.concatenate([np.sin(2 * np.pi * 660 * t), np.sin(2 * np.pi * 880 * t)])
    env = np.minimum(1.0, np.minimum(np.arange(tone.size), tone.size - np.arange(tone.size)) / (sr * 0.01))
    pcm = (tone * env * 0.25 * 32767).astype(np.int16).tobytes()
    return audio.pcm_to_wav(pcm, sr)


def beep() -> None:
    """Play the chime without blocking (paplay starts fastest; ffplay as fallback)."""
    global _BEEP
    try:
        if _BEEP is None or not _BEEP.exists():
            p = Path(tempfile.gettempdir()) / "jarvis_wake_beep.wav"
            p.write_bytes(beep_wav())
            _BEEP = p
        for name in ("paplay", "ffplay"):
            if shutil.which(name):
                subprocess.Popen(audio.player_cmd(str(_BEEP), name=name), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
    except Exception as e:  # never let the chime break waking up
        log.info("beep failed: %s", e)


ACK_TEXT = {"ne": "हजुर?", "hi": "जी?", "en": "Yes?"}
