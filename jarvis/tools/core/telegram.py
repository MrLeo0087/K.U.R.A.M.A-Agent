"""telegram: send a message, a file (by path OR by name: it is found on all disks), or the latest thing made, to
the owner's own Telegram. Safe (only ever the owner's chat)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.core._hub import Act, run

TABLE = {
    "message": Act("send_message_telegram", lambda a: {"text": a.get("text")}),
    "file": Act("send_file_telegram", lambda a: {"path": a.get("file"), "caption": a.get("text", "")}),
    "latest": Act("send_last_result", lambda a: {"kind": a.get("kind", "any")}),
}


@tool(group="core", safety="safe",
      description="Send to the user's Telegram: a text message, a file (give a path or just its name: it is found on "
                  "the laptop), or the latest thing made (picture, document, list).")
def telegram(action: Literal["message", "file", "latest"], text: str = "", file: str = "",
             kind: Literal["any", "image", "document", "list"] = "any") -> str:
    """Telegram.

    Args:
        action: message, file, latest.
        text: The message (or a caption for a file).
        file: A path or a file name ('naruto.jpg', 'tools.py'); a folder is sent as a zip.
        kind: latest: image, document, list or any.
    """
    if action == "file" and file and not Path(file).expanduser().exists() and "/" not in file:
        return run(TABLE, {"action": "file", "file": file, "text": text})  # send_file_telegram finds it by name
    return run(TABLE, {"action": action, "text": text, "file": file, "kind": kind})
