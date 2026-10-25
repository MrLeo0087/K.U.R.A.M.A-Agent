"""send_file_telegram (P7c): send a local file to the user's Telegram (sendPhoto / sendDocument)."""
from __future__ import annotations

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
    """Resolved file path; raises ValueError unless it exists, is a file, <= 50 MB and is under SHARE_ROOTS."""
    p = _files.resolve(path)
    if not _under_shares(p):
        raise ValueError(f"I can only send files from your home folder or your data disks, not {p}")
    if not p.is_file():
        raise ValueError(f"{p} doesn't exist or isn't a file")
    if p.stat().st_size > config.TELEGRAM_FILE_MAX_MB * 1024 * 1024:
        raise ValueError(f"{p.name} is bigger than {config.TELEGRAM_FILE_MAX_MB} MB")
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
    base = z.name  # the real zip filename (has a timestamp); the parts are <base>.001, .002, …
    parts = split_file(z, int(cap) - 512 * 1024)  # a little headroom under the limit
    if len(parts) > 25:  # absurdly large: don't flood the chat with 40 parts
        for pp in parts:
            pp.unlink(missing_ok=True)
        return (f"“{name}” would need {len(parts)} Telegram files even split — that's too many to send sensibly. "
                f"Tell me a specific sub-folder or file instead.")
    results = []
    for i, pp in enumerate(parts, 1):
        results.append(deliver(pp, f"{name} — part {i}/{len(parts)}"))
    bad = [r for r in results if r.startswith("error")]
    howto = (f"Sent “{name}” as {len(parts)} parts ({base}.001 … .{len(parts):03d}). To rebuild it on a computer: "
             f"put all parts in one folder, then run  cat {base}.*  >  {base}  and unzip {base}.")
    return howto if not bad else howto + "\nSome parts failed: " + "; ".join(bad)


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
    resolved = _files.resolve(path)
    if resolved.is_dir():  # a folder: zip it (minus junk); split into parts if it's over the Telegram limit
        return deliver_folder(resolved, caption)
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
