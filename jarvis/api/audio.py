"""Audio helpers for the API: browser recordings -> 16 kHz wav (STT), and text -> streamed mp3 (TTS).

TTS reuses jarvis.core.tts: the same sentence splitter, speech cleaner, voices and the edge-tts
pipeline (warm pooled sockets, next sentence prefetched while the previous one streams). Instead of
playing on the laptop speakers, the mp3 chunks are streamed to the HTTP client so the BROWSER plays
them (which also lets the browser's echo cancellation hear them).
"""
from __future__ import annotations

import io
import queue
import subprocess
import threading
import wave
from typing import Iterator

from jarvis.api.settings import Settings


def is_wav16k_mono(data: bytes) -> bool:
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return False
    try:
        with wave.open(io.BytesIO(data)) as w:
            return w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2
    except Exception:
        return False


def to_wav16k(data: bytes, settings: Settings) -> bytes:
    """Any browser recording (webm/ogg/wav) -> 16 kHz mono 16-bit wav via ffmpeg (skipped if already)."""
    if is_wav16k_mono(data):
        return data
    proc = subprocess.run([settings.ffmpeg, "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                           "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", "-f", "wav", "pipe:1"],
                          input=data, capture_output=True, timeout=settings.ffmpeg_timeout_s, check=False)
    if proc.returncode != 0 or len(proc.stdout) < 44:
        raise ValueError(f"ffmpeg could not decode the audio: {proc.stderr.decode(errors='replace')[:200]}")
    return proc.stdout


class TTSStream:
    """Sentence-chunked edge-tts synthesis feeding a thread-safe queue of mp3 chunks."""

    def __init__(self, text: str, lang: str | None) -> None:
        from jarvis.core import tts

        self._done = tts._DONE
        self.voice = tts.voice_for(lang)
        self.audio: queue.Queue = queue.Queue()
        self.stop = threading.Event()
        sentences: queue.Queue = queue.Queue()
        for s in tts.split_sentences(text):
            for part in tts.voice_parts(s, lang):  # Devanagari pieces get the Nepali/Hindi voice
                sentences.put(part)
        sentences.put(self._done)
        # Speaker with a no-op player: only its synth pipeline is used (nothing plays on the laptop)
        self.speaker = tts.Speaker(synth=tts.edge_synth, player_factory=lambda *a, **k: None)
        self.thread = threading.Thread(target=self.speaker._synth_loop,
                                       args=(self.voice, sentences, self.audio, self.stop),
                                       name="api-tts", daemon=True)
        self.thread.start()

    @property
    def error(self) -> Exception | None:
        return self.speaker.error

    def next_chunk(self, timeout: float = 30.0) -> bytes | None:
        """Next mp3 chunk, or None when finished (or stalled for `timeout`)."""
        try:
            c = self.audio.get(timeout=timeout)
        except queue.Empty:
            self.stop.set()
            return None
        return None if c is self._done else c

    def iterate(self, first: bytes) -> Iterator[bytes]:
        try:
            yield first
            while (c := self.next_chunk()) is not None:
                yield c
        finally:
            self.stop.set()
