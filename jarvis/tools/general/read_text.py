"""read_text: OCR. Read the text in a screen area / the screen / a copied image / a picture file, copy it (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="screen", safety="safe", description="Read the text in a picture (OCR, handwriting too): a screen area "
      "the user drags, the whole screen, a copied image or an image file. The text is copied to the clipboard.")
def read_text(source: Literal["area", "screen", "clipboard", "file"] = "area", path: str = "") -> str:
    """OCR a picture.

    Args:
        source: area (the user drags a box on the screen), screen (all of it), clipboard (a copied image) or
            file (an image file; empty path = the newest picture in Downloads/Pictures).
        path: the image file for source=file ('this' = the newest picture).
    """
    from jarvis.core import ocr

    return ocr.run(source, path)
