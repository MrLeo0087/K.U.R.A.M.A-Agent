"""convert_file: convert a file (or every file of a type in a folder) to another format, locally (safe)."""
from __future__ import annotations

from pathlib import Path

from jarvis.core.registry import tool


def _resolve(name: str, src_ext: str) -> Path | str:
    """A path, 'this'/'it' (the file we were just talking about, else the newest matching file in Downloads),
    or a file/folder NAME found anywhere. Returns the Path or an error string."""
    from jarvis.core import convert, focus
    from jarvis.core.paths import smart_path
    raw = (name or "").strip().strip("'\"")
    want = convert.ext_of(src_ext) if src_ext else ""
    if not raw or focus.is_anaphora(raw) or raw.lower() in ("this " + want, "that " + want, want):
        if (fp := focus.get_path()) and Path(fp).exists() and (not want or Path(fp).is_dir()
                                                               or convert.ext_of(Path(fp).suffix) == want):
            return Path(fp)
        dl = Path.home() / "Downloads"
        files = sorted((p for p in dl.glob("*") if p.is_file() and (not want or convert.ext_of(p.suffix) == want)),
                       key=lambda p: p.stat().st_mtime, reverse=True) if dl.is_dir() else []
        return files[0] if files else f"error: which {want or ''} file? Give its name or path."
    p = Path(raw).expanduser()
    if p.exists():
        return p
    if hit := smart_path(raw):
        return hit
    from jarvis.tools.general.find_and_send import search
    stem_hits = search(raw) or (search(f"{raw}.{want}") if want else [])
    if want:
        stem_hits = [h for h in stem_hits if convert.ext_of(h.suffix) == want] or stem_hits
    return stem_hits[0] if stem_hits else f"error: I couldn't find '{raw}'."


@tool(group="files", safety="safe",
      description="Convert files locally: pdf<->md/txt/images/docx, md/txt/html->pdf, jpg<->png/webp/ico, "
                  "images->pdf, docx/pptx/xlsx->pdf, mp4->mp3/gif, mov/mkv->mp4, csv<->xlsx<->json, image->text (OCR). "
                  "A folder converts all its files of src_ext.")
def convert_file(path: str = "", to: str = "", src_ext: str = "") -> str:
    """Convert a file.

    Args:
        path: The file or folder (a path, a name to find, or 'this' for the file just mentioned/newest download).
        to: Target format: pdf, md, txt, html, png, jpg, webp, ico, docx, mp3, mp4, gif, csv, xlsx, json ...
        src_ext: For a folder (or 'this pdf'): which files to convert, e.g. jpg.
    """
    from jarvis.core import convert, focus
    if not to.strip():
        return "error: convert it to which format?"
    src = _resolve(path, src_ext)
    if isinstance(src, str):
        return src
    out = convert.convert(src, to, src_ext)
    if out.startswith("Converted to "):
        focus.set_path(out.removeprefix("Converted to ").strip())
    return out
