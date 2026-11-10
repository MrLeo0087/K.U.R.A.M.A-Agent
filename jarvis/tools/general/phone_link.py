"""phone_link: your Android phone from the laptop: its screen in a window (scrcpy), ring it, send it a file / link /
text over Wi-Fi (GSConnect + KDE Connect), what is set up (safe, 0 tokens)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="telegram", safety="safe",
      description="The Android phone from the laptop: screen = show / control the phone's screen in a window; ring; "
                  "send_file / send_link / send_text over Wi-Fi (not Telegram); status = what is set up and how.")
def phone_link(action: Literal["screen", "ring", "send_file", "send_link", "send_text", "status"] = "status",
               value: str = "") -> str:
    """Phone link.

    Args:
        action: What to do.
        value: The file path / link / text to send; for screen an adb Wi-Fi address (ip:port), else empty.
    """
    from jarvis.core import phonelink as p
    if action == "screen":
        return p.screen(value)
    if action == "ring":
        return p.ring()
    if action in ("send_file", "send_link", "send_text") and not value.strip():
        return "What should I send to the phone?"
    if action == "send_file":
        return p.share_file(value)
    if action == "send_link":
        return p.share_link(value)
    if action == "send_text":
        return p.share_text(value)
    return p.status()
