"""Voice loop: `python -m jarvis --voice` (wake word on by default) or `--wake` / `--no-wake`.

hotkey (toggle, default Ctrl+Alt+J) or Enter or "Hey Jarvis" -> record with VAD -> Groq Whisper STT ->
LangGraph agent stream (router + tools, spoken yes/no confirmations) -> sentence-streamed edge-tts.

Wake mode: SLEEPING listens only for "hey/hi/hello/ok Jarvis|Kurama" (core/wake.py: cheap VAD
bursts + free Google speech recognition). AWAKE takes turns without the hotkey until
WAKE_IDLE_S of silence or "sleep Jarvis" / "go to sleep" / "so jao". "stop" while Jarvis speaks
interrupts; "exit Jarvis" quits after a confirmation. The hotkey keeps working alongside.
"""
from __future__ import annotations

import argparse
import sys
import itertools
import threading
import time
from typing import Iterable, Iterator

from jarvis.core import agent, audio, config, greeting, hotkey, jobs, llm, notify, safety, store, stt, tts, wake

LANG_NAMES = agent.LANG_NAMES
QUIT = {"q", "quit", "exit", "/q", "/quit", "/exit"}
SLEEP_REPLY = {"en": "Okay, going to sleep.", "hi": "ठीक है, मैं सो रहा हूँ।", "ne": "हुन्छ, म सुत्छु।"}


