"""wifi_share: send a file/folder to the phone over the local Wi-Fi (link + QR, no internet, no size limit) (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="telegram", safety="safe",
      description="Send a file or folder to the phone over Wi-Fi (not Telegram): makes a private link + QR code on "
                  "the same network, any size, full speed; or stop sharing.")
def wifi_share(action: Literal["share", "stop"] = "share", path: str = "") -> str:
    """Share over Wi-Fi.

    Args:
        action: share (start) or stop.
        path: The file/folder: a path, a name to find, or 'this' for the one just mentioned.
    """
    from jarvis.core import wifishare
    if action == "stop":
        return wifishare.stop()
    from jarvis.core.paths import resolve_target
    target = resolve_target(path)
    if isinstance(target, str):
        return target
    from jarvis.core import safety
    r = wifishare.start(target, show_qr=safety.context().get("mode") != "telegram")
    return wifishare.status_text(r)
