"""Read the text in a picture: a screen area you drag, the whole screen, an image file, a copied image or a photo
sent on Telegram.

Cheapest first:
  1. Tesseract on this laptop (eng + nep; 0 tokens). Pillow cleans the picture first (grey, bigger, contrast).
  2. Only when Tesseract's own confidence is low (handwriting, a blurry photo) the vision model reads it once
     (the picture is shrunk to 1024 px first: ~1-2k tokens). config.OCR_VISION = False never sends pictures.
The text goes to the clipboard, so it can be pasted at once.
"""
from __future__ import annotations

import base64
import io
import logging
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from jarvis.core import config

log = logging.getLogger("jarvis.ocr")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".heic"}


class Result:
    def __init__(self, text: str, engine: str, conf: float):
        self.text, self.engine, self.conf = text, engine, conf


def _tmp(suffix: str = ".png") -> Path:
    d = Path(tempfile.gettempdir()) / "kurama-ocr"
    d.mkdir(exist_ok=True)
    return d / f"{int(time.time() * 1000)}{suffix}"


# --- getting the picture ---------------------------------------------------------------------------------------
def grab_area() -> Path | str:
    """The user drags a box on the screen (gnome-screenshot -a, else scrot -s). Path, or a message."""
    out = _tmp()
    if shutil.which("gnome-screenshot"):
        cmd = ["gnome-screenshot", "-a", "-f", str(out)]
    elif shutil.which("scrot"):
        cmd = ["scrot", "-s", "-o", str(out)]
    else:
        return "I need gnome-screenshot or scrot to pick a screen area: sudo apt install gnome-screenshot"
    try:
        subprocess.run(cmd, timeout=120, check=False, capture_output=True)
    except subprocess.TimeoutExpired:
        return "No area was picked in 2 minutes."
    return out if out.is_file() and out.stat().st_size > 0 else "No area was picked (Esc cancels it)."


def grab_screen() -> Path | str:
    out = _tmp()
    if shutil.which("gnome-screenshot"):
        subprocess.run(["gnome-screenshot", "-f", str(out)], timeout=20, check=False, capture_output=True)
    elif shutil.which("scrot"):
        subprocess.run(["scrot", "-o", str(out)], timeout=20, check=False, capture_output=True)
    return out if out.is_file() else "I couldn't take a screenshot."


