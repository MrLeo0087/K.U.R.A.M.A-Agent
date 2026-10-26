"""Decode / prettify the highlighted text on this laptop, 0 tokens: JSON, JWT, base64, URL-encoding, query strings,
Unix timestamps, HTML entities, \\u escapes, XML, hex; and encode to base64 / URL. The result is copied too.
'auto' tries them in a safe order (the most specific first)."""
from __future__ import annotations

import base64
import binascii
import html
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import parse_qsl, quote, unquote_plus

MAX_IN = 200_000


def _printable(b: bytes) -> str | None:
    try:
        s = b.decode("utf-8")
    except UnicodeDecodeError:
        return None
    ok = sum(1 for ch in s if ch.isprintable() or ch in "\n\r\t")
    return s if s and ok / len(s) > 0.95 else None


def _b64(s: str) -> bytes | None:
    t = re.sub(r"\s+", "", s)
    if len(t) < 8 or not re.fullmatch(r"[A-Za-z0-9+/_-]+={0,2}", t):
        return None
    try:
        return base64.urlsafe_b64decode(t.replace("+", "-").replace("/", "_") + "=" * (-len(t) % 4))
    except (binascii.Error, ValueError):
        return None


def _when(ts: float) -> str:
    d = datetime.fromtimestamp(ts)
    ago = time.time() - ts
    rel = (f"{abs(ago) / 86400:.0f} days {'ago' if ago > 0 else 'from now'}" if abs(ago) >= 86400 else
           f"{abs(ago) / 3600:.1f} hours {'ago' if ago > 0 else 'from now'}")
    return (f"{d:%A, %d %B %Y, %I:%M:%S %p} (local) · "
            f"{datetime.fromtimestamp(ts, timezone.utc):%Y-%m-%d %H:%M:%S} UTC · {rel}")


def as_json(s: str) -> str | None:
    t = s.strip()
    if not t or t[0] not in "{[":
        return None
    try:
        return json.dumps(json.loads(t), indent=2, ensure_ascii=False)
    except ValueError:
        import ast
        try:  # a Python dict / list (single quotes, True/None)
            return json.dumps(ast.literal_eval(t), indent=2, ensure_ascii=False, default=str)
        except (ValueError, SyntaxError):
            return None


def as_jwt(s: str) -> str | None:
    t = s.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*", t):
        return None
    parts = []
    for name, seg in (("Header", t.split(".")[0]), ("Payload", t.split(".")[1])):
        raw = _b64(seg)
        try:
            data = json.loads(raw or b"")
        except ValueError:
            return None
        parts.append(f"{name}:\n{json.dumps(data, indent=2, ensure_ascii=False)}")
        if name == "Payload":
            for k in ("iat", "nbf", "exp"):
                if isinstance(data.get(k), (int, float)):
                    parts.append(f"{k}: {_when(data[k])}" + (" (EXPIRED)" if k == "exp" and data[k] < time.time() else ""))
    return "JWT (signature not checked)\n" + "\n".join(parts)


def as_timestamp(s: str) -> str | None:
    t = s.strip()
    if not re.fullmatch(r"\d{10}(?:\d{3})?(?:\.\d+)?", t):
        return None
    ts = float(t) / (1000 if len(t.split(".")[0]) == 13 else 1)
    return _when(ts)


def as_url(s: str) -> str | None:
    t = s.strip()
    if not re.search(r"%[0-9A-Fa-f]{2}", t) and not ("=" in t and "&" in t):
        return None
    dec = unquote_plus(t)
    query = dec.split("?", 1)[1] if "?" in dec else dec
    pairs = parse_qsl(t.split("?", 1)[1] if "?" in t else t, keep_blank_values=True)
    if len(pairs) >= 2 and "=" in query:
        head = dec.split("?", 1)[0] + "\n" if "?" in dec else ""
        return head + "\n".join(f"{k} = {v}" for k, v in pairs)
    return dec if dec != t else None


def as_base64(s: str) -> str | None:
    raw = _b64(s)
    if raw is None:
        return None
    text = _printable(raw)
    if text is not None:
        return as_json(text) or text
    kind = next((k for sig, k in ((b"\x89PNG", "a PNG image"), (b"\xff\xd8", "a JPEG image"), (b"%PDF", "a PDF"),
                                  (b"PK", "a ZIP/Office file"), (b"GIF8", "a GIF image")) if raw.startswith(sig)), "")
    return f"Binary data, {len(raw)} bytes{' (' + kind + ')' if kind else ''}." if kind else None


def as_unicode(s: str) -> str | None:
    if not re.search(r"\\u[0-9a-fA-F]{4}|\\x[0-9a-fA-F]{2}", s):
        return None
    try:
        return s.encode("latin-1", "backslashreplace").decode("unicode_escape")
    except UnicodeDecodeError:
        return None


def as_html(s: str) -> str | None:
    dec = html.unescape(s)
    return dec if dec != s and re.search(r"&(?:#\d+|#x[0-9a-f]+|[a-z]+);", s, re.I) else None


def as_xml(s: str) -> str | None:
    t = s.strip()
    if not (t.startswith("<") and t.endswith(">")) or t.count("<") < 2:
        return None
    from xml.dom import minidom
    try:
        pretty = minidom.parseString(t).toprettyxml(indent="  ")
    except Exception:  # noqa: BLE001 - not well-formed XML / HTML fragment
        return None
    return "\n".join(ln for ln in pretty.splitlines() if ln.strip() and not ln.startswith("<?xml"))


def as_hex(s: str) -> str | None:
    t = re.sub(r"[\s:]|0x", "", s.strip())
    if len(t) < 6 or len(t) % 2 or not re.fullmatch(r"[0-9a-fA-F]+", t) or t.isdigit():
        return None
    return _printable(bytes.fromhex(t))


ORDER = (("JSON", as_json), ("JWT", as_jwt), ("timestamp", as_timestamp), ("XML", as_xml), ("URL", as_url),
         ("unicode escapes", as_unicode), ("HTML entities", as_html), ("hex", as_hex), ("base64", as_base64))
MODES = {name.split()[0].lower(): fn for name, fn in ORDER}


def convert(text: str, mode: str = "auto") -> tuple[str, str] | None:
    """(what it was, the result) or None if nothing fits."""
    text = text[:MAX_IN]
    if mode == "encode_base64":
        return "text → base64", base64.b64encode(text.encode()).decode()
    if mode == "encode_url":
        return "text → URL encoding", quote(text, safe="")
    if mode in MODES:
        out = MODES[mode](text)
        return (mode, out) if out is not None else None
    for name, fn in ORDER:
        out = fn(text)
        if out is not None and out.strip() != text.strip():
            return name, out
    return None


def run(mode: str = "auto", text: str = "") -> str:
    from jarvis.core import rewrite
    if not text.strip():
        g = rewrite.grab()
        if isinstance(g, str):
            return g
        text = g.text
    got = convert(text, mode)
    if got is None:
        return ("I couldn't tell how this is encoded (tried JSON, JWT, timestamp, XML, URL, unicode, HTML, hex, "
                "base64)." if mode == "auto" else f"That doesn't look like {mode}.")
    kind, out = got
    rewrite._xclip(["-selection", "clipboard"], out)
    return f"{kind}:\n{out}\n(Copied.)"
