"""phone_link: your Android phone over Wi-Fi with KDE Connect: share a file (any size; Telegram when the phone isn't
reachable), ring it, send a link / text, pair it, close the link, status (safe, 0 tokens)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


def _exact(name: str):
    """A file or folder named exactly that (any case) in the home folder's usual places (Downloads/Phone ...)."""
    from pathlib import Path
    home = Path.home()
    want = name.lower()
    for base in (home, *(home / d for d in ("Downloads", "Documents", "Desktop", "Pictures", "Videos", "Music"))):
        try:
            for p in base.iterdir():
                if p.name.lower() == want or p.stem.lower() == want:
                    return p
        except OSError:
            continue
    return None


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
        if not Path(v).expanduser().exists():  # a name ('the phone folder', 'tools.py from laptop'): find it
            import re

            from jarvis.core.paths import smart_path
            name = re.sub(r"\s+(?:in|from|on)\s+(?:my\s+|the\s+)?(?:laptop|computer|pc|disk)$", "", v, flags=re.I).strip()
            name = re.sub(r"^(?:the|my)\s+|\s+(?:folder|file)$", "", name, flags=re.I).strip()
            found = _exact(name) or (smart_path(name) if "/" in name else None)  # (a loose fuzzy match sent
            if found is None:  # phonecmds.py for 'phone'); anywhere on the laptop (home + disks), like the Telegram finder
                from jarvis.tools.general.find_and_send import search
                hits = search(name.removesuffix(" folder").strip())
                if len(hits) > 1:
                    lines = "\n".join(f"{i}. {h}" for i, h in enumerate(hits[:8], 1))
                    return f"I found {len(hits)} like '{name}':\n{lines}\nSay 'share <the full path>'."
                found = hits[0] if hits else None
            if found is None:
                return f"I couldn't find '{v}'. Say its full name, or select it in the Files app and say 'share this'."
            v = str(found)
        from jarvis.core import safety
        if (safety.context() or {}).get("channel") == "telegram":  # asked FROM Telegram: the answer goes back there
            from jarvis.tools.general.send_file_telegram import send_file_telegram
            return send_file_telegram(v)
        return p.share_file(v)
    if not value.strip():
        return "What should I send to the phone?"
    return p.share_link(value) if action == "send_link" else p.share_text(value)
