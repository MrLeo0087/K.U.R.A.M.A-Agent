"""Help with whatever is highlighted in any app (one tool, several jobs), plus code in VS Code:

  READ (the answer comes to the chat; the selection is not touched)
    explain    what a sentence / paragraph / question means, in simple words (or in Nepali/Hindi if asked)
    meaning    a word or phrase -> its meaning in Nepali (default), part of speech, a short example
    translate  to Nepali / Hindi / English (the translation is also put on the clipboard)
    code       a highlighted function / code -> what it does, step by step
  WRITE (pasted over the selection, or at the cursor)
    improve    text: fix / formal / shorter ...   code: fix, optimize, format, add comments (keeps indentation)
    write      "write a calculator here" -> new code at the cursor, in the language of the open file
    translate with replace=True puts the translation in place of the selection
  explain_file: explain a whole file (path / name / 'this file' = the file open in VS Code)

The selection is copied from the app itself (rewrite.grab), pasted back with rewrite.put. Code and Nepali/Hindi use
the smart model (accuracy), simple English the fast one. One LLM call per request.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from jarvis.core import config, rewrite

log = logging.getLogger(__name__)
LANGS = {"ne": "Nepali (Devanagari script)", "hi": "Hindi (Devanagari script)", "en": "English"}
_CODE_HINT = re.compile(r"(?m)^\s*(?:def |class |import |from \S+ import|function |const |let |var |public |private |"
                        r"#include|for\s*\(|if\s*\(|while\s*\(|return\b|async |@\w+)|[{};]\s*$|=>|::|\)\s*:\s*$")
_EXT_LANG = {".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".jsx": "React JSX", ".tsx": "React TSX",
             ".java": "Java", ".c": "C", ".cpp": "C++", ".h": "C/C++ header", ".cs": "C#", ".go": "Go", ".rs": "Rust",
             ".php": "PHP", ".rb": "Ruby", ".kt": "Kotlin", ".swift": "Swift", ".html": "HTML", ".css": "CSS",
             ".sql": "SQL", ".sh": "Bash", ".ipynb": "Python", ".dart": "Dart", ".r": "R", ".md": "Markdown"}


def lang_of(text: str) -> str:
    """'nepali' / 'hindi' / 'english' mentioned (or Devanagari typed) -> ne / hi / en; '' if none."""
    t = (text or "").lower()
    if re.search(r"\bnepali\b|नेपाली", t):
        return "ne"
    if re.search(r"\bhindi\b|हिन्दी|हिंदी", t):
        return "hi"
    if re.search(r"\benglish\b|अंग्रेजी", t):
        return "en"
    return ""


def _short(title: str) -> str:
    """'● test.py - KURAMA - Claude-1 - Visual Studio Code' -> 'test.py' (something a voice can say)."""
    first = re.sub(r"^[●•\s]+", "", (title or "").split(" - ")[0]).strip()
    return first or "that window"


def is_code(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    hits = len(_CODE_HINT.findall(text))
    return hits >= 2 or (hits >= 1 and len(lines) <= 3 and bool(re.search(r"[(){}\[\]=]", text)))


def _llm(system: str, user: str, smart: bool, max_tokens: int, purpose: str) -> str:
    from jarvis.core import llm
    reply = llm.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                     tier="smart" if smart else "fast", purpose=purpose, max_tokens=max_tokens)
    return re.sub(r"【[^】]*】", "", (reply.text or "")).strip()


def _strip_fence(code: str) -> str:
    m = re.search(r"```[\w+-]*\n(.*?)```", code, re.S)
    return (m.group(1) if m else code).rstrip("\n")


# --- the jobs -----------------------------------------------------------------------------------------------
def explain(text: str, lang: str = "") -> str:
    out = LANGS.get(lang or "en", "English")
    if is_code(text):
        return explain_code(text, lang)
    return _llm(f"Explain what the user's selected text means, for a learner who isn't a native English speaker: "
                f"what it is really saying, in simple words, then any hard word briefly. Reply in {out}. Short "
                f"(2-6 sentences) unless the text is long.", text[:6000], smart=lang in ("ne", "hi"),
                max_tokens=700, purpose="assist_explain")


def meaning(text: str, lang: str = "ne") -> str:
    out = LANGS.get(lang or "ne", "Nepali (Devanagari script)")
    words = len(text.split())
    if words <= 4:
        sys = (f"Dictionary entry for the user's English word/phrase in {out}: the meaning(s) in {out} (most common "
               f"first), the part of speech, and ONE short English example sentence with its {out} translation. "
               f"Compact, no extra talk.")
    else:
        sys = f"Give the exact meaning of the user's sentence in {out}, naturally, then 1 line on any hard word."
    return _llm(sys, text[:3000], smart=True, max_tokens=500, purpose="assist_meaning")


def translate(text: str, lang: str = "ne") -> str:
    out = LANGS.get(lang or "ne", "Nepali (Devanagari script)")
    return _llm(f"Translate the user's text into {out}. Natural, accurate, everyday language as people really speak "
                f"and write it (for Nepali: Nepal's Nepali, not Hindi words); keep names, code and technical terms "
                f"as they are; same meaning and formatting. Output ONLY the translation.", text[:6000], smart=True, max_tokens=min(3000, len(text) + 400),
                purpose="assist_translate")


def explain_code(code: str, lang: str = "", name: str = "") -> str:
    out = LANGS.get(lang or "en", "English")
    return _llm(f"Explain this code to a student, in {out}: first one line on what it does overall, then the "
                f"important steps in order (short bullet lines), then any bug or risk you notice. Plain text, no "
                f"code blocks unless a tiny snippet helps.", (f"File: {name}\n" if name else "") + code[:12000],
                smart=True, max_tokens=1200, purpose="assist_code_explain")


def improve_code(code: str, instruction: str, lang_name: str = "") -> str:
    """Fixed / optimized / formatted code, same indentation, ONLY the code."""
    first = next((ln for ln in code.splitlines() if ln.strip()), "")
    indent = first[: len(first) - len(first.lstrip())]
    got = _llm("You edit code. Apply the user's instruction to their selected code and return ONLY the full new "
               "code (no explanation, no markdown fences). Keep the same behaviour unless asked, the same names "
               "used by other code, and the same indentation level." + (f" Language: {lang_name}." if lang_name else ""),
               f"Instruction: {instruction}\n\nCode:\n{code[:12000]}", smart=True,
               max_tokens=min(4000, len(code) // 2 + 800), purpose="assist_code_fix")
    new = _strip_fence(got)
    if indent and new and not new.startswith(indent):  # the model dropped the block's indentation: put it back
        new = "\n".join(indent + ln if ln.strip() else ln for ln in new.splitlines())
    return new


def open_file_in_editor() -> Path | None:
    """The file open in the front VS Code / editor window: '<name> - <folder> - Visual Studio Code'."""
    from jarvis.core import rewrite as rw
    wid, _ = rw.target_window()
    title = rw._window_name(wid) if wid else ""
    m = re.match(r"^[●•\s]*(?P<f>[^/\\]+?\.\w{1,8})\s+-\s+(?P<d>[^-]+?)\s+-\s+.*Visual Studio Code", title)
    if not m:
        return None
    from jarvis.core.paths import smart_path
    return smart_path(f"{m.group('d').strip()}/{m.group('f').strip()}", want="file")


def write_code(request: str) -> str:
    """New code at the cursor of the front editor, in that file's language, with the file around it as context."""
    f = open_file_in_editor()
    lang_name = _EXT_LANG.get(f.suffix.lower(), "") if f else ""
    context = ""
    if f and f.is_file() and f.stat().st_size < 400_000:
        context = f.read_text(errors="replace")[:6000]
    code = _strip_fence(_llm(
        "You write code to insert at the user's cursor. Return ONLY the code (no explanation, no markdown fences), "
        "complete and runnable, matching the existing file's style and imports."
        + (f" Language: {lang_name}." if lang_name else " Infer the language from the request."),
        f"Request: {request}\n\n" + (f"The file ({f.name}) so far:\n{context}" if context else ""),
        smart=True, max_tokens=3000, purpose="assist_write_code"))
    if not code.strip():
        return "error: no code came back"
    g = rewrite.grab_cursor()
    if isinstance(g, str):
        return g + "\n\n" + code
    rewrite.put(g, code + "\n")
    lines = code.count("\n") + 1
    return (f"Wrote {lines} lines of {lang_name or 'code'} at your cursor in {_short(g.title)}. Control Z in the "
            f"editor undoes it.")


