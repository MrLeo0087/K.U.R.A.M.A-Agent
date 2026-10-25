"""File converter: documents, images, audio/video, tables — all local, 0 tokens.

  images  jpg/png/webp/bmp/gif/tiff/ico <-> each other, images -> pdf     (Pillow)
  pdf     -> png/jpg pages (pdftoppm), -> txt (pdftotext), -> md (pdftotext + light structure), scanned -> OCR
  md/txt/html -> pdf (markdown -> HTML -> fpdf2, pure Python), md -> html, html -> md
  office  docx/doc/odt/pptx/xlsx/rtf <-> pdf/docx/odt (LibreOffice, if installed)
  media   mp4/mkv/mov/avi/webm/mp3/wav/m4a/ogg/flac/gif -> each other (ffmpeg)
  tables  csv <-> xlsx <-> json (openpyxl)
  ocr     image -> txt (tesseract)
A folder converts every file of the `src_ext` type inside it. Output goes next to the source, never overwriting.
"""
from __future__ import annotations

import csv
import html as _html
import json
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

IMAGES = {"jpg", "jpeg", "png", "webp", "bmp", "gif", "tiff", "tif", "ico"}
MEDIA = {"mp4", "mkv", "mov", "avi", "webm", "mp3", "wav", "m4a", "ogg", "flac", "aac", "opus"}
OFFICE = {"docx", "doc", "odt", "rtf", "pptx", "ppt", "odp", "xlsx", "xls", "ods"}
TABLES = {"csv", "xlsx", "json"}
TEXTS = {"md", "markdown", "txt", "html", "htm"}
_ALIAS = {"jpeg": "jpg", "tif": "tiff", "markdown": "md", "htm": "html", "word": "docx", "excel": "xlsx",
          "powerpoint": "pptx", "text": "txt", "image": "png", "picture": "png", "audio": "mp3", "video": "mp4",
          "music": "mp3", "sound": "mp3"}
_CSS = ("body{font-family:'DejaVu Sans',Arial,sans-serif;font-size:11pt;line-height:1.5;margin:18mm;color:#111}"
        "h1,h2,h3{line-height:1.25}code,pre{font-family:'DejaVu Sans Mono',monospace;font-size:9.5pt}"
        "pre{background:#f4f4f4;padding:8px;border-radius:4px;white-space:pre-wrap}"
        "table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:4px 8px}img{max-width:100%}")


class ConvertError(Exception):
    pass


def ext_of(name: str) -> str:
    e = name.lower().lstrip(".").strip()
    return _ALIAS.get(e, e)


def _out(src: Path, to: str) -> Path:
    out = src.with_suffix("." + to)
    n = 1
    while out.exists():
        out = src.with_name(f"{src.stem} ({n}).{to}")
        n += 1
    return out


def _run(argv: list[str], timeout: float = 600) -> subprocess.CompletedProcess:
    if not shutil.which(argv[0]):
        raise ConvertError(f"{argv[0]} is missing")
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        lines = (r.stderr or r.stdout or "").strip().splitlines()
        raise ConvertError(lines[-1][:200] if lines else f"{argv[0]} failed")
    return r


_FONTS = Path("/usr/share/fonts/truetype")


def _font(*names: str) -> Path | None:
    return next((p for n in names for p in _FONTS.rglob(n)), None)


# --- converters (each: src path, out path) ---
def _image(src: Path, out: Path) -> None:
    from PIL import Image
    with Image.open(src) as im:
        if out.suffix.lower() in (".jpg", ".jpeg", ".bmp", ".pdf") and im.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", im.size, "white")
            rgba = im.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[-1])
            im2 = bg
        else:
            im2 = im.copy()
        kw = {"quality": 92} if out.suffix.lower() in (".jpg", ".jpeg", ".webp") else {}
        if out.suffix.lower() == ".ico":
            kw = {"sizes": [(256, 256), (64, 64), (32, 32), (16, 16)]}
        im2.save(out, **kw)


