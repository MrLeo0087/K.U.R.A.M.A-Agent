"""cleanup: clean RAM (top RAM/CPU apps + KURAMA's idle memory), storage (self-rebuilding caches, old Trash) or
KURAMA (its old logs, caches, temp files) — only safe things, 0 tokens, no internet (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="system", safety="safe",
      description="Clean / optimize: ram (top apps by RAM and CPU, frees KURAMA's idle memory), storage (deletes "
                  "caches that rebuild themselves; never browsers or your files), kurama "
                  "(KURAMA's old logs, caches, temp files; chats, memory and videos stay).")
def cleanup(action: Literal["ram", "storage", "kurama"] = "ram") -> str:
    """Safe cleanups.

    Args:
        action: ram, storage or kurama.
    """
    from jarvis.core import cleanup as c
    return c.run(action)
