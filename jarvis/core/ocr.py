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
def _otsu(hist: list[int]) -> int:
    """Otsu's threshold from a 256-bin grey histogram (pure Python)."""
    total = sum(hist)
    sum_all = sum(i * h for i, h in enumerate(hist))
    best, cut, w0, s0 = 0.0, 127, 0, 0.0
    for t in range(256):
        w0 += hist[t]
        if w0 == 0 or w0 == total:
            continue
        s0 += t * hist[t]
        m0, m1 = s0 / w0, (sum_all - s0) / (total - w0)
        between = w0 * (total - w0) * (m0 - m1) ** 2
        if between > best:
            best, cut = between, t
    return cut


def _prepare(src: Path) -> Path:
    """Black text on white, big enough: grey -> light text on a dark background (videos, dark themes) is inverted
    -> upscaled so letters are ~30 px tall -> auto-contrast -> Otsu black/white (drops coloured pen marks and
    gradients). Tesseract was trained on exactly this."""
    from PIL import Image, ImageOps, ImageStat
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        rgb = im.convert("RGB")
        im = rgb.convert("L")
        sat = rgb.convert("HSV").split()[1]
        ink = sat.point(lambda v: 255 if v > 110 else 0)  # coloured pen / highlighter strokes (text is grey/black/white)
        if ImageStat.Stat(ink).mean[0] < 255 * 0.25:  # a little colour = pen marks; a colourful photo stays as it is
            hist = im.histogram()
            im.paste(hist.index(max(hist)), mask=ink)  # paint them in the background's colour
        if ImageStat.Stat(im).mean[0] < 110:
            im = ImageOps.invert(im)
        f = min(4.0, max(1.0, 2000 / max(im.size)))
        if f > 1.05:
            im = im.resize((int(im.width * f), int(im.height * f)), Image.LANCZOS)
        im = ImageOps.autocontrast(im, cutoff=1)
        cut = _otsu(im.histogram())
        im = im.point(lambda v: 255 if v > cut else 0)
        out = _tmp()
        im.save(out)
    return out


_BULLET = re.compile(r"^(?:[¢©°•●◦▪■□oe*«»>-]|0|o0|oo)\s+(?=\S)")


def tidy(text: str) -> str:
    """Tesseract's bullets ('¢ ', '© ', '° ', 'e ', '0 ') -> '• ', lines that are only symbols dropped, spaces fixed."""
    out = []
    for ln in text.splitlines():
        ln = _BULLET.sub("• ", ln.strip())
        ln = re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"\s{2,}", " ", ln))
        if ln and (not re.search(r"[^\W_]{2,}|\d", ln) or re.fullmatch(r"[oO0°•.\s]+", ln)):
            continue  # symbol-only lines, a column of small bullets read as 'oo000'
        out.append(ln)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def tesseract(src: Path, langs: str = "") -> Result:
    """0 tokens. Text in reading order + the mean word confidence (0-100)."""
    if not shutil.which("tesseract"):
        return Result("", "none", 0.0)
    from PIL import Image
    with Image.open(src) as im:
        mpx = max(0.05, im.width * im.height / 1e6)
    img = _prepare(src)
    langs = langs or config.OCR_LANGS
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
        word = c[11]
        if conf < 35 or not re.search(r"[^\W_]", word) and not re.fullmatch(r"[-–—=+*/<>{}()\[\]→←|&%$#@!?.,:;\"']{1,3}", word):
            word = ""  # pen strokes / specks read as 'oo000', '—_—', 'QUW'
        lines.setdefault((int(c[2]), int(c[3]), int(c[4])), []).append(word)  # block, paragraph, line
    out, last_par = [], None
    lines = {k: ws for k, ws in ((k, [w for w in ws if w]) for k, ws in lines.items()) if ws}
    for (b, p, _), words in lines.items():
        if last_par is not None and (b, p) != last_par:
            out.append("")  # a blank line between paragraphs
        out.append(" ".join(words))
        last_par = (b, p)
    text = tidy("\n".join(out).strip())
    unsure = sum(1 for c in confs if c < 70) / len(confs) if confs else 1.0  # handwriting / noise: many unsure words
    return Result(text, "tesseract", sum(confs) / len(confs) if confs else 0.0, unsure, len(confs) / mpx)


