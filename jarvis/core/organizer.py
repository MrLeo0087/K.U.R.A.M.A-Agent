"""Smart file organizer: rename and sort a messy folder (Downloads by default) by what is INSIDE the files.

  1. 0 tokens: category by type (Documents, Images, Screenshots, Videos, Audio, Archives, Code, Installers, ...).
  2. Only files with meaningless names (IMG_2031.jpg, doc(3).pdf, Screenshot from ..., download.pdf) get looked at:
     the first page of a PDF / start of a text file, and pictures get one short look by the vision model
     (max config.ORGANIZE_MAX_IMAGES per run).
  3. ONE fast-LLM call turns those clues into short descriptive names and an optional topic subfolder.
Nothing moves until the user says yes (safety.ask) to the plan; every run writes an undo file, and
"undo organize" puts everything back where it was.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
import subprocess
import time
import zipfile
from pathlib import Path

from pydantic import BaseModel, Field

from jarvis.core import config

log = logging.getLogger(__name__)
CATS = {
    "Documents": {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".epub"},
    "Spreadsheets": {".xls", ".xlsx", ".ods", ".csv"},
    "Presentations": {".ppt", ".pptx", ".odp", ".key"},
    "Images": {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".svg", ".tiff"},
    "Videos": {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv"},
    "Audio": {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz"},
    "Code": {".py", ".ipynb", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".html", ".css", ".json", ".yaml",
             ".yml", ".sh", ".sql", ".r", ".go", ".rs"},
    "Installers": {".deb", ".appimage", ".rpm", ".run", ".exe", ".msi", ".snap", ".flatpak"},
}
_MEANINGLESS = re.compile(
    r"^(?:img|image|dsc|dscn|pxl|photo|pic|vid|video|mvimg|screenshot|screen ?shot|scan|doc|document|file|download|"
    r"untitled|new|copy|whatsapp (?:image|video)|signal-|telegram|output|unnamed|temp|tmp)?[\s_\-]*"
    r"(?:from\s+)?[\d\s_\-:.()at]*(?:\(\d+\))?$|^[0-9a-f]{8,}(?:-[0-9a-f]{4,})*$|^\d{6,}[_-]?\d*$", re.I)
_PARTIAL = (".crdownload", ".part", ".download", ".tmp")
UNDO_DIR = "organize_undo"


class Name(BaseModel):
    i: int
    name: str = Field(description="short descriptive file name WITHOUT extension, 2-6 words, keep a date if the "
                                  "file had one")
    topic: str = Field("", description="optional topic folder (1-2 words, e.g. College, Bills, ML, Travel), "
                                       "'' if none fits")


class Names(BaseModel):
    files: list[Name] = Field(default_factory=list)


def category(p: Path) -> str:
    ext = p.suffix.lower()
    if ext in CATS["Images"] and re.search(r"screen\s*shot|screenshot", p.name, re.I):
        return "Screenshots"
    return next((c for c, exts in CATS.items() if ext in exts), "Other")


def meaningless(p: Path) -> bool:
    return bool(_MEANINGLESS.match(p.stem.strip()))


def _snippet(p: Path) -> str:
    ext = p.suffix.lower()
    try:
        if ext == ".pdf":
            return subprocess.run(["pdftotext", "-l", "1", "-q", str(p), "-"], capture_output=True, text=True,
                                  timeout=15).stdout[:400]
        if ext in (".txt", ".md", ".csv", ".py", ".json", ".html"):
            return p.read_text(errors="replace")[:400]
        if ext in (".docx", ".pptx", ".xlsx"):
            with zipfile.ZipFile(p) as z:
                part = next((n for n in z.namelist() if n in ("word/document.xml", "ppt/slides/slide1.xml",
                                                                 "xl/sharedStrings.xml")), None)
                return re.sub(r"<[^>]+>", " ", z.read(part).decode(errors="replace"))[:400] if part else ""
    except Exception as e:  # noqa: BLE001 - no clue just means "keep the name"
        log.info("snippet failed for %s: %s", p.name, e)
    return ""


def _caption(p: Path) -> str:
    """One short look at a picture by the vision model (~600 tokens)."""
    try:
        from PIL import Image
        from jarvis.core import llm
        with Image.open(p) as im:
            im = im.convert("RGB")
            im.thumbnail((768, 768))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=70)
        b64 = base64.b64encode(buf.getvalue()).decode()
        r = llm.chat([{"role": "user", "content": [
            {"type": "text", "text": "In under 12 words, what is this picture of? If it is a screenshot, say of what "
                                     "app/page/error. Plain words only."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}],
            tier="vision", purpose="organize_caption", max_tokens=40)
        return (r.text or "").strip()[:120]
    except Exception as e:  # noqa: BLE001
        log.info("caption failed for %s: %s", p.name, e)
        return ""


def _free(dest: Path) -> Path:
    n, out = 1, dest
    while out.exists():
        out = dest.with_name(f"{dest.stem} ({n}){dest.suffix}")
        n += 1
    return out


def _clean(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|\n\r\t]+", " ", name).strip(" .")
    return re.sub(r"\s+", " ", name)[:80]


def plan(folder: Path, rename: bool = True) -> list[tuple[Path, Path]]:
    files = sorted((p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")
                    and not p.name.lower().endswith(_PARTIAL)), key=lambda p: p.stat().st_mtime, reverse=True)
    files = files[: config.ORGANIZE_MAX_FILES]
    clues: list[dict] = []
    images = 0
    for i, p in enumerate(files):
        if not rename or not meaningless(p):
            continue
        clue = _snippet(p)
        if not clue and p.suffix.lower() in CATS["Images"] and images < config.ORGANIZE_MAX_IMAGES:
            clue, images = _caption(p), images + 1
        if clue.strip():
            clues.append({"i": i, "name": p.name, "clue": " ".join(clue.split())[:300]})
    names: dict[int, Name] = {}
    if clues:
        from jarvis.core import llm
        try:
            got = llm.structured([{"role": "system", "content": "Give each file a short, clear, human file name from "
                                                                 "its clue, and an optional topic folder."},
                                  {"role": "user", "content": json.dumps(clues, ensure_ascii=False)}],
                                 Names, tier="fast", purpose="organize", max_tokens=1200)
            names = {n.i: n for n in got.files}
        except Exception as e:  # noqa: BLE001 - still sort by type without new names
            log.warning("organize naming failed: %s", e)
    moves = []
    taken: set[Path] = set()
    for i, p in enumerate(files):
        sub = folder / category(p)
        n = names.get(i)
        if n and _clean(n.topic) and category(p) not in ("Installers", "Archives"):
            sub = sub / _clean(n.topic).title()
        stem = _clean(n.name) if n and _clean(n.name) else p.stem
        if n and (dm := re.search(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})", p.stem)) and dm.group(1) not in stem:
            stem = f"{stem} {dm.group(1)}-{dm.group(2)}-{dm.group(3)}"  # keep the photo/scan date
        dest = _free(sub / f"{stem}{p.suffix.lower() if n else p.suffix}")
        while dest in taken:
            dest = dest.with_name(f"{dest.stem}_{len(taken)}{dest.suffix}")
        taken.add(dest)
        if dest != p:
            moves.append((p, dest))
    return moves


def describe(moves: list[tuple[Path, Path]], folder: Path, k: int = 15) -> str:
    lines = [f"{a.name} -> {b.relative_to(folder)}" for a, b in moves[:k]]
    more = f"\n... and {len(moves) - k} more" if len(moves) > k else ""
    return "\n".join(lines) + more


def apply(moves: list[tuple[Path, Path]]) -> Path:
    done = []
    for a, b in moves:
        if not a.exists():
            continue
        b.parent.mkdir(parents=True, exist_ok=True)
        b = _free(b)
        a.rename(b)
        done.append([str(a), str(b)])
    d = Path(config.DATA_DIR) / UNDO_DIR
    d.mkdir(parents=True, exist_ok=True)
    undo = d / f"{int(time.time())}.json"
    undo.write_text(json.dumps(done))
    return undo


def undo_last() -> str:
    d = Path(config.DATA_DIR) / UNDO_DIR
    logs = sorted(d.glob("*.json")) if d.is_dir() else []
    if not logs:
        return "There is nothing to undo."
    pairs = json.loads(logs[-1].read_text())
    back = 0
    for a, b in reversed(pairs):
        src, dst = Path(b), Path(a)
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            back += 1
    for _, b in pairs:  # remove the folders the organizer made, if they are empty now
        for parent in (Path(b).parent, Path(b).parent.parent):
            try:
                parent.rmdir()
            except OSError:
                pass
    logs[-1].unlink()
    return f"Put {back} of {len(pairs)} files back where they were."
