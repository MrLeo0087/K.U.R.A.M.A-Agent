"""Voice loop: `python -m jarvis --voice`.

hotkey (toggle, default Ctrl+Alt+J) or Enter -> record with VAD -> Groq Whisper STT ->
LangGraph agent stream (router + tools, spoken yes/no confirmations) -> sentence-streamed edge-tts -> barge-in.
Talking over Jarvis (or pressing the hotkey) stops playback and starts listening again.
"""
from __future__ import annotations

import argparse
import sys
import itertools
import threading
import time
from typing import Iterable, Iterator

from jarvis.core import agent, audio, config, greeting, hotkey, jobs, llm, notify, safety, store, stt, tts

LANG_NAMES = agent.LANG_NAMES
QUIT = {"q", "quit", "exit", "/q", "/quit", "/exit"}


class VoiceLoop:
    def __init__(self, use_hotkey: bool = True, barge_in: bool | None = None):
        self.use_hotkey = use_hotkey
        self.barge_in = config.BARGE_IN if barge_in is None else barge_in
        self.speaker = tts.Speaker()
        tts.warm()
        self.state = "idle"  # idle | listening | thinking | speaking
        self.trigger = threading.Event()  # start listening
        self.cancel = threading.Event()  # end the current recording now
        self.quit = threading.Event()
        self._hk: hotkey.HotkeyListener | None = None
        self._greeter: tts.Speaker | None = None  # startup greeting (own speaker, stoppable)
        self.lang = config.TTS_DEFAULT_LANG
        self.agent = agent.Agent(confirm=self.confirm)
        self.agent.warm()  # LangChain/LangGraph setup at startup, not on the first turn
        safety.set_confirm_hook("voice", self.confirm)
        jobs.set_mode("voice")  # finished background jobs are queued and spoken when idle
        self._alert_check = 0.0  # last look at the alerts table (worker alerts are spoken when idle)

    def announce_jobs(self) -> bool:
        """Speak one queued job announcement if Jarvis is idle (not listening/thinking/speaking)."""
        if self.state != "idle" or self.trigger.is_set():
            return False
        item = jobs.ANNOUNCER.pop() or self._pending_alert()
        if item is None:
            return False
        text, lang = item
        self.state = "speaking"
        print(f"jarvis> {text}", flush=True)
        try:
            self.speaker.speak(text, lang=lang or self.lang)
        finally:
            self.state = "idle"
        return True

    def _pending_alert(self) -> tuple[str, str] | None:
        """A background-worker alert (SQLite, written by notify()) to speak; checked every few seconds."""
        now = time.monotonic()
        if now - self._alert_check < config.ALERT_ANNOUNCE_CHECK_S:
            return None
        self._alert_check = now
        line = notify.pop_spoken_alert()
        return (line, "en") if line else None

    # --- spoken confirmation (called from the agent's tool node) ---
    def confirm(self, prompt: str) -> bool:
        """Ask by TTS, record the answer, STT, parse yes/no. Silence or unclear means no."""
        question = f"{prompt} Say yes or no."
        print(f"jarvis> {question}", flush=True)
        try:
            tts.Speaker().speak(question, lang=self.lang)  # own speaker: main stream untouched
            wav = audio.record(max_s=min(6.0, config.CONFIRM_TIMEOUT_S),
                               on_speech_start=lambda: print("[speech]", flush=True))
            if not wav:
                print("[no answer: not doing it]")
                return False
            tr = stt.transcribe(wav)
        except (audio.AudioError, stt.STTError) as e:
            print(f"[confirm failed: {e}]")
            return False
        ok = safety.parse_yes_no(tr.text) is True
        print(f"you({tr.lang})> {tr.text}   [{'yes' if ok else 'no'}]", flush=True)
        return ok

    # --- input events (hotkey thread / stdin thread) ---
    def greet(self, text: str) -> None:
        """Speak the startup greeting unless the user already started talking (greeting thread)."""
        if self.state != "idle" or self.trigger.is_set():
            return
        print(f"jarvis> {text}", flush=True)
        sp = self._greeter = tts.Speaker()
        try:
            sp.speak(text, lang=config.TTS_DEFAULT_LANG)
        finally:
            self._greeter = None

    def press(self) -> None:
        if self._greeter is not None:
            self._greeter.stop()  # the hotkey cuts the greeting short
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
        tts.prewarm()  # open edge-tts sockets while the user talks
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
        self.lang = tr.lang
        parts: list[str] = []
        monitor = audio.BargeInMonitor(on_speech=self.speaker.stop) if self.barge_in else None
        try:
            gen = self.agent.stream(tr.text, mode="voice", lang=tr.lang)
            # Pull the first delta here: routing, tool rounds and spoken confirmations run before
            # TTS playback and the barge-in mic monitor start, so they never fight over the mic.
            first = next(gen, None)
            self.state = "speaking"
            if first is not None:
                if monitor:
                    monitor.start()
                self.speaker.speak_stream(self._printing(itertools.chain([first], gen), parts),
                                          lang=tr.lang)
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
        cut = "talk over Jarvis" if config.BARGE_IN else (f"press {key}" if key else "press Enter")
        print(f"Jarvis voice ({config.LLM_FAST}). {how} to talk; {cut} to interrupt; "
              f"q + Enter or Ctrl+C to quit.")
        greeting.start(self.greet)  # background thread: the hotkey is already live
        again = False
        try:
            while not self.quit.is_set():
                if not again:
                    while not self.trigger.wait(0.5):
                        self.announce_jobs()
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
            jobs.shutdown()
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
