"""Voice loop: `python -m jarvis --voice`.

hotkey (toggle, default Ctrl+Alt+J) or Enter -> record with VAD -> Groq Whisper STT ->
llm.chat stream (fast tier, short voice prompt) -> sentence-streamed edge-tts -> barge-in.
Talking over Jarvis (or pressing the hotkey) stops playback and starts listening again.
"""
from __future__ import annotations

import argparse
import sys
import threading
from collections import deque
from typing import Iterable, Iterator

from jarvis.core import audio, config, hotkey, llm, store, stt, tts

LANG_NAMES = {"en": "English", "ne": "Nepali (Devanagari script)", "hi": "Hindi (Devanagari script)"}

VOICE_PROMPT = (
    "You are Jarvis, a friendly voice assistant on the user's Ubuntu laptop. "
    "Your reply is spoken aloud: answer in 1 to 2 short sentences, plain text only, "
    "no markdown, lists, code or emojis. If unsure, say so briefly. "
    "The user spoke {lang}; reply in {lang}."
)
QUIT = {"q", "quit", "exit", "/q", "/quit", "/exit"}


class VoiceLoop:
    def __init__(self, use_hotkey: bool = True, barge_in: bool | None = None):
        self.use_hotkey = use_hotkey
        self.barge_in = config.BARGE_IN if barge_in is None else barge_in
        self.speaker = tts.Speaker()
        tts.warm()
        self.history: deque[dict] = deque(maxlen=config.HISTORY_TURNS * 2)
        self.state = "idle"  # idle | listening | thinking | speaking
        self.trigger = threading.Event()  # start listening
        self.cancel = threading.Event()  # end the current recording now
        self.quit = threading.Event()
        self._hk: hotkey.HotkeyListener | None = None

    # --- input events (hotkey thread / stdin thread) ---
    def press(self) -> None:
        if self.state == "listening":
            self.cancel.set()
        elif self.state == "speaking":
            self.speaker.stop()
            self.trigger.set()
        else:
            self.trigger.set()

    def _stdin_reader(self) -> None:
        for line in sys.stdin:
            if line.strip().lower() in QUIT:
                break
            self.press()
        self.quit.set()
        self.trigger.set()

    # --- one turn ---
    def _printing(self, deltas: Iterable[str], parts: list[str]) -> Iterator[str]:
        print("jarvis> ", end="", flush=True)
        for d in deltas:
            parts.append(d)
            print(d, end="", flush=True)
            yield d

    def turn(self) -> bool:
        """Listen, answer, speak. Returns True if the user barged in (listen again at once)."""
        self.cancel.clear()
        self.state = "listening"
        print("[listening...]", flush=True)
        try:
            wav = audio.record(stop_event=self.cancel,
                               on_speech_start=lambda: print("[speech]", flush=True))
        finally:
            self.state = "thinking"
        if not wav:
            print("[nothing heard]")
            return False
        try:
            tr = stt.transcribe(wav)
        except stt.STTError as e:
            print(f"[stt error] {e}")
            return False
        if not tr.text:
            print("[nothing heard]")
            return False
        print(f"you({tr.lang})> {tr.text}   [stt {tr.latency_ms} ms, {tr.model}]")
        sys_prompt = VOICE_PROMPT.format(lang=LANG_NAMES.get(tr.lang, "English"))
        msgs = [{"role": "system", "content": sys_prompt}, *self.history,
                {"role": "user", "content": tr.text}]
        parts: list[str] = []
        self.state = "speaking"
        monitor = audio.BargeInMonitor(on_speech=self.speaker.stop) if self.barge_in else None
        try:
            gen = llm.chat(msgs, tier="fast", stream=True, purpose="voice_chat",
                           max_tokens=config.VOICE_MAX_TOKENS)
            if monitor:
                monitor.start()
            self.speaker.speak_stream(self._printing(gen, parts), lang=tr.lang)
        except llm.LLMError as e:
            print(f"[llm error] {e}")
        finally:
            if monitor:
                monitor.stop()
            self.state = "idle"
        barged = bool(monitor and monitor.triggered)
        print(" [interrupted]" if barged else "")
        if self.speaker.error:
            print(f"[tts] {self.speaker.error}")
        if self.speaker.first_audio_s is not None:
            print(f"[first audio {self.speaker.first_audio_s:.2f}s]")
        reply = "".join(parts).strip()
        self.history.append({"role": "user", "content": tr.text})
        self.history.append({"role": "assistant", "content": reply})
        try:
            store.add_message("user", tr.text)
            store.add_message("assistant", reply)
        except Exception:
            pass
        return barged

    # --- main loop ---
    def run(self) -> int:
        key = None
        if self.use_hotkey:
            try:
                self._hk = hotkey.HotkeyListener(config.HOTKEY_PTT, self.press).start()
                key = hotkey.pretty(config.HOTKEY_PTT)
            except hotkey.HotkeyError as e:
                print(f"[hotkey unavailable: {e}] falling back to Enter")
        if sys.stdin.isatty():
            threading.Thread(target=self._stdin_reader, name="stdin", daemon=True).start()
        how = f"press {key} (or Enter)" if key else "press Enter"
        print(f"Jarvis voice ({config.LLM_FAST}). {how} to talk; talk over Jarvis to interrupt; "
              f"q + Enter or Ctrl+C to quit.")
        again = False
        try:
            while not self.quit.is_set():
                if not again:
                    while not self.trigger.wait(0.5):
                        pass
                    if self.quit.is_set():
                        break
                self.trigger.clear()
                try:
                    again = self.turn()
                except audio.AudioError as e:
                    print(f"[audio error] {e}")
                    again = False
                if self.trigger.is_set():  # hotkey pressed during the reply
                    again = True
        except KeyboardInterrupt:
            print()
        finally:
            self.speaker.stop()
            if self._hk:
                self._hk.stop()
        return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m jarvis --voice")
    ap.add_argument("--voice", action="store_true")
    ap.add_argument("--no-hotkey", action="store_true", help="use Enter instead of the global hotkey")
    ap.add_argument("--no-barge-in", action="store_true", help="do not watch the mic while speaking")
    a = ap.parse_args(argv)
    if not config.GROQ_API_KEY:
        print("GROQ_API_KEY missing: add it to .env", file=sys.stderr)
        return 1
    return VoiceLoop(use_hotkey=not a.no_hotkey, barge_in=False if a.no_barge_in else None).run()


if __name__ == "__main__":
    raise SystemExit(main())