def explain_file(path: Path, lang: str = "") -> str:
    if not path.is_file():
        return f"error: {path} isn't a file"
    if path.stat().st_size > 2_000_000:
        return f"{path.name} is too big to explain in one go; select the part you want explained."
    text = path.read_text(errors="replace")
    head = f"{path.name} ({len(text.splitlines())} lines)"
    if path.suffix.lower() in _EXT_LANG and path.suffix.lower() != ".md":
        body = explain_code(text, lang, name=path.name)
    else:
        body = _llm(f"Explain this document in {LANGS.get(lang or 'en')}: what it is about and its main points, "
                    f"simply.", text[:12000], smart=lang in ("ne", "hi"), max_tokens=1000, purpose="assist_file")
    return f"{head}:\n{body}"


# --- code edits: improved in the background, shown in the workspace, put in place only after "yes" ---
_pending: dict = {}


def pending_code_active() -> bool:
    import time
    return bool(_pending) and time.time() < _pending.get("expires", 0)


def start_code_improve(g, instruction: str) -> str:
    """Improve the highlighted code as a background job; the result goes to the workspace and waits for a yes."""
    import time
    from jarvis.core import jobs
    f = open_file_in_editor()
    lang_name = _EXT_LANG.get(f.suffix.lower(), "") if f else ""
    old, name = g.text, (f.name if f else _short(g.title))

    def run(ctx) -> str | None:
        ctx.progress("improving the code")
        new = improve_code(old, instruction, lang_name)
        ctx.check()
        if not new.strip():
            ctx.progress("» Sorry, no improved code came back; nothing was changed.")
            return None
        out = Path(config.OUTPUTS_DIR) / "code" / f"{Path(name).stem}-improved-{time.strftime('%H%M%S')}{Path(name).suffix or '.txt'}"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(new + "\n", encoding="utf-8")
        _pending.clear()
        _pending.update(old=old, new=new, file=str(f) if f else "", wid=g.wid, term=g.term, title=g.title,
                        expires=time.time() + config.ASSIST_PENDING_TTL_S)
        a, b = old.count("\n") + 1, new.count("\n") + 1
        ctx.progress(f"» I improved the selected code in {name} ({a} lines to {b} lines). It's in the workspace. "
                     f"Should I replace it? Say yes or no.")
        return str(out)
    jobs.get_manager().submit(f"Improve code in {name}", "code", run)
    return (f"I'm improving the selected code in {name} in the background. I'll show it in the workspace and ask "
            f"before replacing anything.")


