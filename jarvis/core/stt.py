"""Speech-to-text on Groq Whisper: STT_MODEL first, STT_FALLBACK on any error.

Auto language detection: verbose_json returns the detected language ("english", "nepali",
"hindi", ...), mapped to the codes KURAMA speaks (en / ne / hi). Each call is logged to the
llm_calls table with purpose="stt" (0 tokens; audio is not token-billed).
"""
from __future__ import annotations

import io
import logging
import re
import threading
import time
import wave
from dataclasses import dataclass

from jarvis.core import config, llm, store

log = logging.getLogger(__name__)

# Whisper's language names/codes -> KURAMA language codes. Whisper often labels Nepali speech
# as Marathi or Sanskrit (same Devanagari script), so those map to Nepali; Urdu sounds like
# Hindi when spoken. Anything else falls back to English.
LANG_MAP: dict[str, str] = {
    "english": "en", "en": "en",
    "nepali": "ne", "ne": "ne", "marathi": "ne", "mr": "ne", "sanskrit": "ne", "sa": "ne",
    "hindi": "hi", "hi": "hi", "urdu": "hi", "ur": "hi",
}

# Classic Whisper hallucinations on silence/noise (compared without punctuation/case).
_HALLUCINATIONS = {"", "you", "thank you", "thanks", "bye", "okay", "uh", "um", "hmm"}
_HALLUCINATION_RE = re.compile(r"(?:thanks?(?: you)? (?:so much )?for watching|please subscribe|like and subscribe|"
                               r"subtitles? by|captions? by|amara\.org|see you (?:in the )?next (?:video|time))", re.I)


def is_hallucination(text: str) -> bool:
    """Whisper on silence: stock YouTube phrases, or an echo of our own vocabulary prompt (config.STT_PROMPT,
    e.g. "KURAMA, KURAMA, VS Code, Brave, YouTube, Kathmandu, Pokhara.")."""
    norm = re.sub(r"[^\w\s]", " ", text.lower()).split()
    if " ".join(norm) in _HALLUCINATIONS or _HALLUCINATION_RE.search(text):
        return True
    prompt = re.sub(r"[^\w\s]", " ", (config.STT_PROMPT or "").lower()).split()
    vocab = set(prompt)
    if len(norm) >= 3 and vocab and sum(w in vocab for w in norm) / len(norm) >= 0.8:
        return True
    if len(norm) == 2 and all(w in vocab for w in norm):  # "KURAMA, Pokhara."
        return True
    # "Kurama, VS Code, Brave, YouTube, and ...": 3+ prompt words in the prompt's own order = an echo, not speech
    dedup = [w for i, w in enumerate(norm) if i == 0 or w != norm[i - 1]]
    for i in range(len(dedup)):
        for j in range(len(prompt)):
            k = 0
            while i + k < len(dedup) and j + k < len(prompt) and dedup[i + k] == prompt[j + k]:
                k += 1
            if k >= 3:
                return True
    return False


class STTError(RuntimeError):
    """Every STT model failed."""


@dataclass
class Transcript:
    text: str
    lang: str  # en / ne / hi
    model: str
    raw_lang: str = ""
    duration_s: float = 0.0
    latency_ms: int = 0
    logprob: float | None = None  # mean segment avg_logprob (confidence), when available
    no_speech: float | None = None  # mean segment no_speech_prob, when available

    def __str__(self) -> str:
        return self.text


def map_language(raw: str | None) -> str:
    return LANG_MAP.get((raw or "").strip().lower(), config.TTS_DEFAULT_LANG)


def wav_duration(wav: bytes) -> float:
    try:
        with wave.open(io.BytesIO(wav)) as wf:
            return wf.getnframes() / float(wf.getframerate() or 1)
    except Exception:
        return 0.0


def _field(result, name: str, default=None):
    if isinstance(result, dict):
        return result.get(name, default)
    return getattr(result, name, default)


def fix_text(text: str) -> str:
    """Apply config.STT_FIXES (known mishearings such as "BS code" -> "VS Code")."""
    for pat, rep in config.STT_FIXES.items():
        text = re.sub(pat, rep, text, flags=re.I)
    return text


