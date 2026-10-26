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
    def __init__(self, text: str, engine: str, conf: float, unsure: float = 0.0, density: float = 999.0):
        self.text, self.engine, self.conf, self.unsure = text, engine, conf, unsure
        self.density = density  # words found per megapixel of the picture


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


def _geometry(wid: int) -> tuple[int, int, int, int, str] | None:
    """(x, y, w, h, wm_class) of a window on the screen (frame included)."""
    try:
        from Xlib import display
        d = display.Display()
        w = d.create_resource_object("window", wid)
        g = w.get_geometry()
        pos = w.translate_coords(d.screen().root, 0, 0)
        cls = " ".join(w.get_wm_class() or ())
        d.close()
        return -pos.x, -pos.y, g.width, g.height, cls
    except Exception as e:  # noqa: BLE001
        log.info("window geometry failed: %s", e)
        return None


def grab_window() -> Path | str:
    """The window the user is looking at (not KURAMA's), cropped from a screenshot; a browser's tab strip and
    address bar are cut off so only the page is read."""
    from jarvis.core import rewrite
    shot = grab_screen()
    if isinstance(shot, str):
        return shot
    wid, _ = rewrite.target_window()
    geo = _geometry(wid) if wid else None
    if not geo:
        return shot
    x, y, w, h, cls = geo
    top = 0
    if re.search(r"brave|chrom|firefox|edge|opera|vivaldi", cls, re.I):
        top = min(110, h // 5)  # tabs + address bar
    from PIL import Image
    with Image.open(shot) as im:
        box = (max(0, x), max(0, y + top), min(im.width, x + w), min(im.height, y + h))
        if box[2] - box[0] > 50 and box[3] - box[1] > 50:
            im.crop(box).save(shot)
    return shot


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
    from PIL import Image
    with Image.open(src) as im:
        mpx = max(0.05, im.width * im.height / 1e6)
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
    unsure = sum(1 for c in confs if c < 50) / len(confs) if confs else 1.0  # handwriting: many unsure words
    return Result(text, "tesseract", sum(confs) / len(confs) if confs else 0.0, unsure, len(confs) / mpx)


def vision(src: Path, focus: bool = False) -> Result:
    """The vision model reads it (handwriting / hard photos): one call, picture shrunk to 1280 px. focus = a screen
    capture: read only the main content (the photo / paper / page), not the app around it."""
    from PIL import Image, ImageOps
    from jarvis.core import llm
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((1280, 1280))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80)
    b64 = base64.b64encode(buf.getvalue()).decode()
    r = llm.chat([{"role": "user", "content": [
        {"type": "text", "text": ("This is a screenshot. Read only the MAIN content: the photo, paper, handwriting or "
                                  "document in it, not menus, tabs, buttons, names or comments around it. "
                                  if focus else "") +
         "Write out exactly the text (handwriting too), keeping its lines, numbering and language (Nepali/Hindi in "
         "Devanagari). Only the text; '[?]' for a word you can't read."},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}],
        tier="vision", purpose="ocr_vision", max_tokens=1500)
    return Result((r.text or "").strip(), "vision", 100.0)


def looks_poor(r: Result, focus: bool = False) -> bool:
    """Tesseract wasn't sure: low mean confidence, many unsure words, hardly any words, or (a screen capture) very
    few words for its size: the main thing on screen is a photo / handwriting it can't see, and it only read the
    app around it (a Facebook photo of a handwritten page: 14 words/Mpx, all from the sidebar)."""
    words = re.findall(r"[^\W\d_]{2,}", r.text)
    sparse = focus and r.density < config.OCR_MIN_DENSITY
    return r.conf < config.OCR_MIN_CONF or r.unsure > 0.25 or len(words) < 2 or sparse


def read(src: Path, allow_vision: bool | None = None, focus: bool = False) -> Result:
    """Tesseract first; the vision model only when that looks poor (and it's allowed)."""
    r = tesseract(src)
    allow = config.OCR_VISION if allow_vision is None else allow_vision
    if looks_poor(r, focus) and allow:
        try:
            v = vision(src, focus)
            if v.text:
                return v
        except Exception as e:  # noqa: BLE001 - no AI (No AI mode, limit, offline): keep Tesseract's best try
            log.info("vision OCR failed: %s", e)
    return r


def copy(text: str) -> None:
    from jarvis.core import rewrite
    rewrite._xclip(["-selection", "clipboard"], text)


def run(source: str = "area", path: str = "") -> str:
    """source: window (what the user is looking at) | area (drag a box) | screen | clipboard |
    file (a path, or 'latest' = the newest picture in Downloads/Pictures)."""
    tmp = None
    if source == "file" and path.strip().lower() in ("", "this", "it", "photo", "picture", "image"):
        source, path = "window", ""  # "this photo" = the one on the screen, not an old file
    if source == "file" or path:
        if path and path.strip().lower() not in ("latest", "newest", "last"):
            from jarvis.core.paths import resolve_target
            p = resolve_target(path)
            if isinstance(p, str):
                return p
        else:
            p = latest_image()
            if p is None:
                return "I couldn't find a picture in Downloads, Pictures or Desktop."
    else:
        got = {"area": grab_area, "screen": grab_screen, "clipboard": grab_clipboard,
               "window": grab_window}.get(source, grab_area)()
        if isinstance(got, str):
            return got
        p = tmp = got
    if p.suffix.lower() not in IMAGE_EXT:
        return f"{p.name} isn't a picture. For a PDF say 'convert {p.name} to text'."
    try:
        r = read(p, focus=source in ("window", "screen"))
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    if not r.text.strip():
        return "I couldn't find any text in that picture."
    copy(r.text)
    how = " (read by the AI: handwriting/hard photo)" if r.engine == "vision" else ""
    unsure = " Some words may be wrong (blurry or handwriting)." if r.engine == "tesseract" and looks_poor(r) else ""
    return f"{r.text}\n\n(Copied{how}.{unsure})"
