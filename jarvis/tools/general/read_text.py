"""read_text: OCR. Read the text in a screen area / the screen / a copied image / a picture file, copy it (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="screen", safety="safe", description="Read the text in a picture (OCR, handwriting too): what is on the "
      "screen in the window the user looks at, a part they drag a box around, a copied image or an image file. "
      "The text is copied to the clipboard.")
def read_text(source: Literal["window", "area", "screen", "clipboard", "file"] = "window", path: str = "") -> str:
    """OCR a picture.

    Args:
        source: window (the photo/page on the screen the user is looking at), area (the user drags a box around
            the part to read), screen (all of it), clipboard (a copied image) or file (an image file).
        path: the image file for source=file ('latest' = the newest picture in Downloads/Pictures).
    """
    from jarvis.core import ocr

    return ocr.run(source, path)
