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
                                "apply_code", "cancel_code", "reply", "summary", "ask", "more", "cancel_more", "use", "complete",
                                "answer_back", "use_yes", "use_no", "use_retry", "use_cancel", "file_ask", "file_yes", "file_no"] = "explain",
                request: str = "", lang: str = "", replace: bool = False, path: str = "",
                text: str = "") -> str:
    """Help with the selection.

    Args:
        action: explain (what it means), meaning (word -> meaning), translate, improve (rewrite/fix in place:
            grammar, formal, shorter, optimize/fix/format code), code (explain highlighted code), write (new code at
            the cursor; request says what), explain_file (path), apply_code / cancel_code (the user said yes / no to
            an improved code waiting in the workspace), reply (the user's next message in the selected/copied chat;
            request = what they want to say), summary (the main points of the highlighted text), ask (anything
            else about the highlighted code/text, e.g. pytest tests for it; request = the user's words), use (a small
            run block to use/run the highlighted code, added to the file), complete (finish unfinished code; asks
            first when unclear, then waits for yes).
        request: The user's words / instruction (e.g. "make it formal", "optimize this", "a calculator class").
        lang: Answer/translation language code (ne, hi, en, ja, fr...); empty = from the request.
        replace: translate only: put the translation in place of the selection.
        path: explain_file only: the file (name, path, or 'this' = the file open in VS Code).
        text: Explain/meaning/translate this typed text instead of the highlighted one.
    """
    from jarvis.core import assist
    if action in ("explain", "meaning", "translate", "summary", "ask") and not text.strip():
        read = _just_read(request)
        if isinstance(read, str):
            return read
        if read is not None:
            import re
            whole = re.search(r"\b(?:all|whole|full|complete|everything)\b",
                              f"{request} {safety_text()}", re.I)  # 'translate all of it': the whole text, anew
            if action in ("meaning", "translate") and read.get("english") and (lang or "en") == "en" and not (
                    whole and "Only the first part" in read["english"]):
                return f"{read['lang'] + ': ' if read.get('lang') else ''}{read['english']}"
            text = read["text"]
    out = assist.run(action, request, lang, replace, path, text)
    if action in ("explain", "code", "use") and not text and str(out).startswith("I couldn't see any highlighted text"):
        # nothing selected: 'how can I use it?' / 'explain this code' is about what KURAMA just gave (11-05: "I
        # couldn't see any highlighted text" right after 'set up colab notebook')
        from jarvis.core import trace
        from jarvis.tools.general.explain_self import explain_self
        q = request or str((trace.current() or {}).get("text") or "") or "how can I use what you just gave me?"
        return explain_self(q)
    return out


def safety_text() -> str:
    from jarvis.core import safety
    return str(safety.context().get("user_text") or "")


def _just_read(request: str):
    """'what is the meaning of this?' a moment after 'OCR my screen' = the text just read, not whatever is highlighted
    (11-06 it explained '04-17311', a highlighted file name). 'the SELECTED text' = the selection. A selection made
    after the read -> ask which. Returns the read (dict), a question (str) or None (use the selection as before)."""
    import re

    from jarvis.core import ocr, safety
    words = f"{safety.context().get('user_text') or ''} {request or ''}"
    if re.search(r"\b(?:select(?:ed|ion)?|highlight(?:ed)?|copied|clipboard)\b", words, re.I):
        return None
    read = ocr.last()
    if read is None:
        return None
    from jarvis.core import browsertab
    if browsertab.selection() and browsertab._SEL["ts"] > float(read.get("ts") or 0) + 2:
        return ("Do you mean the text I just read from the screen, or the text you highlighted after it? "
                "Say 'the screen text' or 'the selected text'.")
    return read


alias("rewrite_text", "text_assist", lambda a: {"action": "improve", "request": a.get("instruction", ""),
                                                 "text": ""})
