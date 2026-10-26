"""text_assist: one tool for highlighted text/code in any app and code in VS Code: explain, meaning (Nepali),
translate, improve/fix (in place), write code at the cursor, explain a file (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import alias, tool


@tool(group="clipboard", safety="safe",
      description="Work on the text/code the user highlighted in any app: explain it, a word's meaning, translate "
                  "(any language), improve/fix/optimize it in place, explain code, reply to a selected/copied chat; "
                  "or write new code at the cursor in VS Code; or explain a whole file.")
def text_assist(action: Literal["explain", "meaning", "translate", "improve", "code", "write", "explain_file",
                                "apply_code", "cancel_code", "reply"] = "explain",
                request: str = "", lang: str = "", replace: bool = False, path: str = "",
                text: str = "") -> str:
    """Help with the selection.

    Args:
        action: explain (what it means), meaning (word -> meaning), translate, improve (rewrite/fix in place:
            grammar, formal, shorter, optimize/fix/format code), code (explain highlighted code), write (new code at
            the cursor; request says what), explain_file (path), apply_code / cancel_code (the user said yes / no to
            an improved code waiting in the workspace), reply (the user's next message in the selected/copied chat;
            request = what they want to say).
        request: The user's words / instruction (e.g. "make it formal", "optimize this", "a calculator class").
        lang: Answer/translation language code (ne, hi, en, ja, fr...); empty = from the request.
        replace: translate only: put the translation in place of the selection.
        path: explain_file only: the file (name, path, or 'this' = the file open in VS Code).
        text: Explain/meaning/translate this typed text instead of the highlighted one.
    """
    from jarvis.core import assist
    return assist.run(action, request, lang, replace, path, text)


alias("rewrite_text", "text_assist", lambda a: {"action": "improve", "request": a.get("instruction", ""),
                                                 "text": ""})
