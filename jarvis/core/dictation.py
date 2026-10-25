"""Voice typing in any app: "dictate" -> what you say is typed where the cursor is, until "stop dictation".

The laptop mic is read directly (parec, else arecord: 16 kHz mono PCM, ~2 MB RAM), split into phrases with webrtcvad,
each phrase goes to Groq Whisper (speech-to-text only: no LLM tokens) and is typed with xdotool. Spoken commands:
"new line", "new paragraph", "stop dictation". While dictation runs, talk mode's own copy of the same speech is
ignored (api.turns asks active()). Stops by itself after DICTATION_IDLE_S of silence or DICTATION_MAX_S in total.
"""
from __future__ import annotations

import logging
import queue
import re
import shutil
import subprocess
import threading
import time

from jarvis.core import config

log = logging.getLogger(__name__)
RATE, FRAME_MS = 16000, 30
FRAME_BYTES = RATE * 2 * FRAME_MS // 1000
STOP = re.compile(r"^\W*(?:(?:please\s+)?(?:stop|end|finish|cancel|exit|close)\s+(?:the\s+)?(?:dictation|dictating|typing|voice\s+typing)"
                  r"|dictation\s+(?:off|stop)|stop\s+(?:it|now)|बन्द\s+गर|रोक)\W*$", re.I)
NEWLINE = re.compile(r"^\W*new\s*line\W*$", re.I)
NEWPARA = re.compile(r"^\W*new\s*paragraph\W*$", re.I)

_state: dict = {"thread": None, "stop": threading.Event(), "lang": None, "typed": 0, "since": 0.0}


def active() -> bool:
    t = _state["thread"]
    return bool(t and t.is_alive())


def _recorder() -> subprocess.Popen:
    if shutil.which("parec"):
        argv = ["parec", "--format=s16le", f"--rate={RATE}", "--channels=1", "--raw", "--latency-msec=60"]
    elif shutil.which("arecord"):
        argv = ["arecord", "-q", "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "raw"]
    else:
        raise RuntimeError("no recorder (install pulseaudio-utils or alsa-utils)")
    return subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)


_CMD = re.compile(r"\s*\b(new\s*line|new\s*paragraph|(?:stop|end|finish)\s+(?:the\s+)?(?:dictation|typing))\b[\s,.!]*", re.I)


def handle_text(text: str) -> bool:
    """Type one recognised phrase; 'new line' / 'new paragraph' anywhere in it become line breaks. Returns False
    when the phrase contains the stop command (anything before it is still typed)."""
    from jarvis.core import uiagent
    t = text.strip()
    if not t:
        return True
    if STOP.match(t):
        return False
    pos = 0
    for m in _CMD.finditer(t):
        before = t[pos:m.start()].strip().rstrip(",")
        if before:
            uiagent.type_text(before + " ")
            _state["typed"] += len(before.split())
        cmd = m.group(1).lower()
        if cmd.startswith(("stop", "end", "finish")):
            return False
        uiagent.key("Return Return" if "paragraph" in cmd else "Return")
        pos = m.end()
    rest = t[pos:].strip()
    if rest:
        uiagent.type_text(rest + " ")
        _state["typed"] += len(rest.split())
    return True


def _stt_loop(q: "queue.Queue[bytes | None]") -> None:
    from jarvis.core import audio, stt
    while True:
        pcm = q.get()
        if pcm is None:
            return
        try:
            tr = stt.transcribe(audio.pcm_to_wav(pcm, RATE), _state["lang"])
        except Exception as e:  # noqa: BLE001 - one failed phrase must not end dictation
            log.warning("dictation STT failed: %s", e)
            continue
        if not handle_text(getattr(tr, "text", "") or ""):
            _state["stop"].set()
            return


def _run(delay: float) -> None:
    import webrtcvad
    stop = _state["stop"]
    if stop.wait(delay):
        return
    vad = webrtcvad.Vad(2)
    q: "queue.Queue[bytes | None]" = queue.Queue()
    stt_t = threading.Thread(target=_stt_loop, args=(q,), daemon=True, name="dictation-stt")
    stt_t.start()
    rec = _recorder()
    voiced: list[bytes] = []
    ring: list[bool] = []
    talking, silence_ms, last_voice, t0 = False, 0, time.time(), time.time()
    try:
        while not stop.is_set():
            frame = rec.stdout.read(FRAME_BYTES)  # type: ignore[union-attr]
            if len(frame) < FRAME_BYTES:
                break
            speech = vad.is_speech(frame, RATE)
            ring = (ring + [speech])[-10:]
            if not talking:
                voiced = (voiced + [frame])[-10:]  # keep 300 ms before the start
                if sum(ring) >= 6:
                    talking, silence_ms = True, 0
            else:
                voiced.append(frame)
                silence_ms = 0 if speech else silence_ms + FRAME_MS
                if silence_ms >= config.DICTATION_PAUSE_MS or len(voiced) * FRAME_MS >= 15000:
                    if len(voiced) * FRAME_MS >= 400:
                        q.put(b"".join(voiced))
                    voiced, ring, talking = [], [], False
                    last_voice = time.time()
            now = time.time()
            if (not talking and now - last_voice > config.DICTATION_IDLE_S) or now - t0 > config.DICTATION_MAX_S:
                log.info("dictation auto-stop")
                break
    finally:
        rec.terminate()
        q.put(None)
        stt_t.join(timeout=30)
        stop.set()
        from jarvis.core import notify
        notify.notify("Dictation stopped", f"{_state['typed']} words typed.", level="info", source="dictation",
                      telegram=False, save=False)


def start(lang: str | None = None, delay: float = 3.0) -> str:
    if active():
        return "Dictation is already on. Say 'stop dictation' to end it."
    if not shutil.which("xdotool"):
        return "error: xdotool is missing (sudo apt install xdotool)"
    _state.update(stop=threading.Event(), lang=lang, typed=0, since=time.time())
    th = threading.Thread(target=_run, args=(delay,), daemon=True, name="dictation")
    _state["thread"] = th
    th.start()
    return (f"Dictation starts in {int(delay)} seconds: click where the text should go, then speak"
            f"{' in ' + {'ne': 'Nepali', 'hi': 'Hindi', 'en': 'English'}[lang] if lang else ''}. "
            "Say 'new line' for a line break and 'stop dictation' to finish.")


def stop() -> str:
    if not active():
        return "Dictation isn't on."
    _state["stop"].set()
    return f"Dictation stopped ({_state['typed']} words typed)."
