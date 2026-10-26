"""decode_text: decode / prettify the highlighted text locally (JSON, JWT, base64, URL, timestamp...), 0 tokens (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="devutils", safety="safe", description="Decode or prettify the highlighted text, 0 tokens: JSON, JWT, "
      "base64, URL encoding, Unix timestamp, HTML entities, unicode escapes, XML, hex; or encode to base64 / URL.")
def decode_text(mode: Literal["auto", "json", "jwt", "base64", "url", "timestamp", "html", "unicode", "xml", "hex",
                              "encode_base64", "encode_url"] = "auto", text: str = "") -> str:
    """Decode / prettify text.

    Args:
        mode: auto (detect), a specific format, or encode_base64 / encode_url.
        text: the text; empty = the highlighted text.
    """
    from jarvis.core import decode

    return decode.run(mode, text)