def apply_pending_code() -> str:
    """'yes': put the improved code in place of exactly the code that was selected."""
    if not pending_code_active():
        _pending.clear()
        return "There's no code change waiting (it expires after a few minutes)."
    p = dict(_pending)
    _pending.clear()
    f = Path(p["file"]) if p["file"] else None
    dirty = p["title"].lstrip().startswith(("●", "•"))  # unsaved edits in the editor: don't write the file under it
    if f and f.is_file() and not dirty:
        text = f.read_text(errors="replace")
        if text.count(p["old"]) == 1:  # replace exactly the selected block on disk; the editor reloads the file
            backup = Path(config.DATA_DIR) / "code_backups" / f"{f.name}.{int(__import__('time').time())}.bak"
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_text(text, encoding="utf-8")
            f.write_text(text.replace(p["old"], p["new"], 1), encoding="utf-8")
            return f"Done, I replaced the selected code in {f.name}. The old version is saved as a backup."
    g = rewrite.Grab(p["old"], p["wid"], False, p["term"], p["title"])  # fall back: paste over the selection
    again = rewrite.grab()
    if isinstance(again, rewrite.Grab) and again.text.strip() == p["old"].strip():
        rewrite.put(again, p["new"])
        return f"Done, I replaced the selected code in {_short(g.title)}. Control Z there undoes it."
    rewrite._xclip(["-selection", "clipboard"], p["new"])
    return ("The code isn't selected anymore, so I didn't change the file. The improved code is on your clipboard: "
            "select the old code and press Control V.")


def cancel_pending_code() -> str:
    had = pending_code_active()
    _pending.clear()
    return "Okay, I left your code as it was." if had else "There was no code change waiting."


# --- one entry point the tool calls ---------------------------------------------------------------------------
def run(action: str, request: str = "", lang: str = "", replace: bool = False, path: str = "",
        text: str = "") -> str:
    lang = lang if lang in LANGS else lang_of(request)
    if text.strip() and action in ("explain", "meaning", "translate", "code"):  # typed, not highlighted
        return {"meaning": lambda: meaning(text, lang or "ne"), "translate": lambda: translate(text, lang or "ne"),
                "code": lambda: explain_code(text, lang)}.get(action, lambda: explain(text, lang))()
    if action == "apply_code":
        return apply_pending_code()
    if action == "cancel_code":
        return cancel_pending_code()
    if action == "write":
        return write_code(request or "the code the user asked for")
    if action == "explain_file":
        from jarvis.core.paths import resolve_target
        target = open_file_in_editor() if path.strip().lower() in ("", "this", "this file", "it") else None
        target = target or resolve_target(path or "this")
        return target if isinstance(target, str) else explain_file(target, lang)
    g = rewrite.grab()
    if isinstance(g, str):
        return g
    sel = g.text
    if action == "improve":
        if is_code(sel) or "code" in (request or "").lower():
            return start_code_improve(g, request or "fix and improve this code")
        else:
            new = rewrite.transform(sel, request or "fix grammar and make it clearer")
        if not new:
            return "error: nothing came back; the selection was not changed"
        rewrite.put(g, new)
        return (f"Done, I replaced the highlighted {'code' if is_code(sel) else 'text'} in {_short(g.title)}. "
                f"Control Z there undoes it.")
    if action == "translate":
        out = translate(sel, lang or "ne")
        if replace:
            rewrite.put(g, out)
            return f"Replaced it with the {LANGS.get(lang or 'ne', '').split(' ')[0]} translation.\n\n{out}"
        rewrite._xclip(["-selection", "clipboard"], out)
        return out + "\n\n(Also on your clipboard. Say 'replace it with the translation' to put it in place.)"
    if action == "meaning":
        return meaning(sel, lang or "ne")
    if action == "code":
        return explain_code(sel, lang)
    if not is_code(sel) and len(sel.split()) <= 3:  # one word / short phrase: a dictionary meaning (Nepali)
        return meaning(sel, lang or "ne")
    return explain(sel, lang)