def grab_clipboard() -> Path | str:
    """An image that was copied (Ctrl+C on a picture, or a screenshot to the clipboard)."""
    try:
        types = subprocess.run(["xclip", "-selection", "clipboard", "-t", "TARGETS", "-o"], capture_output=True,
                               timeout=5).stdout.decode(errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return "I can't read the clipboard (xclip missing?)."
    kind = next((t for t in ("image/png", "image/jpeg") if t in types), "")
    if not kind:
        return "There's no picture on the clipboard. Copy an image, or say 'read this area'."
    out = _tmp(".png" if kind.endswith("png") else ".jpg")
    data = subprocess.run(["xclip", "-selection", "clipboard", "-t", kind, "-o"], capture_output=True, timeout=10).stdout
    out.write_bytes(data)
    return out


def latest_image() -> Path | None:
    """The newest picture in Downloads / Pictures / Desktop (a photo just received or saved)."""
    best: tuple[float, Path] | None = None
    for d in (Path.home() / "Downloads", Path.home() / "Pictures", Path.home() / "Desktop",
              Path(config.DATA_DIR) / "telegram"):
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if p.suffix.lower() in IMAGE_EXT and p.is_file():
                m = p.stat().st_mtime
                if best is None or m > best[0]:
                    best = (m, p)
    return best[1] if best else None


# --- reading it ------------------------------------------------------------------------------------------------
def _prepare(src: Path) -> Path:
    """Grey, upscaled when small, auto-contrast: Tesseract reads phone photos and small screen text much better."""
    from PIL import Image, ImageOps
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("L")
        if max(im.size) < 1600:
            f = min(3.0, 1600 / max(im.size))
            im = im.resize((int(im.width * f), int(im.height * f)), Image.LANCZOS)
        im = ImageOps.autocontrast(im, cutoff=1)
        out = _tmp()
        im.save(out)
    return out


def tesseract(src: Path) -> Result:
    """0 tokens. Text in reading order + the mean word confidence (0-100)."""
    if not shutil.which("tesseract"):
        return Result("", "none", 0.0)
    img = _prepare(src)
    langs = config.OCR_LANGS
    try:
        tsv = subprocess.run(["tesseract", str(img), "stdout", "-l", langs, "--psm", "3", "tsv"],
                             capture_output=True, timeout=90).stdout.decode(errors="replace")
    finally:
        img.unlink(missing_ok=True)
    lines: dict[tuple, list[str]] = {}
    confs: list[float] = []
    for row in tsv.splitlines()[1:]:
        c = row.split("\t")
        if len(c) < 12 or not c[11].strip():
            continue
        try:
            conf = float(c[10])
        except ValueError:
            continue
        if conf < 0:
            continue
        confs.append(conf)
        lines.setdefault((int(c[2]), int(c[3]), int(c[4])), []).append(c[11])  # block, paragraph, line
    out, last_par = [], None
    for (b, p, _), words in lines.items():
        if last_par is not None and (b, p) != last_par:
            out.append("")  # a blank line between paragraphs
        out.append(" ".join(words))
        last_par = (b, p)
    text = "\n".join(out).strip()
    return Result(text, "tesseract", sum(confs) / len(confs) if confs else 0.0)


def vision(src: Path) -> Result:
    """The vision model reads it (handwriting / hard photos): one call, picture shrunk to 1024 px."""
    from PIL import Image, ImageOps
    from jarvis.core import llm
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((1024, 1024))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80)
    b64 = base64.b64encode(buf.getvalue()).decode()
    r = llm.chat([{"role": "user", "content": [
        {"type": "text", "text": "Write out exactly the text in this picture (handwriting too), keeping its lines and "
                                 "language (Nepali in Devanagari). Only the text; '[?]' for a word you can't read."},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}],
        tier="vision", purpose="ocr_vision", max_tokens=1200)
    return Result((r.text or "").strip(), "vision", 100.0)


def looks_poor(r: Result) -> bool:
    words = re.findall(r"[^\W\d_]{2,}", r.text)
    return r.conf < config.OCR_MIN_CONF or len(words) < 2


def read(src: Path, allow_vision: bool | None = None) -> Result:
    """Tesseract first; the vision model only when that looks poor (and it's allowed)."""
    r = tesseract(src)
    allow = config.OCR_VISION if allow_vision is None else allow_vision
    if looks_poor(r) and allow:
        try:
            v = vision(src)
            if v.text:
                return v
        except Exception as e:  # noqa: BLE001 - no AI (No AI mode, limit, offline): keep Tesseract's best try
            log.info("vision OCR failed: %s", e)
    return r


def copy(text: str) -> None:
    from jarvis.core import rewrite
    rewrite._xclip(["-selection", "clipboard"], text)


def run(source: str = "area", path: str = "") -> str:
    """source: area (drag a box) | screen | clipboard | file (path, or the newest picture)."""
    tmp = None
    if source == "file" or path:
        if path and path.strip().lower() not in ("this", "it", "photo", "picture", "image", "latest"):
            from jarvis.core.paths import resolve_target
            p = resolve_target(path)
            if isinstance(p, str):
                return p
        else:
            p = latest_image()
            if p is None:
                return "I couldn't find a picture in Downloads, Pictures or Desktop."
    else:
        got = {"area": grab_area, "screen": grab_screen, "clipboard": grab_clipboard}.get(source, grab_area)()
        if isinstance(got, str):
            return got
        p = tmp = got
    if p.suffix.lower() not in IMAGE_EXT:
        return f"{p.name} isn't a picture. For a PDF say 'convert {p.name} to text'."
    try:
        r = read(p)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    if not r.text.strip():
        return "I couldn't find any text in that picture."
    copy(r.text)
    how = " (read by the AI: handwriting/hard photo)" if r.engine == "vision" else ""
    unsure = " Some words may be wrong (blurry or handwriting)." if r.engine == "tesseract" and looks_poor(r) else ""
    return f"{r.text}\n\n(Copied{how}.{unsure})"
