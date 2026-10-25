"""send_file_telegram (P7c): send a local file to the user's Telegram (sendPhoto / sendDocument)."""
from __future__ import annotations

import re
from pathlib import Path

from jarvis.core import config, notify
from jarvis.core.registry import alias, tool
from jarvis.tools.general import _files, _tg

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}
PHOTO_MAX = 10 * 1024 * 1024  # Bot API sendPhoto limit


ZIP_SKIP = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".mypy_cache",
            ".pytest_cache", ".next", ".cache", "site-packages"}


def _under_shares(p: Path) -> bool:
    from jarvis.core.paths import all_disks
    return any(_files.inside(p, Path(r)) for r in (*config.SHARE_ROOTS, *all_disks()))


def check_path(path: str) -> Path:
    """Resolved file path; raises ValueError unless it exists, is a file and is under SHARE_ROOTS.
    (No size limit here: deliver() sends a big file as a download link instead of rejecting it.)"""
    p = _files.resolve(path)
    if not _under_shares(p):
        raise ValueError(f"I can only send files from your home folder or your data disks, not {p}")
    if not p.is_file():
        raise ValueError(f"{p} doesn't exist or isn't a file")
    return p


def zip_dir(path: str | Path) -> Path:
    """Zip a folder (skipping junk like venv/.git/node_modules) into data/outputs/zips, for sending to Telegram.
    Raises ValueError if the folder is missing, outside the allowed roots, or the content exceeds the size limit."""
    import time
    import zipfile

    p = _files.resolve(str(path))
    if not _under_shares(p):
        raise ValueError(f"I can only send folders from your home folder or your data disks, not {p}")
    if not p.is_dir():
        raise ValueError(f"{p} isn't a folder")
    cap = config.TELEGRAM_FILE_MAX_MB * 1024 * 1024
    hard = cap * 40  # ~2 GB raw: above this, zipping it just to find out it won't fit is a waste
    files, total = [], 0
    for f in p.rglob("*"):
        if not f.is_file() or any(part in ZIP_SKIP for part in f.relative_to(p).parts):
            continue
        try:
            total += f.stat().st_size
        except OSError:
            continue
        files.append(f)
    if not files:
        raise ValueError(f"the folder “{p.name}” is empty (or only junk), nothing to send")
    if total > hard:
        raise ValueError(
            f"“{p.name}” is about {total // (1024 * 1024)} MB — far over Telegram's {config.TELEGRAM_FILE_MAX_MB} MB "
            f"limit even compressed. Tell me a specific sub-folder or file to send instead.")
    out_dir = Path(config.OUTPUTS_DIR) / "zips"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{p.name}-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:  # actually compress
        for f in files:
            z.write(f, Path(p.name) / f.relative_to(p))
    return out


def split_file(path: Path, part_bytes: int) -> list[Path]:
    """Split a big file into <=part_bytes pieces named <file>.001, .002, … (reassemble with `cat … > file`)."""
    parts, i = [], 1
    with open(path, "rb") as fh:
        while chunk := fh.read(part_bytes):
            part = path.with_name(f"{path.name}.{i:03d}")
            part.write_bytes(chunk)
            parts.append(part)
            i += 1
    path.unlink(missing_ok=True)  # keep only the parts
    return parts


def deliver_folder(path: str | Path, caption: str = "") -> str:
    """Zip a folder and send it to Telegram. If the zip is over the limit, split it into numbered parts and send
    each, with instructions to reassemble. (Sending happens inside; returns a status line.)"""
    if err := _tg.ready():
        return err
    try:
        z = zip_dir(path)
    except ValueError as e:
        return f"error: {e}"
    cap = config.TELEGRAM_FILE_MAX_MB * 1024 * 1024
    name = Path(path).name if not isinstance(path, Path) else path.name
    if z.stat().st_size <= cap:
        return deliver(z, caption or f"{name} (folder, zipped)")
    # Too big for Telegram: upload the ONE zip to a free host and send a single download link (far better than
    # splitting into parts you can't rebuild on a phone).
    mb = z.stat().st_size / (1024 * 1024)
    return upload_and_link(z, name, mb)


def upload_and_link(file_path: Path, name: str, mb: float, is_zip: bool = True) -> str:
    from jarvis.core import cloudshare
    try:
        link = cloudshare.share(str(file_path))
    except Exception as e:
        return (f"“{name}” is {mb:.0f} MB — too big for Telegram's {config.TELEGRAM_FILE_MAX_MB} MB limit, and the "
                f"file-share upload didn't work ({str(e)[:100]}). It's saved on your laptop at {file_path}.")
    tail = " (tap it, download, then unzip)" if is_zip else " (tap it to download)"
    return (f"📦 “{name}” is {mb:.0f} MB — too big to send through Telegram directly, so I uploaded it. Download link"
            f"{tail}:\n{link}\n(Anyone with this link can download it, and it may expire after a while.)")


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
    raw = path.strip().strip("\"'")
    cleaned = re.sub(r"\s*\bfolder\b\s*", " ", raw, flags=re.I).strip()
    literal = Path(raw).expanduser()
    if literal.is_absolute() or raw.startswith("~"):  # an explicit path the user/model gave
        if literal.is_dir():
            return deliver_folder(literal, caption)
        if literal.is_file():
            if err := _tg.ready():
                return err
            try:
                return deliver(check_path(raw), caption)
            except ValueError as e:
                return f"error: {e}"
        return f"error: {literal} doesn't exist"
    nested = "/" in raw or bool(re.search(r"\b(?:in|inside|under|from)\b", raw, re.I))  # "X in Y", "downloads/project"
    if nested:
        try:
            from jarvis.tools.interactive._proc import resolve_dir
            d = resolve_dir(cleaned)
            if d.is_dir():
                return deliver_folder(d, caption)
        except Exception:
            pass
    # a bare NAME ("phone", "clz_project", "report.pdf"): find it with EXACT-match preference — never fuzzy to "Python"
    want = "folder" if re.search(r"\b(?:folder|directory|dir)\b", raw, re.I) else "file"
    return find_and_send(cleaned, want=want)


def deliver(p: Path, caption: str = "") -> str:
    """Upload one checked file to the user's chat (photos as pictures, the rest as documents).
    A file over Telegram's limit is uploaded to a file host and sent as a download link instead."""
    if p.stat().st_size > config.TELEGRAM_FILE_MAX_MB * 1024 * 1024:
        return upload_and_link(p, p.name, p.stat().st_size / (1024 * 1024), is_zip=False)
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
    # don't put the raw filename in the text: Telegram turns "x.zip" into a (dead) web link because .zip is a TLD.
    # The file itself is attached above with its name, so just confirm.
    return "Sent it to your Telegram. ✅"


alias("find_and_send", "send_file_telegram", lambda a: {"path": a.get("name", ""), "pick": a.get("pick", 0)})
