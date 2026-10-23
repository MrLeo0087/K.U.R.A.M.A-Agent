"""Text-to-speech with edge-tts and sentence-level streaming.

speak_stream(deltas, lang) runs three stages in parallel so the first sentence is heard while
the LLM is still writing the rest:
  1. splitter thread  : reads LLM deltas, cuts complete sentences (. ! ? । newline)
  2. synth thread     : edge-tts per sentence, in order, pushes mp3 chunks to a queue
  3. player (worker)  : one ffplay/mpv process fed through stdin, so playback is gapless
stop() interrupts everything at once (barge-in).

CLI: python -m jarvis.core.tts "text" [--lang en|ne|hi] [--out file.mp3]
"""
from __future__ import annotations

import argparse
import asyncio
import queue
import re
import sys
import threading
import time
from typing import AsyncIterator, Callable, Iterable

from jarvis.core import config

_DONE = object()

# Sentence end: . ! ? (needs following whitespace, so 3.14 / e.g.x stay intact), the Devanagari
# danda । (always final), or a newline. Closing quotes/brackets stay with their sentence.
_END = re.compile(r"[.!?]+[\"')\]]*\s+|[।॥]+[\"')\]]*\s*|\n+")
_FENCE = re.compile(r"```.*?```", re.S)
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]+")


