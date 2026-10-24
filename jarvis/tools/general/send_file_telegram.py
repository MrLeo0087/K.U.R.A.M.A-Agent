"""send_file_telegram (P7c): send a local file to the user's Telegram (sendPhoto / sendDocument)."""
from __future__ import annotations

from pathlib import Path

from jarvis.core import config, notify
from jarvis.core.registry import alias, tool
from jarvis.tools.general import _files, _tg

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}
PHOTO_MAX = 10 * 1024 * 1024  # Bot API sendPhoto limit


def check_path(path: str) -> Path:
    """Resolved file path; raises ValueError unless it exists, is a file, <= 50 MB and is under SHARE_ROOTS."""
    from jarvis.core.paths import all_disks

    p = _files.resolve(path)
    if not any(_files.inside(p, Path(r)) for r in (*config.SHARE_ROOTS, *all_disks())):
        raise ValueError(f"I can only send files from your home folder or your data disks, not {p}")
    if not p.is_file():
        raise ValueError(f"{p} doesn't exist or isn't a file")
    if p.stat().st_size > config.TELEGRAM_FILE_MAX_MB * 1024 * 1024:
        raise ValueError(f"{p.name} is bigger than {config.TELEGRAM_FILE_MAX_MB} MB")
    return p


# safe: it can only ever send to the owner's own chat (TELEGRAM_CHAT_ID), like find_and_send
@tool(group="telegram", safety="safe",
      description="Send a file from this laptop to the user's Telegram: a full path, or a file NAME to find anywhere "
                  "(all disks; several matches give a numbered list), or pick N / all from the last list.")
def send_file_telegram(path: str = "", caption: str = "", pick: int = 0) -> str:
    """Send a file (photos as pictures, everything else as a document).

    Args:
        path: File path, or just a file name / words from it to find it first.
        caption: Optional short caption.
        pick: Send item N of the last numbered list (-1 = all of them).
    """
    from jarvis.tools.general.find_and_send import find_and_send
    if pick or not path.strip():
        return find_and_send(path, pick)
    try:
        p = check_path(path)
    except ValueError as e:
        if "/" in path or path.startswith("~"):
            return f"error: {e}"
        return find_and_send(path)  # a name, not a path: find it first
    if err := _tg.ready():
        return err
    return deliver(p, caption)


def deliver(p: Path, caption: str = "") -> str:
    """Upload one checked file to the user's chat (photos as pictures, the rest as documents)."""
    photo = p.suffix.lower() in PHOTO_EXT and p.stat().st_size <= PHOTO_MAX
    method, field = ("sendPhoto", "photo") if photo else ("sendDocument", "document")
    payload = {"chat_id": config.TELEGRAM_CHAT_ID, **({"caption": caption[:1000]} if caption else {})}
    try:
        with open(p, "rb") as fh:
            ok = notify.telegram_call(method, payload, files={field: (p.name, fh)})
    except RuntimeError as e:
        return f"error: Telegram didn't accept {p.name}: {e}"
    if not ok:
        return f"error: Telegram didn't accept {p.name} (check the bot token/chat id or your internet)"
    return f"Sent {p.name} to Telegram."


alias("find_and_send", "send_file_telegram", lambda a: {"path": a.get("name", ""), "pick": a.get("pick", 0)})
