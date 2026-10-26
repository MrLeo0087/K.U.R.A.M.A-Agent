"""scan_qr: read QR codes / barcodes on the screen, a dragged area, a copied image or a picture (0 tokens, safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="screen", safety="safe", description="Scan a QR code or barcode on the screen (or a dragged area, a copied "
      "image, a picture): show + copy its link/text; Wi-Fi codes copy the password; can open the link or join the Wi-Fi.")
def scan_qr(source: Literal["screen", "area", "clipboard", "file"] = "screen", path: str = "", open_link: bool = False,
            connect: bool = False) -> str:
    """Scan a QR code.

    Args:
        source: screen (whole screen), area (the user drags a box), clipboard (a copied image) or file.
        path: the picture for source=file ('this' = the newest picture).
        open_link: open the link in the browser.
        connect: join the Wi-Fi network of a Wi-Fi QR code.
    """
    from jarvis.core import qr

    return qr.run(source, path, open_link, connect)
