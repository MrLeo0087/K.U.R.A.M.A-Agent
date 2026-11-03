"""learned_shortcuts: what KURAMA learned from 👍 / 👎 and clean repeats (0-token shortcuts, kept answers): list, forget (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import config, recipes
from jarvis.core.registry import tool


def _line(i: int, r: dict) -> str:
    what = f"kept answer ({len(r.get('answer') or '')} chars)" if r["kind"] == "answer" else \
        f"{r['tool']} {r['args']}" + (f" (slots: {', '.join(r['slots'])})" if r.get("slots") else "")
    state = "on" if r.get("on") else f"waiting ({len(r.get('ok') or [])}/{config.RECIPE_AUTO_CONFIRMS})"
    return f"{i}. \"{r['text'][:70]}\" -> {what} · {state} · used {r.get('used', 0)}x"


@tool(group="self", safety="safe",
      description="What KURAMA learned from your 👍/👎: its 0-token shortcuts and kept answers, tokens saved; forget one or all.")
def learned_shortcuts(action: Literal["list", "forget", "clear", "stats"] = "list", n: int = 0) -> str:
    """Learned shortcuts.

    Args:
        action: list (numbered), forget (number n), clear (forget all), stats (counts and tokens saved).
        n: The number from the list, for forget.
    """
    rows = sorted(recipes.rows(), key=lambda r: (not r.get("on"), -r.get("used", 0)))
    st = recipes.stats()
    head = (f"Learned: {st['on']} on ({st['answers']} kept answers), {st['waiting']} waiting for a 👍 or one more "
            f"clean run. Saved about {st['saved_today']:,} tokens today, {st['saved_week']:,} this week.")
    if action == "stats":
        return head
    if action == "clear":
        return f"Forgot {recipes.forget(everything=True)} learned shortcuts and answers."
    if action == "forget":
        if not 1 <= n <= len(rows):
            return f"error: say a number from 1 to {len(rows)} (see the list)"
        r = rows[n - 1]
        recipes.forget(r["id"])
        return f"Forgot \"{r['text'][:70]}\"."
    if not rows:
        return "Nothing learned yet. Press 👍 on a good reply (or 👎 on a bad one) and I'll learn from it."
    return head + "\n" + "\n".join(_line(i, r) for i, r in enumerate(rows[:40], 1))
