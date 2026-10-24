"""Phone <-> laptop bridge over the Telegram bot (0 tokens): files and photos you send land on the laptop, voice
notes become text (Groq Whisper: audio quota, not chat tokens), the clipboard goes both ways, and a screenshot of the
laptop comes back on request.
"""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from jarvis.core import config, notify

FILE_URL = "https://api.telegram.org/file/bot{token}/{path}"
# "copy: some text" / "copy this: ..." from the phone puts the text on the laptop's clipboard
COPY = re.compile(r"^\s*(?:copy|clip|paste on laptop|laptop clipboard)(?: this| it)?\s*[:\-]\s*(?P<t>.+)$", re.I | re.S)
SCREEN = re.compile(r"^\s*(?:/screen|(?:send|take|show)(?: me)?(?: a)? screen ?shot(?: of)?(?: my| the)?"
                    r"(?: laptop| screen| computer| desktop)?(?: now)?|screenshot(?: of)?(?: my| the)? "
                    r"(?:laptop|screen|computer|desktop)(?: now)?|what(?:'s| is) on my (?:laptop|screen))\s*[.!?]*$", re.I)
CLIP = re.compile(r"^\s*(?:/clip|(?:send|what(?:'s| is))(?: me)?(?: my| the)? (?:laptop(?:'s)? )?clipboard"
                  r"(?: from (?:my |the )?laptop)?)\s*[.!?]*$", re.I)


def inbox() -> Path:
    d = Path(config.PHONE_INBOX).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def download(file_id: str, max_mb: float = 20.0) -> tuple[bytes, str]:
    """(bytes, telegram file path) of a file the user sent (the Bot API serves up to 20 MB)."""
    info = notify.telegram_call("getFile", {"file_id": file_id})
    if not info or not info.get("file_path"):
        raise RuntimeError("Telegram didn't give me the file")
    if int(info.get("file_size") or 0) > max_mb * 1048576:
        raise RuntimeError(f"the file is bigger than {max_mb:.0f} MB (Telegram's limit for bots)")
    r = notify._http().get(FILE_URL.format(token=config.TELEGRAM_BOT_TOKEN, path=info["file_path"]), timeout=120)
    r.raise_for_status()
    return r.content, info["file_path"]


def _folder(caption: str) -> Path:
    """'to downloads/papers' or 'save in project1 tara' in the caption picks the folder; else the phone inbox."""
    m = re.search(r"\b(?:to|in|into)\s+(?P<f>.+)$", caption or "", re.I)
    if m:
        from jarvis.core.paths import smart_path
        hit = smart_path(m.group("f").strip(" ."), want="dir")
        if hit is not None:
            return hit
    return inbox()


def save_incoming(msg: dict) -> str:
    """A document / photo / video / audio from the phone -> saved on the laptop; returns the reply."""
    caption = msg.get("caption") or ""
    if msg.get("photo"):
        item, name = msg["photo"][-1], f"photo-{time.strftime('%Y%m%d-%H%M%S')}.jpg"  # the biggest size
    else:
        kind = next((k for k in ("document", "video", "audio", "animation") if msg.get(k)), None)
        if kind is None:
            return ""
        item = msg[kind]
        name = item.get("file_name") or f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        data, _ = download(item["file_id"])
    except Exception as e:
        return f"Sorry, I couldn't get that file: {e}"
    folder = _folder(caption)
    name = re.sub(r"[/\\\0]", "_", name)
    path = folder / name
    n = 1
    while path.exists():
        path = folder / f"{Path(name).stem} ({n}){Path(name).suffix}"
        n += 1
    path.write_bytes(data)
    return f"Saved on your laptop: {path} ({len(data) / 1e6:.1f} MB)."


def voice_text(msg: dict) -> str:
    """A voice note -> its text (Whisper); '' when it can't be heard."""
    voice = msg.get("voice") or msg.get("audio")
    data, _ = download(voice["file_id"], max_mb=10)
    wav = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-ac", "1", "-ar", "16000", "-f", "wav",
                          "pipe:1"], input=data, capture_output=True, timeout=60).stdout
    if not wav:
        raise RuntimeError("couldn't read the voice note")
    from jarvis.core import stt
    t = stt.transcribe(wav)
    return (t.text or "").strip()


def clipboard_text() -> str:
    from jarvis.tools.general.read_clipboard import read_clipboard
    text = read_clipboard(3500)
    if text.startswith("error") or not text.strip():
        return "The laptop's clipboard is empty."
    return text


def set_clipboard(text: str) -> str:
    from jarvis.tools.general.write_clipboard import write_clipboard
    out = write_clipboard(text)
    return "Copied to your laptop's clipboard." if not out.startswith("error") else out


def screenshot_to_phone() -> str:
    from jarvis.tools.general.screenshot import screenshot
    from jarvis.tools.general.send_file_telegram import deliver
    out = screenshot("full")
    m = re.search(r"(/\S+\.png)", out)
    if not m:
        return out
    return deliver(Path(m.group(1)), f"Your laptop screen at {time.strftime('%H:%M')}")
