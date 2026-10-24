"""about_me: the assistant's knowledge about itself (docs/kurama_self.md); protected topics need the password (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="self", safety="safe", max_chars=2000,
      description="Facts about yourself: overview, outputs (where files go), howto, limits; storage/architecture/"
                  "security are password-protected.")
def about_me(topic: str = "overview") -> str:
    """Answer questions about the assistant itself.

    Args:
        topic: overview | outputs | howto | limits | storage | architecture | security.
    """
    from jarvis.core import selfknow
    return selfknow.ask(topic)