def images_to_pdf(srcs: list[Path], out: Path) -> None:
    from PIL import Image
    pages = []
    for s in srcs:
        with Image.open(s) as im:
            pages.append(im.convert("RGB"))
    if not pages:
        raise ConvertError("no images")
    pages[0].save(out, save_all=True, append_images=pages[1:], resolution=150)


def _pdf_text(src: Path, layout: bool = False) -> str:
    r = _run(["pdftotext", *(["-layout"] if layout else []), str(src), "-"])
    return r.stdout


def _ocr_pdf(src: Path) -> str:
    with tempfile.TemporaryDirectory() as d:
        _run(["pdftoppm", "-r", "200", "-png", str(src), f"{d}/p"])
        parts = []
        for img in sorted(Path(d).glob("p*.png")):
            parts.append(_run(["tesseract", str(img), "-", "-l", _ocr_langs()]).stdout)
    return "\n\n".join(parts)


def _ocr_langs() -> str:
    try:
        have = set(subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True,
                                  timeout=10).stdout.split())
    except (OSError, subprocess.SubprocessError):
        have = set()
    return "+".join(x for x in ("eng", "nep", "hin") if x in have) or "eng"


def text_to_md(text: str) -> str:
    """pdftotext output -> readable Markdown: paragraphs re-joined, short title-ish lines as headings, bullets kept."""
    out, para = [], []

    def flush() -> None:
        if para:
            out.append(" ".join(para))
            para.clear()
    for raw in text.replace("\f", "\n\n").splitlines():
        line = raw.strip()
        if not line:
            flush()
            continue
        if re.match(r"^(?:[•●▪◦\-*–]|\d+[.)])\s+", line):
            flush()
            out.append(re.sub(r"^[•●▪◦*–]\s+", "- ", line))
            continue
        heading = (len(line) < 70 and not line.endswith((".", ",", ";", ":")) and len(line.split()) <= 10 and
                   (line.isupper() or re.match(r"^(?:\d+(?:\.\d+)*\s+)?[A-Z][^.]*$", line)) and not para)
        if heading:
            flush()
            level = "##" if line.isupper() or re.match(r"^\d+\s", line) else "###"
            out.append(f"{level} {line.title() if line.isupper() else line}")
            continue
        if para and para[-1].endswith("-"):
            para[-1] = para[-1][:-1] + line
        else:
            para.append(line)
    flush()
    return re.sub(r"\n{3,}", "\n\n", "\n\n".join(out)).strip() + "\n"


