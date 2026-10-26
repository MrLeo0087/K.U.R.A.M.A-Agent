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
# Spoken editing commands. A whole short phrase is matched (exact, then fuzzy for mishearings like "please enter");
# the clearly multi-word ones also work inside a longer sentence ("... thanks. new line. see you").
COMMANDS: dict[str, tuple[str, ...]] = {
    "Return": ("new line", "next line", "change line", "change the line", "line change", "line break", "break line",
               "break the line", "enter", "press enter", "hit enter", "go to next line", "go down", "new row"),
    "Return Return": ("new paragraph", "next paragraph", "change paragraph", "change the paragraph", "paragraph",
                      "paragraph change", "give a gap", "give gap", "leave a gap", "leave a line", "gap", "blank line",
                      "empty line", "give a line"),
    "space": ("space", "press space", "give space", "give a space", "add space", "add a space", "space bar"),
    "Tab": ("tab", "press tab", "give tab", "give a tab", "indent", "tab key", "press the tab key", "tab button"),
    "BackSpace": ("backspace", "back space", "press backspace", "delete letter"),
    "ctrl+BackSpace": ("delete that word", "delete last word", "remove last word", "delete the word"),
    "ctrl+z": ("undo", "undo that", "press undo"),
    "ctrl+s": ("save", "save it", "save the file", "press save"),
}
_CMD_PHRASE = {ph: k for k, phs in COMMANDS.items() for ph in phs}
_INLINE = sorted((ph for ph in _CMD_PHRASE if " " in ph and ph not in ("go down", "save it", "undo that")),
                 key=len, reverse=True)
# Whisper is told these words exist, so "change line" stops coming back as "align tinge"
VOCAB = ("Dictation. New line. Next line. Change line. New paragraph. Change the paragraph. Press enter. Press tab. "
         "Tab key. Give space. Backspace. Undo. Stop dictation.")


def command_for(phrase: str) -> str | None:
    """xdotool key(s) for a phrase that is only a command, else None."""
    t = re.sub(r"[^\w\s]", " ", phrase.lower())
    t = re.sub(r"^(?:please|okay|ok|and|now|then)\s+|\s+(?:please|now)$", "", " ".join(t.split())).strip()
    if not t or len(t.split()) > 5:
        return None
    if t in _CMD_PHRASE:
        return _CMD_PHRASE[t]
    import difflib
    best = difflib.get_close_matches(t, list(_CMD_PHRASE), n=1, cutoff=0.78)
    return _CMD_PHRASE[best[0]] if best else None


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


_CMD = re.compile(r"\s*\b(" + "|".join(re.escape(p).replace(r"\ ", r"\s+") for p in _INLINE) +
                  r"|(?:stop|end|finish)\s+(?:the\s+)?(?:dictation|typing))\b[\s,.!]*", re.I)


def handle_text(text: str) -> bool:
    """Type one recognised phrase. A phrase that is only a command ('new line', 'press enter', 'give space', 'tab',
    'undo', 'stop dictation') presses keys instead; multi-word commands inside a sentence work too. Returns False
    when dictation should stop (anything said before the stop command is still typed)."""
    from jarvis.core import uiagent
    t = text.strip()
    if not t:
        return True
    if STOP.match(t):
        return False
    if keys := command_for(t):
        uiagent.key(keys)
        return True
    pos = 0
    for m in _CMD.finditer(t):
        before = t[pos:m.start()].strip().rstrip(",")
        if before:
            uiagent.type_text(before + " ")
            _state["typed"] += len(before.split())
        cmd = " ".join(m.group(1).lower().split())
        if cmd.startswith(("stop", "end", "finish")):
            return False
        uiagent.key(_CMD_PHRASE.get(cmd, "Return"))
        pos = m.end()
    rest = t[pos:].strip()
    if rest:
        uiagent.type_text(rest + " ")
        _state["typed"] += len(rest.split())
    return True


def _stt_loop(q: "queue.Queue[bytes | None]") -> None:
    from jarvis.core import audio, stt
    stt.set_thread_prompt(VOCAB)  # this thread only: bias Whisper toward the editing commands
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
