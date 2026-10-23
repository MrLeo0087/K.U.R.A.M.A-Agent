"""Speech-to-text on Groq Whisper: STT_MODEL first, STT_FALLBACK on any error.

Auto language detection: verbose_json returns the detected language ("english", "nepali",
"hindi", ...), mapped to the codes Jarvis speaks (en / ne / hi). Each call is logged to the
llm_calls table with purpose="stt" (0 tokens; audio is not token-billed).
"""
from __future__ import annotations

import io
import logging
import re
import time
import wave
from dataclasses import dataclass

from jarvis.core import config, llm, store

log = logging.getLogger(__name__)

# Whisper's language names/codes -> Jarvis language codes. Whisper often labels Nepali speech
# as Marathi or Sanskrit (same Devanagari script), so those map to Nepali; Urdu sounds like
# Hindi when spoken. Anything else falls back to English.
LANG_MAP: dict[str, str] = {
    "english": "en", "en": "en",
    "nepali": "ne", "ne": "ne", "marathi": "ne", "mr": "ne", "sanskrit": "ne", "sa": "ne",
    "hindi": "hi", "hi": "hi", "urdu": "hi", "ur": "hi",
}

# Classic Whisper hallucinations on silence/noise.
_HALLUCINATIONS = {
    "", "you", "thank you", "thank you.", "thanks for watching!", "thanks for watching.",
    "bye.", "bye", ".", "okay.", "uh", "um", "thank you for watching.",
}


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


def transcribe(wav: bytes, language: str | None = None) -> Transcript:
    """Transcribe WAV bytes. language=None means auto-detect."""
    client = llm.get_client()
    last: Exception | None = None
    language = language or config.STT_LANGUAGE_HINT
    models = [config.STT_MODEL, config.STT_FALLBACK]
    if language in config.STT_PREFER_FALLBACK_LANGS:
        models.reverse()  # turbo garbles Nepali; large-v3 with a hint is accurate
    for model in models:
        t0 = time.monotonic()
        kwargs = {"model": model, "file": ("speech.wav", wav), "response_format": "verbose_json",
                  "temperature": 0.0}
        if config.STT_PROMPT:
            kwargs["prompt"] = config.STT_PROMPT
        if language:
            kwargs["language"] = language
        try:
            result = client.audio.transcriptions.create(**kwargs)
        except Exception as e:
            last = e
            ms = int((time.monotonic() - t0) * 1000)
            store.log_llm(model, "stt", 0, 0, ms, False, f"{type(e).__name__}: {e}")
            log.warning("stt %s failed (%s), trying fallback", model, type(e).__name__)
            continue
        ms = int((time.monotonic() - t0) * 1000)
        store.log_llm(model, "stt", 0, 0, ms, True)
        text = result if isinstance(result, str) else (_field(result, "text", "") or "")
        text = text.strip()
        if text.lower() in _HALLUCINATIONS:
            text = ""
        raw = language or _field(result, "language", "") or ""
        dur = _field(result, "duration", None) or wav_duration(wav)
        return Transcript(fix_text(text), map_language(raw), model, raw, float(dur), ms)
    raise STTError(f"all STT models failed ({', '.join(models)}): {last}") from last
