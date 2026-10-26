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
STOP = re.compile(r"^\W*(?:please\s+|ok(?:ay)?\s+|kurama\W+)?(?:(?:stop|end|finish|cancel|exit|close|disable|turn\s+off|switch\s+off)"
                  r"(?:\W+\w+){0,2}|stop\w*|dictation\s+(?:off|stop)|speech\s+to\s+text\s+off)\W*$|"
                  r"^\W*(?:रोक|रोक्नुहोस्|बन्द\s*गर|बन्द\s*गर्नुहोस्|पुग्यो|बंद\s*करो|रुको|बस)\W*$", re.I)
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
COMMANDS["Return"] += ("नयाँ लाइन", "अर्को लाइन", "लाइन बदल", "इन्टर", "नई लाइन", "अगली लाइन", "लाइन बदलो")
COMMANDS["Return Return"] += ("नयाँ अनुच्छेद", "अर्को अनुच्छेद", "नया पैराग्राफ", "नयाँ प्याराग्राफ")
COMMANDS["space"] += ("स्पेस", "खाली ठाउँ")
COMMANDS["ctrl+z"] += ("अनडु", "पछाडि फर्क")
_CMD_PHRASE = {ph: k for k, phs in COMMANDS.items() for ph in phs}
_INLINE = sorted((ph for ph in _CMD_PHRASE if " " in ph and ph not in ("go down", "save it", "undo that")),
                 key=len, reverse=True)
# Whisper is told these words exist, so "change line" stops coming back as "align tinge"
VOCAB = "Okay, new line, change the line, new paragraph, press enter, tab key, give space, stop dictation."
VOCAB_NE = "नमस्ते। यो नेपाली लेखाइ हो। नयाँ लाइन। अर्को अनुच्छेद। स्पेस। रोक।"
VOCAB_HI = "नमस्ते। यह हिंदी लेखन है। नई लाइन। अगला पैराग्राफ। स्पेस। रुको।"
_VOCAB_WORDS = set(re.sub(r"[^\w\s]", " ", VOCAB.lower()).split()) | {"dictation", "press", "line", "enter"}


def command_for(phrase: str) -> str | None:
    """xdotool key(s) for a phrase that is only a command, else None."""
    t = re.sub(r"[^\w\s\u0900-\u097F]", " ", phrase.lower())
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
            _type(before + " ")
            _state["typed"] += len(before.split())
        cmd = " ".join(m.group(1).lower().split())
        if cmd.startswith(("stop", "end", "finish")):
            return False
        uiagent.key(_CMD_PHRASE.get(cmd, "Return"))
        pos = m.end()
    rest = t[pos:].strip()
    if rest:
        _type(rest + " ")
        _state["typed"] += len(rest.split())
    return True


def is_noise(text: str, raw_lang: str) -> bool:
    """Prompt echoes ('Dictation.', 'Press.'), Whisper's silence phrases, and short bits in a language the user
    doesn't speak (room talk / TV) are not dictation."""
    from jarvis.core import stt
    words = re.sub(r"[^\w\s\u0900-\u097F]", " ", text.lower()).split()
    if not words or stt.is_hallucination(text):
        return True
    if command_for(text) or STOP.match(text):
        return False
    if set(words) <= _VOCAB_WORDS:
        return True
    return raw_lang.strip().lower() not in stt.LANG_MAP and len(words) < 5


def _front_is_kurama() -> bool:
    try:
        from jarvis.core import rewrite
        wid, in_front = rewrite.target_window()
        return not in_front  # the front window is KURAMA's own
    except Exception:  # noqa: BLE001
        return False


def _type(text: str) -> None:
    from jarvis.core import uiagent
    if text.isascii():
        uiagent.type_text(text)
        return
    from jarvis.core import rewrite  # Nepali/Hindi: paste (xdotool can't type every Devanagari sign reliably)
    old = rewrite._xclip(["-selection", "clipboard"])
    rewrite._xclip(["-selection", "clipboard"], text)
    term = uiagent.family(uiagent.active_class()) == "terminal"
    uiagent.key("ctrl+shift+v" if term else "ctrl+v")
    time.sleep(0.2)
    if old:
        rewrite._xclip(["-selection", "clipboard"], old)


def _stt_loop(q: "queue.Queue[bytes | None]") -> None:
    from jarvis.core import audio, stt
    lang = _state["lang"]
    # this thread only: bias Whisper toward the editing commands, in the dictation language and script
    # (an English prompt made Nepali come back romanized: "Namaste as a moussom ramroosa")
    stt.set_thread_prompt({"ne": VOCAB_NE, "hi": VOCAB_HI}.get(lang or "", VOCAB))
    models = [config.STT_MODEL, config.STT_FALLBACK]
    if lang in config.STT_PREFER_FALLBACK_LANGS:
        models.reverse()  # large-v3 is much better than turbo at Nepali
    while True:
        pcm = q.get()
        if pcm is None:
            return
        try:  # ONE fast Whisper call per phrase (not the dual Nepali pass of voice chat): less lag, fewer requests
            tr = stt._one(audio.pcm_to_wav(pcm, RATE), lang, models)
        except Exception as e:  # noqa: BLE001 - one failed phrase must not end dictation
            log.warning("dictation STT failed: %s", e)
            continue
        text = (getattr(tr, "text", "") or "").strip()
        if is_noise(text, getattr(tr, "raw_lang", "") or (lang or "english")):
            continue
        if STOP.match(text):
            _state["stop"].set()
            return
        if _front_is_kurama() and not command_for(text):
            continue  # never type into KURAMA's own window (that's how chat got flooded)
        if not handle_text(text):
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
                    if len(voiced) * FRAME_MS >= 600:  # shorter = a cough/click, not words
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
