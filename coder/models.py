"""The AI calls of the coding agent, through KURAMA's LLM layer (same keys, same shared Groq rate limit, logged).
Which model: the plan, hard files and fixes -> the smart tier (gpt-oss-120b); easy files (CSS, README, config)
-> the fast tier (gpt-oss-20b). Tokens are counted into the run."""
from __future__ import annotations

from coder.run import Run

TIER = {"plan": "smart", "hard": "smart", "normal": "smart", "fix": "smart", "easy": "fast", "review": "fast"}


def ask(run: Run | None, role: str, system: str, user: str, max_tokens: int) -> str:
    from jarvis.core import llm
    r = llm.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                 tier=TIER.get(role, "smart"), purpose=f"coder_{role}", max_tokens=max_tokens)
    if run is not None:
        run.tokens += int(r.prompt_tokens or 0) + int(r.completion_tokens or 0) or (len(system + user) // 4 + len(r.text) // 4)
    return r.text or ""
