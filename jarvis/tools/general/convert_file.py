"""convert_file: convert a file (or every file of a type in a folder) to another format, locally (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


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
    from jarvis.core.paths import resolve_target
    src = resolve_target(path, src_ext)
    if isinstance(src, str):
        return src
    out = convert.convert(src, to, src_ext)
    if out.startswith("Converted to "):
        focus.set_path(out.removeprefix("Converted to ").strip())
    return out