def clean_for_speech(text: str) -> str:
    """Strip markdown, code, links and emojis that sound bad when read aloud."""
    text = _FENCE.sub(" (code omitted) ", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!?\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [label](url) -> label
    text = re.sub(r"https?://\S+", "a link", text)
    text = re.sub(r"^\s*#{1,6}\s*", "", text, flags=re.M)  # headings
    text = re.sub(r"^\s*(?:[-*+•]|\d+[.)])\s+", "", text, flags=re.M)  # list bullets/numbers
    text = re.sub(r"[*_~>|#]+", "", text)
    text = _EMOJI.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _alpha(s: str) -> int:
    return sum(c.isalpha() for c in s)


class SentenceSplitter:
    """Incrementally cut streamed text into speakable sentences."""

    def __init__(self) -> None:
        self.buf = ""

    def feed(self, delta: str) -> list[str]:
        self.buf += delta
        if self.buf.count("```") % 2:  # inside an open code block: wait for it to close
            return []
        if "```" in self.buf:
            self.buf = _FENCE.sub(" (code omitted). ", self.buf)
        out: list[str] = []
        start = pos = 0
        while (m := _END.search(self.buf, pos)) is not None:
            pos = m.end()
            cand = self.buf[start:pos].strip()
            # "1." or "-" alone is a list marker, not a sentence: keep accumulating
            if _alpha(cand) >= 2:
                out.append(cand)
                start = pos
        self.buf = self.buf[start:]
        return out

    def flush(self) -> str | None:
        rest, self.buf = self.buf.strip(), ""
        return rest if _alpha(rest) >= 1 else None


def split_sentences(text: str) -> list[str]:
    sp = SentenceSplitter()
    out = sp.feed(text)
    last = sp.flush()
    return out + ([last] if last else [])


def voice_for(lang: str | None) -> str:
    return config.VOICES.get(lang or "", config.VOICES["en_multi"])


async def edge_synth(text: str, voice: str, rate: str | None = None) -> AsyncIterator[bytes]:
    """Stream mp3 chunks for one sentence from edge-tts."""
    import edge_tts

    comm = edge_tts.Communicate(text, voice, rate=rate or config.TTS_RATE)
    async for ev in comm.stream():
        if ev.get("type") == "audio" and ev.get("data"):
            yield ev["data"]


def warm() -> None:
    """Pre-import edge-tts/aiohttp (~0.15 s) so the first reply does not pay for it."""
    import edge_tts  # noqa: F401


Synth = Callable[[str, str], AsyncIterator[bytes]]


class Speaker:
    """Stoppable sentence-streaming speaker. One utterance at a time."""

    def __init__(self, synth: Synth | None = None, player_factory: Callable | None = None):
        self.synth = synth or edge_synth
        if player_factory is None:
            from jarvis.core.audio import Player

            player_factory = Player
        self.player_factory = player_factory
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._player = None
        self._queues: tuple[queue.Queue, queue.Queue] | None = None
        self.first_audio_s: float | None = None  # speak call -> first audio bytes to the player
        self.error: Exception | None = None

    # --- public API ---
    def speak(self, text: str, lang: str = config.TTS_DEFAULT_LANG, block: bool = True) -> None:
        self.speak_stream([text], lang=lang, block=block)

    def speak_stream(self, chunks: Iterable[str], lang: str = config.TTS_DEFAULT_LANG,
                     block: bool = True) -> None:
        self.stop()
        self._stop = threading.Event()
        self.first_audio_s = None
        self.error = None
        self._worker = threading.Thread(target=self._run, args=(chunks, voice_for(lang), self._stop),
                                        name="tts", daemon=True)
        self._worker.start()
        if block:
            self.wait()

    def wait(self, timeout: float | None = None) -> None:
        w = self._worker
        if w and w is not threading.current_thread():
            w.join(timeout)

    def stop(self) -> None:
        """Interrupt immediately: kill the player and drop pending sentences."""
        self._stop.set()
        if self._player is not None:
            self._player.stop()
        if self._queues:
            for q in self._queues:
                q.put(_DONE)
        self.wait(timeout=2)

    @property
    def is_speaking(self) -> bool:
        return bool(self._worker and self._worker.is_alive())

    # --- internals ---
    def _run(self, chunks: Iterable[str], voice: str, stop: threading.Event) -> None:
        t0 = time.monotonic()
        sentences: queue.Queue = queue.Queue()
        audio: queue.Queue = queue.Queue()
        self._queues = (sentences, audio)
        threading.Thread(target=self._split, args=(chunks, sentences, stop), daemon=True).start()
        threading.Thread(target=self._synth_loop, args=(voice, sentences, audio, stop),
                         daemon=True).start()
        player = self.player_factory()
        self._player = player
        try:
            player.start()  # spawn now so player startup overlaps the first synthesis
            while not stop.is_set():
                item = audio.get()
                if item is _DONE or stop.is_set():
                    break
                if self.first_audio_s is None:
                    self.first_audio_s = time.monotonic() - t0
                if not player.write(item):
                    break
        except Exception as e:  # no player, broken pipe...
            self.error = e
            stop.set()
        finally:
            if stop.is_set():
                player.stop()
            player.finish()

    def _split(self, chunks: Iterable[str], out: queue.Queue, stop: threading.Event) -> None:
        sp = SentenceSplitter()
        try:
            for delta in chunks:
                if stop.is_set():
                    break
                for s in sp.feed(delta or ""):
                    out.put(s)
            else:
                last = sp.flush()
                if last:
                    out.put(last)
        except Exception as e:  # LLM stream broke: speak what we have
            self.error = e
            last = sp.flush()
            if last:
                out.put(last)
        finally:
            close = getattr(chunks, "close", None)
            if stop.is_set() and callable(close):
                try:
                    close()  # tell the LLM generator we stopped (logs "aborted")
                except Exception:
                    pass
            out.put(_DONE)

    def _synth_loop(self, voice: str, sentences: queue.Queue, audio: queue.Queue,
                    stop: threading.Event) -> None:
        loop = asyncio.new_event_loop()
        try:
            while not stop.is_set():
                s = sentences.get()
                if s is _DONE:
                    break
                text = clean_for_speech(s)
                if not text:
                    continue
                try:
                    loop.run_until_complete(self._synth_one(text, voice, audio, stop))
                except Exception as e:  # network hiccup: skip this sentence, keep going
                    self.error = e
        finally:
            loop.close()
            audio.put(_DONE)

    async def _synth_one(self, text: str, voice: str, audio: queue.Queue,
                         stop: threading.Event) -> None:
        agen = self.synth(text, voice)
        try:
            async for chunk in agen:
                if stop.is_set():
                    return
                audio.put(chunk)
        finally:
            aclose = getattr(agen, "aclose", None)
            if aclose:
                await aclose()


_default: Speaker | None = None


def default_speaker() -> Speaker:
    global _default
    if _default is None:
        _default = Speaker()
    return _default


def speak_stream(chunks: Iterable[str], lang: str = config.TTS_DEFAULT_LANG, block: bool = True) -> Speaker:
    sp = default_speaker()
    sp.speak_stream(chunks, lang=lang, block=block)
    return sp


def speak(text: str, lang: str = config.TTS_DEFAULT_LANG, block: bool = True) -> Speaker:
    return speak_stream([text], lang=lang, block=block)


def stop() -> None:
    if _default is not None:
        _default.stop()


async def _save(text: str, voice: str, path: str) -> float | None:
    t0, first = time.monotonic(), None
    with open(path, "wb") as f:
        async for chunk in edge_synth(text, voice):
            if first is None:
                first = time.monotonic() - t0
            f.write(chunk)
    return first


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m jarvis.core.tts", description="Speak text with edge-tts")
    ap.add_argument("text", nargs="+")
    ap.add_argument("--lang", default=config.TTS_DEFAULT_LANG, help="en | ne | hi | en_multi")
    ap.add_argument("--out", help="save mp3 to this file instead of playing")
    a = ap.parse_args(argv)
    text = clean_for_speech(" ".join(a.text))
    if a.out:
        first = asyncio.run(_save(text, voice_for(a.lang), a.out))
        print(f"saved {a.out} (first audio after {first or 0:.2f}s)")
        return 0
    sp = Speaker()
    try:
        sp.speak_stream(split_sentences(text), lang=a.lang)
    except KeyboardInterrupt:
        sp.stop()
    if sp.error:
        print(f"[tts error] {sp.error}", file=sys.stderr)
        return 1
    if sp.first_audio_s is not None:
        print(f"first audio after {sp.first_audio_s:.2f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
