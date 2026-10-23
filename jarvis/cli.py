"""Terminal text chat: `python -m jarvis`. LangGraph agent (router + tools), streamed output.

`python -m jarvis --voice` starts the voice loop instead.
"""
from __future__ import annotations

import sys

from jarvis.core import agent, config, jobs, llm, store

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
    bot = agent.Agent(channel="text")  # confirmations use safety's terminal prompt in text mode
    bot.warm()
    jobs.set_mode("text")  # finished background jobs print "[job #N done] ..."
    if tty:
        print(f"Jarvis text chat ({config.LLM_FAST} / {config.LLM_DEFAULT}, tools on). /quit to exit.")
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
        parts: list[str] = []
        try:
            for delta in bot.stream(line, mode="text"):
                if not parts:
                    print("jarvis> ", end="", flush=True)
                parts.append(delta)
                print(delta, end="", flush=True)
        except llm.LLMError as e:
            print(f"[error] {e}")
            continue
        except KeyboardInterrupt:
            print(" [stopped]")
        print()
        tools = bot.last.get("tools") or []
        if tools and tty:
            print(f"[tools: {', '.join(t['name'] + ('' if t['ok'] else ' (failed)') for t in tools)}]")
    active = jobs.get_manager().active() if jobs._manager else []
    if active:
        print(f"[cancelling {len(active)} background job(s); partial output stays in data/outputs]")
    jobs.shutdown()
    bot.end_session()  # persists the session; at most one fast-tier profile extraction
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
