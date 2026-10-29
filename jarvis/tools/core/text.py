"""text: work on what the user selected or what is on screen: explain, meaning, translate, improve, summarize,
reply, write code; read the screen (OCR); clipboard history; dictation; scan a QR code (safe dispatcher)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool
from jarvis.tools.core._hub import Act, run


def _edit_request(a: dict) -> str:
    """The selected code when something is selected in VS Code, else the whole open file."""
    from jarvis.core import context
    req = (a.get("request") or "improve it").strip()
    return f"{req} (code)" if context.snapshot()["selection"] else f"{req} in this file"


def _assist(kind: str):
    return Act("text_assist", lambda a: {"action": kind, "request": a.get("request", ""), "lang": a.get("lang", "")})


TABLE = {
    "explain": _assist("explain"), "meaning": _assist("meaning"), "translate": _assist("translate"),
    "improve": _assist("improve"),
    "edit_code": Act("text_assist", lambda a: {"action": "improve", "request": _edit_request(a)}),
    "code_to_file": Act("code_to_file", lambda a: {"path": a.get("request", "") if "/" in a.get("request", "") or
                                                   a.get("request", "").endswith(".py") else ""}), "summary": _assist("summary"), "reply": _assist("reply"), "code": _assist("code"),
    "read_screen": Act("read_text", lambda a: {"source": a.get("request") if a.get("request") in ("area", "window", "screen") else "screen"}),
    "clipboard": Act("clipboard", lambda a: {"action": "history", "query": a.get("request", "")}),
    "copy": Act("clipboard", lambda a: {"action": "write", "text": a.get("request", "")}),
    "dictate": Act("dictate", lambda a: {"action": "stop" if (a.get("request") or "").lower() == "stop" else "start"}),
    "qr": Act("scan_qr", lambda a: {"source": "screen"}),
}


@tool(group="core", safety="safe",
      description="The selected text / screen: code_to_file (write the code KURAMA just generated into the file open "
                  "in VS Code, or the path in request; only code), edit_code (change the code in the file open in VS Code as asked: "
                  "'rename the columns to a,b,c,d', 'add a loop'; shows the change, replaces on yes, Ctrl+Z / backup), "
                  "explain, meaning, translate, improve (fix wording), summary, reply, code "
                  "(write code for it); read_screen (OCR); clipboard (what was copied, history); copy; dictate (start/stop "
                  "typing by voice); qr (scan a QR code).")
def text(action: Literal["code_to_file", "edit_code", "explain", "meaning", "translate", "improve", "summary", "reply", "code", "read_screen", "clipboard",
                         "copy", "dictate", "qr"], request: str = "", lang: str = "") -> str:
    """Selected text and screen.

    Args:
        action: What to do.
        request: Extra wish ('make it formal', 'in 3 lines'), the clipboard search, the text to copy, or 'stop' (dictate).
        lang: translate: target language (ne, hi, en...).
    """
    return run(TABLE, {"action": action, "request": request, "lang": lang})