class VoiceLoop:
    def __init__(self, use_hotkey: bool = True, barge_in: bool | None = None, wake_mode: bool = False):
        self.use_hotkey = use_hotkey
        self.barge_in = config.BARGE_IN if barge_in is None else barge_in
        self.wake_mode = wake_mode
        self.speaker = tts.Speaker()
        tts.warm()
        self.state = "idle"  # idle | sleeping | listening | thinking | speaking
        self.trigger = threading.Event()  # start listening
        self.cancel = threading.Event()  # end the current recording now
        self.quit = threading.Event()
        self._hk: hotkey.HotkeyListener | None = None
        self._greeter: tts.Speaker | None = None  # startup greeting (own speaker, stoppable)
        self.lang = config.TTS_DEFAULT_LANG
        self.agent = agent.Agent(confirm=self.confirm, channel="voice")
        self.agent.warm()  # LangChain/LangGraph setup at startup, not on the first turn
        safety.set_confirm_hook("voice", self.confirm)
        jobs.set_mode("voice")  # finished background jobs are queued and spoken when idle
        self._alert_check = 0.0  # last look at the alerts table (worker alerts are spoken when idle)
        self._guard = wake.RateGuard()  # shared by the wake listener and the "stop" watcher
        self._recognizer = wake.WakeRecognizer()

    def announce_jobs(self) -> bool:
        """Speak one queued job announcement if Jarvis is idle or asleep (not mid-turn)."""
        if self.state not in ("idle", "sleeping") or self.trigger.is_set():
            return False
        item = jobs.ANNOUNCER.pop() or self._pending_alert()
        if item is None:
            return False
        text, lang = item
        prev, self.state = self.state, "speaking"
        print(f"jarvis> {text}", flush=True)
        try:
            self.speaker.speak(text, lang=lang or self.lang)
        finally:
            self.state = prev
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
        verdict = safety.parse_yes_no(tr.text)
        if verdict is None and not getattr(self, "_reasking", False):
            print(f"you({tr.lang})> {tr.text}   [unclear]", flush=True)
            self._reasking = True
            try:  # ask once more instead of silently treating "unclear" as no
                return self.confirm("Sorry, was that a yes or a no?")
            finally:
                self._reasking = False
        ok = verdict is True
        print(f"you({tr.lang})> {tr.text}   [{'yes' if ok else 'no'}]", flush=True)
        return ok

    # --- input events (hotkey thread / stdin thread) ---
    def greet(self, text: str) -> None:
        """Speak the startup greeting unless the user already started talking (greeting thread)."""
        if self.state not in ("idle", "sleeping") or self.trigger.is_set():
            return
        print(f"jarvis> {text}", flush=True)
        sp = self._greeter = tts.Speaker()
        try:
            sp.speak(text, lang=config.TTS_DEFAULT_LANG)
        finally:
            self._greeter = None

    def _busy_speaking(self) -> bool:
        g = self._greeter
        return self.state == "speaking" or (g is not None and g.is_speaking)

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
        self.cancel.set()  # end a wake-mode recording that may wait up to WAKE_IDLE_S
        self.trigger.set()

    # --- one turn ---
    def _printing(self, deltas: Iterable[str], parts: list[str]) -> Iterator[str]:
        print("jarvis> ", end="", flush=True)
        for d in deltas:
            parts.append(d)
            print(d, end="", flush=True)
            yield d

    def listen(self, start_timeout_s: float | None = None, quiet: bool = False) -> stt.Transcript | None:
        """Record one utterance and transcribe it. None = nothing heard (or STT failed)."""
        self.cancel.clear()
        self.state = "listening"
        if not quiet:
            print("[listening...]", flush=True)
        tts.prewarm()  # open edge-tts sockets while the user talks
        try:
            wav = audio.record(stop_event=self.cancel, start_timeout_s=start_timeout_s,
                               on_speech_start=lambda: print("[speech]", flush=True))
        finally:
            self.state = "thinking"
        if not wav:
            return None
        try:
            tr = stt.transcribe(wav)
        except stt.STTError as e:
            print(f"[stt error] {e}")
            return None
        if not tr.text:
            return None
        print(f"you({tr.lang})> {tr.text}   [stt {tr.latency_ms} ms, {tr.model}]")
        return tr

    def respond(self, text: str, lang: str) -> bool:
        """Run the agent and speak the reply. Returns True if the user interrupted."""
        self.lang = lang
        parts: list[str] = []
        monitor = audio.BargeInMonitor(on_speech=self.speaker.stop) if self.barge_in else None
        watcher = None
        if self.wake_mode and config.WAKE_STOP_WORD and not self.barge_in:
            watcher = wake.StopWatcher(self.speaker.stop, self._recognizer, self._guard)
        try:
            gen = self.agent.stream(text, mode="voice", lang=lang)
            # Pull the first delta here: routing, tool rounds and spoken confirmations run before
            # TTS playback and the mic monitors start, so they never fight over the mic.
            first = next(gen, None)
            self.state = "speaking"
            if first is not None:
                for m in (monitor, watcher):
                    if m:
                        m.start()
                self.speaker.speak_stream(self._printing(itertools.chain([first], gen), parts), lang=lang)
        except llm.LLMError as e:
            print(f"[llm error] {e}")
        finally:
            for m in (monitor, watcher):
                if m:
                    m.stop()
            self.state = "idle"
        barged = bool((monitor and monitor.triggered) or (watcher and watcher.triggered))
        print(" [interrupted]" if barged else "")
        if self.speaker.error:
            print(f"[tts] {self.speaker.error}")
        if self.speaker.first_audio_s is not None:
            print(f"[first audio {self.speaker.first_audio_s:.2f}s]")
        return barged  # the agent persists the turn (P7 sessions)

    def turn(self) -> bool:
        """Listen, answer, speak. Returns True if the user barged in (listen again at once)."""
        tr = self.listen()
        if tr is None:
            print("[nothing heard]")
            return False
        return self.respond(tr.text, tr.lang)

    # --- wake mode ---
    def say(self, text: str, lang: str | None = None) -> None:
        """A fixed spoken line (0 tokens)."""
        print(f"jarvis> {text}", flush=True)
        self.state = "speaking"
        try:
            self.speaker.speak(text, lang=lang or self.lang)
        finally:
            self.state = "idle"

    def ack(self) -> None:
        if config.WAKE_ACK == "beep":
            wake.beep()
        elif config.WAKE_ACK == "voice":
            self.say(wake.ACK_TEXT.get(self.lang, "Yes?"))

    def sleep_until_wake(self) -> wake.WakeEvent | None:
        """SLEEPING: block until "Hey Jarvis", the hotkey/Enter, or quit. None = hotkey/quit."""
        self.state = "sleeping"
        print('[sleeping — say "Hey Jarvis"]', flush=True)
        listener = wake.WakeListener(self._recognizer, self._guard, busy=self._busy_speaking)
        try:
            return listener.listen(self.trigger, idle=self.announce_jobs)
        finally:
            self.state = "idle"

    def handle(self, text: str, lang: str) -> str:
        """One heard utterance while awake: 'sleep' | 'quit' | 'barged' | 'ok' (0 tokens for commands)."""
        kind = wake.classify(text)
        if kind == "sleep":
            self.say(SLEEP_REPLY.get(lang, SLEEP_REPLY["en"]), lang)
            return "sleep"
        if kind == "exit":
            self.lang = lang
            return "quit" if self.confirm("Shut down Jarvis?") else "ok"
        if kind == "stop":
            return "ok"  # nothing is playing: just keep listening
        text = wake.strip_wake(text)
        hit = wake.match_wake(text)
        if hit is not None and not hit.command:
            self.ack()  # "hey jarvis" again while awake
            return "ok"
        return "barged" if self.respond(text, lang) else "ok"

    def awake(self, command: str = "", lang: str | None = None) -> str:
        """AWAKE: continuous turns. Returns 'sleep' or 'quit'."""
        print("[awake]", flush=True)
        last = time.monotonic()
        if command:
            res = self.handle(command, lang or self.lang)
            if res in ("sleep", "quit"):
                return res
            last = time.monotonic()
        else:
            self.ack()
        while not self.quit.is_set():
            self.trigger.clear()
            left = config.WAKE_IDLE_S - (time.monotonic() - last)
            if left <= 0:
                print("[idle: going to sleep]", flush=True)
                return "sleep"
            try:
                tr = self.listen(start_timeout_s=max(1.0, left), quiet=True)
            except audio.AudioError as e:
                print(f"[audio error] {e}")
                return "sleep"
            if tr is None:
                continue
            res = self.handle(tr.text, tr.lang)
            if res in ("sleep", "quit"):
                return res
            last = time.monotonic()
            self.announce_jobs()
        return "quit"

    def _run_wake(self) -> None:
        while not self.quit.is_set():
            try:
                ev = self.sleep_until_wake()
            except audio.AudioError as e:
                print(f"[audio error] {e}; retrying in 5 s")
                if self.quit.wait(5):
                    break
                continue
            if self.quit.is_set():
                break
            if ev is not None:
                print(f"[wake: {ev.heard}]", flush=True)
            if self.awake(ev.command if ev else "", ev.lang if ev else None) == "quit":
                break

    def _run_hotkey(self) -> None:
        again = False
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
        if self.wake_mode:
            how = f'say "Hey Jarvis" or {how}'
        cut = "talk over Jarvis" if config.BARGE_IN else (f"press {key}" if key else "press Enter")
        if self.wake_mode and config.WAKE_STOP_WORD:
            cut += ' or say "stop"'
        print(f"Jarvis voice ({config.LLM_FAST}). {how} to talk; {cut} to interrupt; "
              f"q + Enter or Ctrl+C to quit.")
        greeting.start(self.greet)  # background thread: the hotkey is already live
        try:
            self._run_wake() if self.wake_mode else self._run_hotkey()
        except KeyboardInterrupt:
            print()
        finally:
            self.quit.set()
            self.speaker.stop()
            jobs.shutdown()
            self.agent.end_session()
            if self._hk:
                self._hk.stop()
        return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m jarvis --voice")
    ap.add_argument("--voice", action="store_true")
    ap.add_argument("--wake", action="store_true", help='wake word mode ("Hey Jarvis"); default from config')
    ap.add_argument("--no-wake", action="store_true", help="hotkey / Enter only")
    ap.add_argument("--no-hotkey", action="store_true", help="use Enter instead of the global hotkey")
    ap.add_argument("--no-barge-in", action="store_true", help="do not watch the mic while speaking")
    a = ap.parse_args(argv)
    if not config.GROQ_API_KEY:
        print("GROQ_API_KEY missing: add it to .env", file=sys.stderr)
        return 1
    wake_mode = a.wake or (config.WAKE_ENABLED and not a.no_wake)
    return VoiceLoop(use_hotkey=not a.no_hotkey, barge_in=False if a.no_barge_in else None,
                     wake_mode=wake_mode).run()


if __name__ == "__main__":
    raise SystemExit(main())
