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
_GET = r"(?:send|take|get|grab|give|show|capture|snap|can you (?:send|take|get|grab|give|show|capture)|i want)"
_LOC = r"(?:(?: of)?(?: my| the| this)?(?: laptop| screen| computer| desktop))?(?: now)?"
SCREEN = re.compile(r"^\s*(?:/screen|" + _GET + r"(?: me)?(?: a| the)? screen ?shot" + _LOC
                    + r"|screen ?shot" + _LOC + r"|what(?:'s| is) on my (?:laptop|screen))\s*[.!?]*$", re.I)
# "send that", "send it again", "send that in telegram" — resend the last photo/video/screenshot (no file named)
RESEND = re.compile(r"^\s*(?:send|resend|re-send|share|forward|give)(?:\s+(?:me|it|that|this|those|the|one))*"
                    r"(?:\s+(?:file|photo|picture|image|screenshot|screen ?shot|video|clip))?"
                    r"(?:\s+(?:again|once more|back|now|also|as well|too))*"
                    r"(?:\s+(?:to|in|on)\s+(?:my\s+)?(?:telegram|phone|mobile))?\s*[.!?]*$", re.I)
CLIP = re.compile(r"^\s*(?:/clip|(?:send|what(?:'s| is))(?: me)?(?: my| the)? (?:laptop(?:'s)? )?clipboard"
                  r"(?: from (?:my |the )?laptop)?)\s*[.!?]*$", re.I)
# a photo from the laptop's camera ("find my laptop")
CAMERA = re.compile(r"^\s*(?:/camera|/photo|(?:send|take|show|snap)(?: me)?(?: a)? (?:photo|picture|pic|selfie|snap(?:shot)?)"
                    r"(?: from| of| on| using| with)?(?: my| the)?(?: laptop| webcam| camera)+(?: now)?)\s*[.!?]*$", re.I)
# a short video from the laptop's camera; an optional number of seconds ("/video 8")
VIDEO = re.compile(r"^\s*(?:/video|/vid|/rec(?:ord)?|(?:record|take|send|capture)(?: me)?(?: a)? (?:\d+\s*(?:s|sec|seconds?)\s+)?"
                   r"video(?: clip)?(?: from| of| on)?(?: my| the)?(?: laptop| webcam| camera)+)(?:\s+(?P<sec>\d{1,2})\s*(?:s|sec|seconds?)?)?\s*[.!?]*$", re.I)
# label the current Wi-Fi as a known place ("/here Home", "this is home")
HERE = re.compile(r"^\s*(?:/here|(?:remember |save )?(?:this (?:is|spot is|place is)|the laptop is(?: at| in)?))\s+(?P<label>.{1,40}?)\s*[.!?]*$", re.I)
WHERE = re.compile(
    r"^\s*(?:/where|/locate|/find"
    r"|where(?:'s| is| are)?(?: my| the)? laptop(?:'s)?(?: location| at)?"
    r"|(?:find|locate|track|trace)(?: my| the)? laptop"
    r"|(?:give|send|show|get|tell)(?: me)?(?: the| my)? (?:laptop(?:'s)? )?location(?: of(?: my| the)? laptop)?"
    r"|(?:what(?:'s| is))?(?:the )?(?:laptop(?:'s)? )?location(?: of(?: the| my)? laptop)?"
    r"|laptop(?:'s)? location)(?: now| right now)?\s*[.!?]*$", re.I)
# "give me all laptop control commands", "what can you do", "help", "list commands"
HELP_RE = re.compile(r"^\s*(?:/help|/commands?|/start|help|commands?|(?:give me |show me |list |what are |tell me )?"
                     r"(?:all |the |my )?(?:laptop |phone )?(?:control )?commands?(?: list| can i use| do you have)?|"
                     r"what can (?:you|i) (?:do|control|use)(?: from (?:my )?(?:phone|mobile))?)\s*[.!?]*$", re.I)


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
    """'note DSA' files a photo with your DSA notes; 'to downloads/papers' or 'save in project1 tara' picks the folder;
    else the phone inbox."""
    if n := re.match(r"^\s*(?:study )?notes?(?:\s+(?:for|in|on))?\s+(?P<s>[\w+#. ]{1,30})\s*$", caption or "", re.I):
        from jarvis.core import notes
        d = notes.root() / notes._canon(n.group("s"))  # noqa: SLF001
        (d / "images").mkdir(parents=True, exist_ok=True)
        return d / "images"
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


_last_sent: dict = {"path": None}


def remember_sent(path) -> None:
    """Record the last file sent to the phone, so 'send that again' can resend it."""
    _last_sent["path"] = str(path)


def _newest(*globs: tuple[str, str]) -> Path | None:
    """The most recent file matching (dir, pattern) pairs (for 'send that' after an agent-saved screenshot)."""
    best = None
    for d, pat in globs:
        for p in Path(d).expanduser().glob(pat):
            if best is None or p.stat().st_mtime > best.stat().st_mtime:
                best = p
    return best


def resend_last() -> str:
    """Send the last photo/video/screenshot again (or the newest one on disk if none is remembered)."""
    from jarvis.tools.general.send_file_telegram import deliver
    p = _last_sent["path"]
    path = Path(p) if p and Path(p).exists() else _newest(
        (config.SCREENSHOT_DIR, "*.png"), (str(Path(config.DATA_DIR) / "guard"), "*.jpg"),
        (str(Path(config.DATA_DIR) / "guard"), "*.mp4"))
    if path is None or not path.exists():
        return ("I don't have a recent photo, video or screenshot to send. Ask for /screen, /camera or /video "
                "and I'll send it right away.")
    out = deliver(path, "Here it is.")
    if not out.startswith("error"):
        remember_sent(path)
    return out


def screenshot_to_phone() -> str:
    from jarvis.tools.general.screenshot import screenshot
    from jarvis.tools.general.send_file_telegram import deliver
    out = screenshot("full")
    m = re.search(r"(/\S+\.png)", out)
    if not m:
        return out
    r = deliver(Path(m.group(1)), f"Your laptop screen at {time.strftime('%H:%M')}")
    if not r.startswith("error"):
        remember_sent(m.group(1))
    return r
