"""Terminal text chat: `python -m jarvis`. Fast tier, streamed output, last 6 turns of history."""
from __future__ import annotations

import sys
from collections import deque

from jarvis.core import config, llm, store

SYSTEM_PROMPT = (
    "You are Jarvis, a concise, friendly assistant running on the user's Ubuntu laptop. "
    "Reply in 1-2 short sentences unless asked for more detail. "
    "Answer in the user's language (English, Hindi or Nepali). "
    "Plain text only: no markdown, lists or emojis, since replies may be spoken aloud. "
    "If you do not know something, say so briefly."
)

QUIT = {"/quit", "/exit", "/q"}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--voice" in argv:  # `python -m jarvis --voice`; text chat stays the default
        from jarvis.voice import main as voice_main

        return voice_main(argv)
    if not config.GROQ_API_KEY:
        print("GROQ_API_KEY missing: add it to .env", file=sys.stderr)
        return 1
    tty = sys.stdin.isatty()
    history: deque[dict] = deque(maxlen=config.HISTORY_TURNS * 2)
    if tty:
        print(f"Jarvis text chat ({config.LLM_FAST}). /quit to exit.")
    while True:
        try:
            line = input("you> " if tty else "").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.lower() in QUIT:
            break
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}, *history, {"role": "user", "content": line}]
        print("jarvis> ", end="", flush=True)
        parts: list[str] = []
        try:
            for delta in llm.chat(msgs, tier="fast", stream=True, purpose="cli_chat", max_tokens=400):
                parts.append(delta)
                print(delta, end="", flush=True)
        except llm.LLMError as e:
            print(f"[error] {e}")
            continue
        except KeyboardInterrupt:
            print(" [stopped]")
        print()
        reply = "".join(parts).strip()
        history.append({"role": "user", "content": line})
        history.append({"role": "assistant", "content": reply})
        try:
            store.add_message("user", line)
            store.add_message("assistant", reply)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