def vision(src: Path, focus: bool = False) -> Result:
    """The vision model reads it: one call. Small crops are enlarged (the model reads small letters badly), big
    pictures kept up to 1600 px. focus = a window/screen capture: only the main content, not the app around it."""
    from PIL import Image, ImageOps
    from jarvis.core import llm
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        if max(im.size) < 900:
            f = min(3.0, 1200 / max(im.size))
            im = im.resize((int(im.width * f), int(im.height * f)), Image.LANCZOS)
        im.thumbnail((1600, 1600))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
    b64 = base64.b64encode(buf.getvalue()).decode()
    ask = (("This is a screenshot: read only the MAIN content (the page, slide, photo, paper or handwriting), not "
            "menus, tabs, buttons, player controls, names or comments around it. " if focus else
            "This is ONE picture cut from the user's screen (a page, slide, video frame, photo or handwriting). ") +
           "Transcribe ALL of its text exactly as written, top to bottom: keep headings, line breaks, bullets, "
           "numbering, code and symbols (→, ε, {}) as they are; a table row per line. Handwritten words and notes "
           "too; ignore drawings and pen marks that are not words. Nepali/Hindi in Devanagari. Do not describe the "
           "picture, do not split it into parts, do not add anything. '[?]' for a word you can't read.")
    r = llm.chat([{"role": "user", "content": [
        {"type": "text", "text": ask},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}],
        tier="vision", purpose="ocr_vision", max_tokens=2000)
    return Result((r.text or "").strip(), "vision", 100.0)


def _english_ratio(text: str) -> float:
    """Share of the letter-words (3+ letters) that are real English words (/usr/share/dict). Tesseract garbage
    from a video frame ('AOF.INE! WOR FOrtis a er eres Cy aS om') scores low even when its confidence is high."""
    raw = re.findall(r"[A-Za-z]{3,}", text)
    if not raw:
        return 0.0
    vocab = _vocab()
    if not vocab:
        return 1.0

    def real(w: str) -> bool:
        if re.search(r"[a-z][A-Z]|^[A-Z]{2,}[a-z]", w) and not re.fullmatch(r"[A-Z][a-z]+(?:[A-Z][a-z]+)+", w):
            return False  # 'FOrtis', 'aS': case junk (CamelCase like 'ModelView' is fine)
        lw = w.lower()
        if lw in vocab or (w.isupper() and len(w) <= 6):  # acronyms: HTML, ASP, MVC
            return True
        stem = re.sub(r"(?:ing|ed|es|s|ly|er|est)$", "", lw)
        return len(stem) >= 3 and (stem in vocab or stem + "e" in vocab)
    return sum(1 for w in raw if real(w)) / len(raw)


def _vocab() -> set[str]:
    """~100k English words, read when needed (~60 ms) and not kept: ~8 MB stays free between reads."""
    for f in ("/usr/share/dict/words", "/usr/share/dict/american-english", "/usr/share/dict/british-english"):
        try:
            return {w.strip().lower() for w in Path(f).read_text(errors="ignore").split() if w.isalpha()}
        except OSError:
            continue
    return set()


def looks_poor(r: Result, focus: bool = False) -> bool:
    """Tesseract can't be trusted here: low mean confidence, many unsure words, hardly any words, not real English
    (a video frame read as garbage), mixed-up scripts, or (a screen capture) very few words for its size: the main
    thing on screen is a photo / handwriting it can't see (a Facebook photo of a handwritten page: 14 words/Mpx)."""
    words = re.findall(r"[^\W\d_]{2,}", r.text)
    if r.conf < config.OCR_MIN_CONF or r.unsure > 0.15 or len(words) < 3 or (focus and r.density < config.OCR_MIN_DENSITY):
        return True
    latin = len(re.findall(r"[A-Za-z]", r.text))
    deva = len(re.findall(r"[\u0900-\u097F]", r.text))
    if latin and deva and min(latin, deva) / (latin + deva) > 0.03:
        return True  # 'र ४ W ४ | Vv.' in an English slide: Tesseract guessing
    return latin > deva and _english_ratio(r.text) < config.OCR_MIN_ENGLISH


def read(src: Path, allow_vision: bool | None = None, focus: bool = False) -> Result:
    """Accuracy first: Tesseract (free) only when its result is clean English (or clean Nepali); anything doubtful
    goes to the vision model (one call, ~1-3k tokens)."""
    r = tesseract(src, "eng")
    if not looks_poor(r, focus):
        return r
    if "nep" in config.OCR_LANGS:
        n = tesseract(src, "nep")  # a Nepali document: Devanagari words Tesseract is sure about
        if len(re.findall(r"[\u0900-\u097F]", n.text)) > 40 and n.conf >= 80 and n.unsure <= 0.1:
            return n
    allow = config.OCR_VISION if allow_vision is None else allow_vision
    if allow:
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
    how = " by the AI" if r.engine == "vision" else ""
    unsure = " Some words may be wrong." if r.engine == "tesseract" and looks_poor(r) else ""
    return f"{r.text}\n\n(Copied{how}.{unsure})"