def _logprob(result) -> float | None:
    segs = _field(result, "segments", None) or []
    vals = [_field(sg, "avg_logprob", None) for sg in segs]
    vals = [float(v) for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _no_speech(result) -> float | None:
    segs = _field(result, "segments", None) or []
    vals = [float(v) for v in (_field(sg, "no_speech_prob", None) for sg in segs) if v is not None]
    return sum(vals) / len(vals) if vals else None


def is_noise(t: "Transcript") -> bool:
    """Background noise that Whisper turned into words: "probably not speech" AND not confident about the words
    (Whisper's own rule). no_speech alone also dropped real, clearly heard requests now and then."""
    if t.no_speech is None or t.no_speech <= config.STT_NO_SPEECH_MAX:
        return False
    return t.logprob is None or t.logprob < config.STT_NOISE_MAX_LOGPROB


_local = threading.local()  # per-thread vocabulary prompt (dictation biases Whisper toward its commands)


def set_thread_prompt(prompt: str | None) -> None:
    _local.prompt = prompt


def _one(wav: bytes, language: str | None, models: list[str]) -> Transcript:
    """One transcription, trying `models` in order (fallback on error)."""
    client = llm.get_client()
    last: Exception | None = None
    for model in models:
        t0 = time.monotonic()
        kwargs = {"model": model, "file": ("speech.wav", wav), "response_format": "verbose_json",
                  "temperature": 0.0}
        prompt = getattr(_local, "prompt", None) or config.STT_PROMPT
        if prompt:
            kwargs["prompt"] = prompt
        if language:
            kwargs["language"] = language
        try:
            try:
                result = client.audio.transcriptions.create(**kwargs)
            except Exception as e:  # free tier: 20 requests/min per model; wait the few seconds it asks for, once
                wait = re.search(r"try again in ([\d.]+)s", str(e)) if type(e).__name__ == "RateLimitError" else None
                if not wait or float(wait.group(1)) > 5:
                    raise
                time.sleep(float(wait.group(1)) + 0.2)
                result = client.audio.transcriptions.create(**kwargs)
        except Exception as e:
            last = e
            ms = int((time.monotonic() - t0) * 1000)
            store.log_llm(model, "stt", 0, 0, ms, False, f"{type(e).__name__}: {e}")
            log.warning("stt %s failed (%s), trying fallback", model, type(e).__name__)
            continue
        ms = int((time.monotonic() - t0) * 1000)
        try:  # audio seconds for the usage report (verbose_json has duration; else from WAV size)
            audio_s = float(_field(result, "duration", None) or max(0, len(wav) - 44) / (2 * config.AUDIO_SAMPLE_RATE))
        except (TypeError, ValueError):
            audio_s = 0.0
        store.log_llm(model, "stt", 0, 0, ms, True, audio_s=audio_s)
        text = result if isinstance(result, str) else (_field(result, "text", "") or "")
        text = text.strip()
        if is_hallucination(text):
            text = ""
        raw = language or _field(result, "language", "") or ""
        dur = _field(result, "duration", None) or wav_duration(wav)
        return Transcript(fix_text(text), map_language(raw), model, raw, float(dur), ms,
                          None if isinstance(result, str) else _logprob(result),
                          None if isinstance(result, str) else _no_speech(result))
    raise STTError(f"all STT models failed ({', '.join(models)}): {last}") from last


# --- language arbitration (Whisper often mislabels Nepali as English/Hindi/Slovak...) ---
_DEVA = re.compile(r"[\u0900-\u097F]")
_LATIN = re.compile(r"[A-Za-z]")
_HI_WORDS = {"है", "हैं", "में", "क्या", "कैसा", "कैसी", "कैसे", "नहीं", "हूँ", "हूं", "था", "थी", "और",
             "कितने", "मुझे", "मेरा", "मेरी", "आप", "अच्छा", "बताओ", "बताइए", "करो", "हुआ", "सकती", "सकते", "सकता"}
_NE_WORDS = {"छ", "छन्", "हो", "मा", "कस्तो", "कति", "भयो", "अहिले", "हुन्छ", "छैन", "मेरो", "मलाई",
             "तपाईं", "तिमी", "बज्यो", "गर", "गर्नु", "गर", "दिनु", "भन", "भन्नु", "खोल", "के"}


def text_lang(text: str) -> str:
    """en / hi / ne from the words themselves (script + common Hindi/Nepali function words)."""
    if len(_DEVA.findall(text)) <= len(_LATIN.findall(text)):
        return "en"
    toks = re.findall(r"[\u0900-\u0963\u0966-\u097F]+", text)  # words, without danda ।॥
    ne = sum(t in _NE_WORDS or (len(t) > 2 and t.endswith("मा")) for t in toks)
    hi = sum(t in _HI_WORDS for t in toks)
    return "hi" if hi > ne else "ne"


def _clean_english(t: Transcript) -> bool:
    """Plausible English: known label, ASCII only, not a choppy word salad, confident enough."""
    txt = t.text
    if t.raw_lang.strip().lower() not in LANG_MAP or t.lang != "en" or not txt:
        return False
    if any(ord(c) > 127 for c in txt):  # "Môže bota okého" etc.
        return False
    words = re.findall(r"[A-Za-z']+", txt)
    if txt.count(",") >= 3 and len(words) <= 2 * txt.count(","):  # "Oly, Japan, Ma, Mousim, Gusto"
        return False
    return t.logprob is None or t.logprob >= config.STT_EN_MIN_LOGPROB


def choose(auto: Transcript, ne: Transcript | None) -> Transcript:
    """Pick between the auto-detect pass and the Nepali-forced pass."""
    if ne is None or not ne.text:
        return auto
    if _clean_english(auto):
        return auto
    if (auto.raw_lang.strip().lower() in LANG_MAP and auto.lang == "hi" and _DEVA.search(auto.text)
            and text_lang(ne.text) == "hi"):
        auto.lang = "hi"
        return auto
    ne.lang = text_lang(ne.text)  # large-v3 + "ne" transcribes ne, hi and en speech correctly
    return ne


def transcribe(wav: bytes, language: str | None = None) -> Transcript:
    """Transcribe WAV bytes. language=None: auto-detect, plus (STT_DUAL) a parallel Nepali-forced
    large-v3 pass so Nepali is not lost to Whisper's language mislabels (no extra latency)."""
    language = language or config.STT_LANGUAGE_HINT
    best_first = [config.STT_MODEL, config.STT_FALLBACK]
    if language:
        models = best_first[::-1] if language in config.STT_PREFER_FALLBACK_LANGS else best_first
        return _one(wav, language, models)
    if not config.STT_DUAL:
        t = _one(wav, None, best_first)
        return _gate(t, t)
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_auto = ex.submit(_one, wav, None, best_first)
        f_ne = ex.submit(_one, wav, "ne", best_first)
        try:
            auto = f_auto.result()
        except STTError:
            return f_ne.result()
        try:
            ne = f_ne.result()
        except STTError:
            ne = None
    if auto.raw_lang.strip().lower() not in LANG_MAP and not (ne and ne.text):
        try:  # Whisper guessed a language we don't speak (Portuguese, Slovak...) on accented English
            en = _one(wav, "en", best_first)
            if en.text:
                return _gate(en, auto)
        except STTError:
            pass
    best = choose(auto, ne)
    best.latency_ms = max(auto.latency_ms, ne.latency_ms if ne else 0)
    return _gate(best, auto)


_OTHER_SCRIPT = re.compile(r"[^\x00-\u024f\u0900-\u097f\u2000-\u206f\u20b9\u0964\u0965\s]")  # not Latin / Devanagari


def not_ours(best: Transcript, auto: Transcript) -> str:
    """Why this transcript is not the owner speaking English / Nepali / Hindi (fan, drill, TV), or ''.
    Only English, Nepali and Hindi are supported: anything else is ignored ('Didn't catch that')."""
    text = best.text.strip()
    if not text:
        return ""
    if _OTHER_SCRIPT.search(text):  # 'Продолжение следует...' (Cyrillic), Tamil, Chinese...
        return "other script"
    lp = best.logprob
    # Whisper's language label is about the AUTO pass: when the text we keep came from a forced English / Nepali
    # pass, that label says nothing about it (stt.log 10-30: 'Namaste, Kurama.', 'Sot down to laptop.', 'Hel Kurama'
    # were real speech labelled Polish / Tamil / Korean and dropped)
    # (real speech there scored -0.62 .. -0.93; Tamil-labelled nonsense -1.24: a forced pass keeps the -1.0 floor)
    floor = config.STT_FOREIGN_MAX_LOGPROB if best is auto else config.STT_GARBAGE_LOGPROB
    if auto.raw_lang.strip().lower() not in LANG_MAP and lp is not None and lp < floor:
        return f"{auto.raw_lang or '?'} at low confidence"  # 'E aí' (Portuguese), Tamil-labelled nonsense
    if lp is not None and lp < config.STT_GARBAGE_LOGPROB and len(text.split()) <= 4:
        return "short and unsure"  # 'The', 'RUN'
    return ""


def _gate(best: Transcript, auto: Transcript) -> Transcript:
    """Noise check on the final pick only (gating each pass threw away the good one)."""
    heard = best.text
    if best.text and is_noise(auto):
        log.info("dropped as noise (no_speech %.2f): %r", auto.no_speech or 0, best.text[:60])
        best.text = ""
    if best.text and (why := not_ours(best, auto)):
        log.info("dropped (%s): %r", why, best.text[:60])
        best.text = ""
    _trail(best, auto, heard)
    if best.text:
        _heard[" ".join(best.text.split()).lower()] = (time.time(), best.logprob, (auto.raw_lang or "").strip().lower())
        while len(_heard) > 30:  # the wake listener transcribes room sound too: keep each recent text's own score
            _heard.pop(next(iter(_heard)))
        _unsure.update(text=" ".join(best.text.split()).lower(), at=time.time(), unsure=bool(
            auto.raw_lang.strip().lower() not in LANG_MAP and best.logprob is not None
            and best.logprob < config.STT_EN_MIN_LOGPROB))
    return best


_unsure: dict = {"text": "", "at": 0.0, "unsure": False}
_heard: dict[str, tuple[float, float | None, str]] = {}  # recent recognitions: text -> (when, confidence, language)


def heard_well(text: str, within_s: float = 180.0) -> bool:
    """Was this a recent recognition, and a sure one (confidence >= FEEDBACK_MIN_LOGPROB, a language we speak)?
    Spoken praise / complaints only count then: noise once came out as 'Okay, go on.' (lp -0.89). A text that
    isn't the last recognition (typed) is True."""
    got = _heard.get(" ".join((text or "").split()).lower())
    if got is None or time.time() - got[0] > within_s:
        return True
    _, lp, lang = got
    return (lp is None or lp >= config.FEEDBACK_MIN_LOGPROB) and (not lang or lang in LANG_MAP)


def unsure(text: str, within_s: float = 120.0) -> bool:
    """This text is the last recognition, and Whisper heard a language we don't speak at low confidence (11-01:
    'Islam Nizib', 'Maximal Zabolom', 'Please, there is still more to eat.' went to the AI). The caller decides by
    meaning whether it is still clear enough to act on."""
    return bool(_unsure["unsure"] and time.time() - _unsure["at"] < within_s
                and " ".join((text or "").split()).lower() == _unsure["text"])


def _trail(best: Transcript, auto: Transcript, heard: str) -> None:
    """One line per recognition in data/logs/stt.log (what was heard, which pass won, confidence, dropped?):
    the evidence when voice recognition seems off. Kept small."""
    try:
        path = config.STT_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 256_000:
            path.write_text("".join(path.read_text(encoding="utf-8").splitlines(True)[-500:]), encoding="utf-8")
        f = lambda v: "-" if v is None else f"{v:.2f}"  # noqa: E731
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%m-%d %H:%M:%S')} {best.duration_s:4.1f}s {best.model[8:]:>14} "
                     f"{auto.raw_lang or '-'}->{best.lang} lp={f(best.logprob)} ns={f(auto.no_speech)} "
                     f"{'DROPPED ' if heard and not best.text else ''}{heard!r}\n")
    except OSError:
        pass