def pdf_to_md(src: Path) -> str:
    """PDF -> Markdown using poppler's XML (font sizes): bigger text -> headings, bullets -> lists, monospace ->
    code blocks, <b>/<i> kept, wrapped lines re-joined into paragraphs. '' if the PDF has no text layer."""
    import xml.etree.ElementTree as ET
    from collections import Counter
    xml = _run(["pdftohtml", "-xml", "-i", "-stdout", "-q", "-nodrm", str(src)]).stdout
    root = ET.fromstring(xml.encode("utf-8", "replace"))
    fonts = {f.get("id"): (float(f.get("size", 0)), f.get("family", "")) for f in root.iter("fontspec")}
    lines: list[dict] = []
    for page in root.iter("page"):
        for t in page.iter("text"):
            raw = "".join(t.itertext())
            if not raw.strip():
                continue
            inner = ET.tostring(t, encoding="unicode")
            inner = re.sub(r"^<text[^>]*>|</text>$", "", inner)
            inner = re.sub(r"</?b>", "**", re.sub(r"</?i>", "*", inner))
            inner = _html.unescape(re.sub(r"<[^>]+>", "", inner))
            size, fam = fonts.get(t.get("font"), (0.0, ""))
            if raw.strip() in ("•", "●", "▪", "◦", "‣", "–"):
                size = 0.0  # a big bullet glyph must not make its line look like a heading
            top, h = int(t.get("top", 0)), int(t.get("height", 0))
            key = (page.get("number"), top)
            if lines and lines[-1]["key"][0] == key[0] and abs(lines[-1]["key"][1] - top) <= 4:
                ln = lines[-1]
                ln["text"] += ("" if ln["text"].endswith(" ") else " ") + inner if inner.strip() else ""
                ln["size"], ln["chars"] = max(ln["size"], size), ln["chars"] + len(raw)
                ln["mono"] = ln["mono"] and "mono" in fam.lower()
            else:
                lines.append({"key": key, "top": top, "h": h, "text": inner, "size": size, "chars": len(raw),
                              "mono": "mono" in fam.lower() or "courier" in fam.lower(),
                              "page": page.get("number")})
    if not lines:
        return ""
    sizes = Counter()
    for ln in lines:
        sizes[round(ln["size"])] += ln["chars"]
    body = sizes.most_common(1)[0][0] or 12
    out: list[str] = []
    para: list[str] = []
    code: list[str] = []
    prev = None

    def flush() -> None:
        if para:
            out.append(re.sub(r"\*\*\s*\*\*", "", " ".join(para)).strip())
            para.clear()
        if code:
            out.append("```\n" + "\n".join(code) + "\n```")
            code.clear()
    for ln in lines:
        text = re.sub(r"\s+", " ", ln["text"]).strip()
        if not text:
            continue
        gap = (ln["top"] - prev["top"] - prev["h"]) if prev and prev["page"] == ln["page"] else 99
        prev = ln
        if ln["mono"]:
            if para:
                flush()
            code.append(ln["text"].rstrip())
            continue
        if code:
            flush()
        ratio = ln["size"] / body
        plain = text.replace("*", "").strip()
        if ratio >= 1.15 and len(plain) < 120 and plain not in ("•", "●"):
            flush()
            out.append(("#" if ratio >= 1.8 else "##" if ratio >= 1.4 else "###") + " " + plain)
            continue
        if bm := re.match(r"^(?:\*\*)?[•●▪◦‣–](?:\*\*)?\s*(.*)$", text):
            flush()
            para.append("- " + bm.group(1))
            continue
        if re.match(r"^\d+[.)]\s+\S", text) and len(text) < 300:
            flush()
            para.append(text)
            continue
        if para and gap > max(6, ln["h"] * 0.9):
            flush()
        if para and para[-1].endswith("-") and not para[-1].endswith(" -"):
            para[-1] = para[-1][:-1] + text
        else:
            para.append(text)
    flush()
    md = "\n\n".join(out)
    md = re.sub(r"\n\n(- )", r"\n\1", md)  # keep list items together
    return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"


def _pdf_to(src: Path, out: Path, to: str) -> list[Path]:
    if to in ("png", "jpg"):
        prefix = out.with_suffix("")
        _run(["pdftoppm", "-r", "150", "-png" if to == "png" else "-jpeg", str(src), str(prefix)])
        return sorted(prefix.parent.glob(prefix.name + "-*." + ("png" if to == "png" else "jpg")))
    if to == "md" and shutil.which("pdftohtml"):
        md = pdf_to_md(src)
        if len(md.strip()) >= 20:
            out.write_text(md, encoding="utf-8")
            return [out]
    text = _pdf_text(src, layout=(to == "txt"))
    if len(text.strip()) < 20:  # a scanned PDF: no text layer -> OCR
        text = _ocr_pdf(src)
    out.write_text(text_to_md(text) if to == "md" else text, encoding="utf-8")
    return [out]


def md_to_html(md_text: str, title: str = "") -> str:
    import markdown
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists", "toc"])
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{_html.escape(title)}</title>"
            f"<style>{_CSS}</style></head><body>{body}</body></html>")


