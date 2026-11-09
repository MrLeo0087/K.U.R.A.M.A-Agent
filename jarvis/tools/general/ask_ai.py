"""ask_ai: "ask Gemini / ChatGPT / Claude <question>" about the selected text or code: KURAMA builds the prompt
(question + selection + the page or file it is in), Brave opens the site and the KURAMA extension pastes and sends
it. 0 KURAMA tokens; follow-ups go to the same chat (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="web", safety="safe",
      description="Ask Gemini / ChatGPT / Claude on the web about the selected text or code (pastes and sends it in "
                  "Brave, 0 tokens); also set which one is the default.")
def ask_ai(question: str = "", site: Literal["", "gemini", "chatgpt", "claude"] = "", set_default: bool = False) -> str:
    """Ask a web AI.

    Args:
        question: The user's question in their words ('why does this work'); empty = explain the selection.
        site: gemini, chatgpt or claude; empty = the default (or the same chat for a follow-up).
        set_default: True = only make `site` the default for 'ask the AI'.
    """
    from jarvis.core import askai
    if set_default:
        return askai.set_default(site)
    return askai.ask(question, site)
