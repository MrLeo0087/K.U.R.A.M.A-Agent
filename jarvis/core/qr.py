"""Scan QR codes / barcodes on the screen, in a dragged area, a copied image or a picture file (zxing-cpp,
0 tokens). A link is shown and copied (opened only when asked: QR links can be traps), a Wi-Fi code gives the
network and puts its password on the clipboard (never in the chat or logs) and can connect, anything else is
shown and copied."""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("jarvis.qr")


def decode(path: Path) -> list[tuple[str, str]]:
    """[(format, text)] of every code in the picture."""
    import zxingcpp
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        im = (im.convert("RGBA") if im.mode == "P" else im).convert("L")  # palette PNGs (qrencode) warn otherwise
        found = zxingcpp.read_barcodes(im)
        if not found and max(im.size) < 1200:  # tiny codes on a big screen: try bigger
            found = zxingcpp.read_barcodes(im.resize((im.width * 2, im.height * 2)))
    return [(str(b.format).split(".")[-1], b.text) for b in found if b.text]


def _wifi(text: str) -> dict[str, str]:
    """WIFI:T:WPA;S:name;P:pass;; -> {'T':..., 'S':..., 'P':...} (backslash escapes kept right)."""
    body = text[5:]
    out, key, val, esc = {}, "", "", False
    field = True
    for ch in body:
        if esc:
            val += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif field and ch == ":":
            key, val, field = val, "", False
        elif ch == ";":
            if key:
                out[key] = val
            key, val, field = "", "", True
        else:
            val += ch
    return out


def _copy(text: str) -> None:
    from jarvis.core import rewrite
    rewrite._xclip(["-selection", "clipboard"], text)


def describe(fmt: str, text: str, open_link: bool, connect: bool) -> str:
    if text.upper().startswith("WIFI:"):
        w = _wifi(text)
        name, pw = w.get("S", "?"), w.get("P", "")
        if connect and shutil.which("nmcli"):
            args = ["nmcli", "dev", "wifi", "connect", name] + (["password", pw] if pw else [])
            r = subprocess.run(args, capture_output=True, text=True, timeout=45)
            return (f"Connected to the Wi-Fi '{name}'." if r.returncode == 0
                    else f"Couldn't connect to '{name}': {(r.stderr or r.stdout).strip()[:150]}")
        if pw:
            _copy(pw)
        return (f"Wi-Fi code: network '{name}'" + (", password copied to the clipboard" if pw else ", no password")
                + ". Say 'scan the qr and connect' to join it.")
    if re.match(r"https?://", text, re.I):
        _copy(text)
        if open_link:
            from jarvis.tools.general import open_url
            open_url._open(text)
            return f"Opened {text}"
        return f"Link: {text}\n(Copied. Say 'scan the qr and open it' to open it.)"
    _copy(text)
    kind = "barcode" if fmt not in ("QRCode", "MicroQRCode") else "QR code"
    return f"{kind}: {text}\n(Copied.)"


def run(source: str = "screen", path: str = "", open_link: bool = False, connect: bool = False) -> str:
    from jarvis.core import ocr
    tmp = None
    if source == "file" or path:
        if path and path.strip().lower() not in ("this", "it", "photo", "picture", "image"):
            from jarvis.core.paths import resolve_target
            p = resolve_target(path)
            if isinstance(p, str):
                return p
        else:
            p = ocr.latest_image()
            if p is None:
                return "I couldn't find a picture in Downloads, Pictures or Desktop."
    else:
        got = {"screen": ocr.grab_screen, "area": ocr.grab_area, "clipboard": ocr.grab_clipboard}.get(source,
                                                                                                  ocr.grab_screen)()
        if isinstance(got, str):
            return got
        p = tmp = got
    try:
        codes = decode(p)
    except Exception as e:  # noqa: BLE001
        log.warning("qr decode failed: %s", e)
        return f"I couldn't read that picture: {e}"
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    if not codes:
        where = "on the screen" if source == "screen" else "there"
        return f"I don't see a QR code {where}. Make it bigger, or say 'scan the qr in this area' and drag a box."
    if len(codes) == 1:
        return describe(*codes[0], open_link, connect)
    return f"{len(codes)} codes:\n" + "\n".join(f"{i}. {fmt}: {t}" for i, (fmt, t) in enumerate(codes, 1)
                                              if not t.upper().startswith("WIFI:")) + \
        ("\n(Wi-Fi codes found too: scan them one at a time.)" if any(t.upper().startswith("WIFI:") for _, t in codes) else "")