def html_to_pdf(html_text: str, out: Path) -> None:
    """HTML (from Markdown) -> PDF with fpdf2 (pure Python). DejaVu for Unicode, Noto for Devanagari."""
    from fpdf import FPDF
    pdf = FPDF(format="A4")
    pdf.set_margins(18, 18, 18)
    pdf.set_auto_page_break(True, 18)
    family, mono = "helvetica", "courier"
    reg, bold = _font("DejaVuSans.ttf"), _font("DejaVuSans-Bold.ttf")
    if reg:
        family = "dejavu"
        for style, f in (("", reg), ("B", bold or reg), ("I", reg), ("BI", bold or reg)):
            pdf.add_font(family, style, str(f))
        if m := _font("DejaVuSansMono.ttf"):
            mono = "dejavumono"
            pdf.add_font(mono, "", str(m))
        if dev := _font("NotoSansDevanagari-Regular.ttf"):
            pdf.add_font("notodev", "", str(dev))
            pdf.add_font("notodev", "B", str(_font("NotoSansDevanagari-Bold.ttf") or dev))
            pdf.set_fallback_fonts(["notodev"], exact_match=False)
        try:  # proper Devanagari (Nepali/Hindi) vowel signs need shaping (uharfbuzz)
            pdf.set_text_shaping(True)
        except Exception:  # noqa: BLE001 - unshaped text is still readable
            pass
    pdf.add_page()
    pdf.set_font(family, size=11)
    body = re.sub(r"(?is)^.*?<body>|</body>.*$", "", html_text)
    from fpdf.fonts import FontFace
    styles = {h: FontFace(color=(20, 40, 80), emphasis="B", size_pt=pt)
              for h, pt in (("h1", 22), ("h2", 17), ("h3", 14), ("h4", 12))}
    pdf.write_html(body, font_family=family, pre_code_font=mono, li_prefix_color=(60, 60, 60),
                   warn_on_tags_not_matching=False, tag_styles=styles)
    pdf.output(str(out))


def _text_to(src: Path, out: Path, to: str) -> None:
    se = ext_of(src.suffix)
    raw = src.read_text(encoding="utf-8", errors="replace")
    if to == "html":
        page = md_to_html(raw if se == "md" else f"<pre>{_html.escape(raw)}</pre>", src.stem)
        out.write_text(raw if se == "html" else page, encoding="utf-8")
    elif to == "pdf":
        if se == "md":
            page = md_to_html(raw, src.stem)
        elif se == "txt":
            page = "".join(f"<p>{_html.escape(par)}</p>" for par in re.split(r"\n\s*\n", raw) if par.strip())
        else:
            page = raw
        html_to_pdf(page, out)
    elif to in ("md", "txt") and se == "html":
        txt = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", raw, flags=re.S | re.I)
        txt = re.sub(r"<h([1-6])[^>]*>(.*?)</h\1>", lambda m: "\n" + "#" * int(m.group(1)) + " " + m.group(2) + "\n",
                     txt, flags=re.S | re.I)
        txt = re.sub(r"<li[^>]*>", "\n- ", txt, flags=re.I)
        txt = re.sub(r"<(?:br|/p|/div)[^>]*>", "\n", txt, flags=re.I)
        out.write_text(_html.unescape(re.sub(r"<[^>]+>", "", txt)).strip() + "\n", encoding="utf-8")
    elif to in ("md", "txt"):
        out.write_text(raw, encoding="utf-8")
    else:
        raise ConvertError(f"{se} -> {to} isn't supported")


def _office(src: Path, out: Path, to: str) -> Path:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise ConvertError("Word/PowerPoint/Excel files need LibreOffice: sudo apt install -y libreoffice-writer "
                           "libreoffice-calc libreoffice-impress")
    with tempfile.TemporaryDirectory() as d:
        _run([soffice, "--headless", "--convert-to", to, "--outdir", d, str(src)], timeout=300)
        made = next(Path(d).glob("*." + to), None)
        if not made:
            raise ConvertError("LibreOffice couldn't convert it")
        shutil.move(str(made), out)
    return out


def _media(src: Path, out: Path, to: str) -> None:
    args = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src)]
    if to in ("mp3", "wav", "m4a", "ogg", "flac", "aac", "opus"):
        args += ["-vn"] + (["-q:a", "2"] if to == "mp3" else [])
    elif to == "gif":
        args += ["-vf", "fps=12,scale=640:-1:flags=lanczos", "-t", "30"]
    elif to == "mp4":
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-movflags", "+faststart"]
    _run([*args, str(out)], timeout=3600)


