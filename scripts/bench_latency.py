"""Voice latency bench: agent (voice mode) -> tts.Speaker -> fake player.

Prints, per prompt, seconds from the agent call to the first audio bytes reaching the player,
the first text delta time and the tier used. Then runs one text-mode tool call
("what time is it?") and prints the llm_calls rows it logged. Needs GROQ_API_KEY and network.

    venv/bin/python scripts/bench_latency.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

T_START = time.monotonic()
from jarvis.core import agent, store, tts  # noqa: E402

PROMPTS = [
    ("en", "Hi Jarvis, how are you today?"),
    ("en", "Explain in detail how a car engine works."),
    ("ne", "तिमी को हौ?"),
]


class FakePlayer:
    """Stands in for audio.Player: records when the first audio bytes arrive."""

    first: float | None = None

    def start(self, src=None):
        return self

    def write(self, data: bytes) -> bool:
        if FakePlayer.first is None:
            FakePlayer.first = time.monotonic()
        return True

    def finish(self, timeout=None):
        return 0

    def stop(self) -> None:
        pass


def voice_turn(bot: agent.Agent, speaker: tts.Speaker, lang: str, text: str) -> None:
    tts.prewarm()
    time.sleep(1.5)
    FakePlayer.first = None
    first_text: list[float] = []

    def deltas():
        for d in bot.stream(text, mode="voice", lang=lang):
            if not first_text:
                first_text.append(time.monotonic())
            yield d

    t0 = time.monotonic()
    speaker.speak_stream(deltas(), lang=lang, block=True)
    audio = (FakePlayer.first - t0) if FakePlayer.first else float("nan")
    txt = (first_text[0] - t0) if first_text else float("nan")
    print(f"[{lang}] first_audio={audio:.2f}s first_text={txt:.2f}s tier={bot.last.get('tier')} "
          f"prompt={text[:40]!r}")


def text_tool_call(bot: agent.Agent) -> None:
    last_id = (store._exec("SELECT MAX(id) FROM llm_calls")[0][0]) or 0
    t0 = time.monotonic()
    answer = bot.run("what time is it?")
    print(f"[text] {time.monotonic() - t0:.2f}s tools={bot.last.get('tools')} answer={answer!r}")
    for r in store._exec("SELECT model, purpose, prompt_tokens, completion_tokens, latency_ms, ok "
                         "FROM llm_calls WHERE id > ? ORDER BY id", (last_id,)):
        print("   logged:", tuple(r))


def main() -> int:
    tts.warm()
    bot = agent.Agent(confirm=lambda p: False)
    bot.warm()
    print(f"startup (imports + warm) {time.monotonic() - T_START:.2f}s")
    speaker = tts.Speaker(player_factory=FakePlayer)
    for lang, text in PROMPTS:
        voice_turn(bot, speaker, lang, text)
    text_tool_call(agent.Agent(confirm=lambda p: False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
