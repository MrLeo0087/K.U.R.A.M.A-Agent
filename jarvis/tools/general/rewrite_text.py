"""rewrite_text: rewrite the text selected in ANY app in place (formal, fix grammar, translate, shorten...) (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="clipboard", safety="safe",
      description="Rewrite the text the user has selected in any app and replace it in place: make formal/polite/"
                  "simple, fix grammar, translate (Nepali, Hindi, English...), shorten, expand. Or rewrite given text.")
def rewrite_text(instruction: str, text: str = "") -> str:
    """Rewrite selected text.

    Args:
        instruction: What to do, e.g. "make it formal", "fix grammar", "translate to Nepali", "shorten".
        text: Text to rewrite instead of the selection (optional).
    """
    from jarvis.core import rewrite
    if not instruction.strip():
        return "error: say how to rewrite it"
    return rewrite.rewrite(instruction.strip(), text)