def _table(src: Path, out: Path, to: str) -> None:
    se = ext_of(src.suffix)
    if se == "csv":
        with open(src, newline="", encoding="utf-8", errors="replace") as f:
            rows = list(csv.reader(f))
    elif se == "xlsx":
        from openpyxl import load_workbook
        ws = load_workbook(src, read_only=True, data_only=True).active
        rows = [["" if v is None else v for v in r] for r in ws.iter_rows(values_only=True)]
    else:
        data = json.loads(src.read_text(encoding="utf-8"))
        data = data if isinstance(data, list) else [data]
        keys = list(dict.fromkeys(k for d in data if isinstance(d, dict) for k in d))
        rows = [keys] + [[d.get(k, "") for k in keys] for d in data if isinstance(d, dict)]
    if to == "csv":
        with open(out, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
    elif to == "xlsx":
        from openpyxl import Workbook
        wb = Workbook()
        for r in rows:
            wb.active.append(list(r))
        wb.save(out)
    else:
        head = [str(h) for h in rows[0]] if rows else []
        out.write_text(json.dumps([dict(zip(head, r)) for r in rows[1:]], ensure_ascii=False, indent=2, default=str),
                       encoding="utf-8")


def convert_one(src: Path, to: str) -> list[Path]:
    """Convert one file; returns the file(s) written. Raises ConvertError with a clear reason."""
    se, to = ext_of(src.suffix), ext_of(to)
    if se == to:
        raise ConvertError(f"it is already a .{to} file")
    out = _out(src, to)
    if se in IMAGES and (to in IMAGES or to == "pdf"):
        (_image if to != "pdf" else lambda s, o: images_to_pdf([s], o))(src, out)
    elif se in IMAGES and to == "txt":
        out.write_text(_run(["tesseract", str(src), "-", "-l", _ocr_langs()]).stdout, encoding="utf-8")
    elif se == "pdf" and to in ("png", "jpg", "txt", "md"):
        return _pdf_to(src, out, to)
    elif se == "pdf" and to in ("docx", "odt"):
        return [_office(src, out, to)]
    elif se in TEXTS and to in ("pdf", "html", "md", "txt"):
        _text_to(src, out, to)
    elif se in TABLES and to in TABLES:
        _table(src, out, to)
    elif se in OFFICE or (to in OFFICE and se in ("pdf", "md", "txt", "html", "odt", "docx")):
        return [_office(src, out, to)]
    elif (se in MEDIA or se == "gif") and (to in MEDIA or to == "gif"):
        _media(src, out, to)
    else:
        raise ConvertError(f".{se} -> .{to} isn't supported")
    return [out]


def convert(src: Path, to: str, src_ext: str = "") -> str:
    """Convert a file, or every `src_ext` file in a folder. Returns a short report."""
    to = ext_of(to)
    if src.is_dir():
        want = ext_of(src_ext) if src_ext else ""
        files = sorted(p for p in src.iterdir() if p.is_file() and (not want or ext_of(p.suffix) == want)
                       and ext_of(p.suffix) != to)
        if not files:
            return f"error: no {('.' + want + ' ') if want else ''}files to convert in {src}"
        if to == "pdf" and all(ext_of(p.suffix) in IMAGES for p in files):
            out = _out(src / src.name, "pdf")
            images_to_pdf(files, out)
            return f"Made one PDF from {len(files)} images: {out}"
        done, failed = [], []
        for f in files:
            try:
                done += convert_one(f, to)
            except (ConvertError, OSError, subprocess.SubprocessError) as e:
                failed.append(f"{f.name}: {e}")
        msg = f"Converted {len(files) - len(failed)} of {len(files)} files to .{to} in {src}."
        return msg + ("\nFailed: " + "; ".join(failed[:3]) if failed else "")
    try:
        outs = convert_one(src, to)
    except (ConvertError, OSError, subprocess.SubprocessError) as e:
        return f"error: couldn't convert {src.name}: {e}"
    if len(outs) == 1:
        return f"Converted to {outs[0]}"
    return f"Converted {src.name} into {len(outs)} files ({outs[0].name} ...) in {outs[0].parent}"
