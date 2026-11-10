"""phone_link: your Android phone over Wi-Fi with KDE Connect: share a file (any size; Telegram when the phone isn't
reachable), ring it, send a link / text, pair it, close the link, status (safe, 0 tokens)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="telegram", safety="safe",
      description="The Android phone over Wi-Fi (KDE Connect): send_file = share a file / folder to the phone (big "
                  "files fast; Telegram if the phone isn't reachable); ring; send_link / send_text; pair = pair the "
                  "phone's KDE Connect app; close = stop the link; status.")
def phone_link(action: Literal["send_file", "ring", "send_link", "send_text", "pair", "close", "status"] = "status",
               value: str = "") -> str:
    """Phone link.

    Args:
        action: What to do.
        value: The file path (or 'this' = the file selected in the Files app / the last one used), link or text.
    """
    from jarvis.core import phonelink as p
    if action == "close":
        return p.close()
    if action == "pair":
        return p.pair()
    if action == "ring":
        return p.ring()
    if action == "status":
        return p.status()
    if action == "send_file":
        v = value.strip().strip("\"'")
        if not v or v.lower() in ("this", "it", "that", "this file", "the file", "this folder"):
            from jarvis.core import focus
            ref = focus.refer("this")
            if ref is None:
                return "Which file? Select it in the Files app (or say its name), then 'share this to my phone'."
            v = str(ref)
        from pathlib import Path
        if not Path(v).expanduser().exists():  # a name ('the phone folder', 'report.pdf'): find it
            from jarvis.core.paths import smart_path
            found = smart_path(v)
            if found is None:
                return f"I couldn't find '{v}'. Say its full name, or select it in the Files app and say 'share this'."
            v = str(found)
        return p.share_file(v)
    if not value.strip():
        return "What should I send to the phone?"
    return p.share_link(value) if action == "send_link" else p.share_text(value)
