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
import textwrap
from pathlib import Path

from jarvis.core import config, rewrite

log = logging.getLogger(__name__)
LANGS = {"ne": "Nepali (Devanagari script)", "hi": "Hindi (Devanagari script)", "en": "English"}
# any language can be a translation target: spoken name -> code (the code is only a key; the prompt uses the name)
_LANG_NAMES = {"nepali": "ne", "नेपाली": "ne", "hindi": "hi", "हिन्दी": "hi", "हिंदी": "hi", "english": "en",
               "अंग्रेजी": "en", "french": "fr", "spanish": "es", "german": "de", "italian": "it", "portuguese": "pt",
               "russian": "ru", "japanese": "ja", "chinese": "zh", "mandarin": "zh", "korean": "ko", "arabic": "ar",
               "urdu": "ur", "bengali": "bn", "bangla": "bn", "tamil": "ta", "telugu": "te", "marathi": "mr",
               "gujarati": "gu", "punjabi": "pa", "kannada": "kn", "malayalam": "ml", "maithili": "mai",
               "bhojpuri": "bho", "newari": "new", "nepal bhasa": "new", "sanskrit": "sa", "tibetan": "bo",
               "sinhala": "si", "turkish": "tr", "thai": "th", "vietnamese": "vi", "indonesian": "id", "malay": "ms",
               "dutch": "nl", "polish": "pl", "ukrainian": "uk", "persian": "fa", "farsi": "fa", "hebrew": "he",
               "greek": "el", "swedish": "sv", "norwegian": "no", "danish": "da", "finnish": "fi", "filipino": "tl",
               "swahili": "sw"}
for _n, _c in _LANG_NAMES.items():
    LANGS.setdefault(_c, _n.title())
LANG_ALT = "|".join(sorted((re.escape(n) for n in _LANG_NAMES), key=len, reverse=True))  # for the router regexes
_CODE_HINT = re.compile(r"(?m)^\s*(?:def |class |import |from \S+ import|function |const |let |var |public |private |"
                        r"#include|for\s*\(|if\s*\(|while\s*\(|return\b|async |@\w+)|[{};]\s*$|=>|::|\)\s*:\s*$")
_EXT_LANG = {".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".jsx": "React JSX", ".tsx": "React TSX",
             ".java": "Java", ".c": "C", ".cpp": "C++", ".h": "C/C++ header", ".cs": "C#", ".go": "Go", ".rs": "Rust",
             ".php": "PHP", ".rb": "Ruby", ".kt": "Kotlin", ".swift": "Swift", ".html": "HTML", ".css": "CSS",
             ".sql": "SQL", ".sh": "Bash", ".ipynb": "Python", ".dart": "Dart", ".r": "R", ".md": "Markdown"}


def lang_of(text: str) -> str:
    """A language named in the request ('nepali', 'into japanese', 'हिन्दी') -> its code; '' if none. The one after
    'to/into/in' wins ('translate this english text to french' -> fr)."""
    t = (text or "").lower()
    if m := re.search(r"\b(?:to|into|in)\s+(" + LANG_ALT + r")(?![\w])", t):
        return _LANG_NAMES[m.group(1)]
    if m := re.search(r"(?<![\w])(" + LANG_ALT + r")(?![\w])", t):
        return _LANG_NAMES[m.group(1)]
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
EXPLAIN_RULES = ("Do not quote or repeat the text, no 'It says', no headings, bold or word lists, no definitions of "
                 "normal words. If one word is really unusual, add one short line 'word = meaning' at the end.")


def explain(text: str, lang: str = "") -> str:
    """'Explain this': what it really means, in easy everyday words, like a friend would say it (owner: practical,
    not fancy). The smart model: the small one quoted the text back and listed silly 'hard words'."""
    out = LANGS.get(lang or "en", "English")
    if is_code(text):
        return explain_code(text, lang)
    return _llm(f"The user highlighted this text and wants to understand it. Explain it like a friend, in very simple "
                f"everyday {out}: what it actually means and what it means for them in practice, 2-4 short sentences "
                f"(a bit more only for a long text). {EXPLAIN_RULES}", text[:6000], smart=True,
                max_tokens=500, purpose="assist_explain")


def summary(text: str, lang: str = "") -> str:
    """'Summary of this paragraph / what does it want to say': the main points, simply."""
    out = LANGS.get(lang or "en", "English")
    return _llm(f"Summarise the user's highlighted text in very simple everyday {out}: first one sentence with the main "
                f"message, then 2-4 short bullets with the key points (fewer for a short text). What it wants to tell "
                f"the reader, not a retelling. {EXPLAIN_RULES}", text[:8000], smart=True, max_tokens=450,
                purpose="assist_summary")


def meaning(text: str, lang: str = "en") -> str:
    """A word / phrase -> a 1-2 line dictionary meaning (English by default, or in the language asked);
    a sentence -> what it means, briefly. Short on purpose: it stays in the chat."""
    out = LANGS.get(lang or "en", "English")
    if len(text.split()) <= 4:
        if (lang or "en") == "en":
            sys = ("Give the meaning of the user's word/phrase like a learner's dictionary, in simple English. Format: "
                   "'<word> (<part of speech>): <meaning in a few words>.' then 'Example: <one short sentence>.' "
                   "Two lines, nothing else.")
        else:
            sys = (f"Give the meaning of the user's English word/phrase in {out}. Format: '<word> (<part of speech>): "
                   f"<1-3 {out} words for it> – <a few simple English words>.' then 'Example: <short English "
                   f"sentence> → <its {out} translation>.' Two lines, nothing else.")
        return _llm(sys, text[:200], smart=(lang or "en") != "en", max_tokens=200, purpose="assist_meaning")
    sys = (f"In {out}, say what the user's sentence means in 1-2 short, simple sentences (for a learner). Nothing else.")
    return _llm(sys, text[:3000], smart=(lang or "en") != "en", max_tokens=300, purpose="assist_meaning")


def translate(text: str, lang: str = "ne") -> str:
    out = LANGS.get(lang or "ne", lang or "Nepali (Devanagari script)")
    return _llm(f"Translate the user's text (any language) into {out}. Natural, accurate, everyday language as people really speak "
                f"and write it (for Nepali: Nepal's Nepali, not Hindi words); keep names, code and technical terms "
                f"as they are; same meaning and formatting. Output ONLY the translation.", text[:6000], smart=True, max_tokens=min(3000, len(text) + 400),
                purpose="assist_translate")


REPLY_MAX_CHARS = 2500  # only the end of a long chat is sent: the latest messages matter most (tokens)


def reply(chat: str, instruction: str = "", lang: str = "") -> str:
    """The user's next message in a chat they copied/selected (both sides, the other person spoke last).
    One call; the fast model unless the chat is in Devanagari."""
    chat = chat.strip()
    if len(chat) > REPLY_MAX_CHARS:
        chat = "…" + chat[-REPLY_MAX_CHARS:]
    want = f" Write it in {LANGS[lang]}." if lang in LANGS else ""
    how = re.sub(r"^(?:please\s+|kurama\W+|can\s+you\s+)*(?:what\s+should\s+i\s+(?:reply|say|answer|write)|(?:write\s+)?(?:a\s+|my\s+)?"
                 r"(?:reply|response|respond|answer))(?:\s+(?:to|for))?(?:\s+(?:this|that|it|him|her|them|the\s+\w+))?"
                 r"(?:\s+(?:message|chat|conversation|text|email|mail|messages))?[\s,:?.-]*", "", instruction or "",
                 flags=re.I).strip()
    sys = ("This is a chat the user copied: messages from both sides, the other person wrote last. Write the user's "
           "next reply to that last message, using the whole conversation for context. Sound like the user: same "
           "language and script (English, Nepali, Hindi or romanized Nepali/Hindi as they write it), same tone and "
           "length as their own messages, natural, no greeting unless they use one." + want +
           (f" It must answer that last message AND say what the user wants: {how}." if how else "") +
           " Output ONLY the reply text.")
    smart = bool(re.search(r"[\u0900-\u097F]", chat)) or lang in ("ne", "hi")
    return _llm(sys, chat, smart=smart, max_tokens=250, purpose="assist_reply")


def explain_code(code: str, lang: str = "", name: str = "") -> str:
    out = LANGS.get(lang or "en", "English")
    return _llm(f"Explain this code to a student, in {out}: first one line on what it does overall, then the "
                f"important steps in order (short bullet lines), then any bug or risk you notice. Plain text, no "
                f"code blocks unless a tiny snippet helps.", (f"File: {name}\n" if name else "") + code[:12000],
                smart=True, max_tokens=1200, purpose="assist_code_explain")


_CODE_VERB = re.compile(r"\b(?:make|improve|optimi[sz]e|fix|refactor|format|clean|modify|change|update|edit|enhance|"
                        r"expand|rewrite|correct|add|simplify|speed|debug|replace|convert|turn)\b", re.I)
_CODE_TAIL = re.compile(r"(?:[\s,]+(?:and\s+)?(?:then\s+)?replace\s+it(?:\s+(?:there|here|in\s+place))?|[\s,]+actually|"
                        r"[\s,]+please|[\s,]+okay)+\s*[.!?]*$", re.I)


def clean_instruction(request: str) -> str:
    """'Zarpis actually make this selected code better and replace it' -> 'make this selected code better':
    drop the wake-word / filler before the first action word and the 'replace it' tail (replacing is a separate yes)."""
    t = (request or "").strip()
    if m := _CODE_VERB.search(t):
        t = t[m.start():]
    t = _CODE_TAIL.sub("", t).strip(" ,.")
    if re.fullmatch(r"replace\s+(?:it|this|the\s+\w+)", t, re.I):
        t = ""
    return t or "fix and improve this code"


def improve_code(code: str, instruction: str, lang_name: str = "", context: str = "") -> str:
    """The improved selection, at indentation level 0 (the caller puts it back at the block's real indentation).
    ONLY the rewritten selection, not a bigger program."""
    a = code.count("\n") + 1
    system = ("You edit code. Apply the user's instruction to their SELECTED code and return ONLY the new version of "
              "that selection (no explanation, no markdown fences). It replaces exactly the selection inside a bigger "
              "file, so: no example usage, no tests, no demo or main block, no new imports or functions the "
              "instruction didn't ask for. 'Better' or 'detailed' means clearer names, a short docstring or comments, "
              "input checks and error handling, not a bigger program. Keep about the same length (at most twice "
              "the lines). Keep the same behaviour unless asked and the same names used by other code. The "
              "selection is given at indentation level 0: return it at level 0 too, with correct, consistent "
              "indentation inside it." + (f" Language: {lang_name}." if lang_name else ""))
    user = (f"Instruction: {instruction}\n\n" + (f"Surrounding code (for context only, do not return it):\n{context}\n\n"
                                                   if context else "") + f"Selected code ({a} lines):\n{code[:12000]}")
    budget = min(4000, len(code) // 2 + 800)
    new = _strip_fence(_llm(system, user, smart=True, max_tokens=budget, purpose="assist_code_fix"))
    limit = max(3 * a + 10, 30)
    if new.count("\n") + 1 > limit:  # padded with a whole program: ask once more, strictly
        log.info("code improve too long (%d lines for %d), retrying", new.count("\n") + 1, a)
        again = _strip_fence(_llm(system, user + f"\n\nYour answer must be at most {2 * a + 6} lines.", smart=True,
                                  max_tokens=budget, purpose="assist_code_fix"))
        if again.strip():
            new = again
    return textwrap.dedent(new.strip("\n"))


def _indent_of(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _guess_lead(old: str) -> str:
    """No file to look at: the indentation the first line had before the selection began (people often start a
    selection at 'try:', after its spaces). Same as the shallowest later line, one level less after 'try:' / '{'
    unless that line continues the block ('except', 'else', '}')."""
    lines = old.splitlines()
    rest = [ln for ln in lines[1:] if ln.strip()]
    if not lines or _indent_of(lines[0]) or not rest:
        return ""
    low = min((_indent_of(ln) for ln in rest), key=len)
    at_low = [ln.strip() for ln in rest if _indent_of(ln) == low]
    opens = lines[0].rstrip().endswith((":", "{", "(", "["))
    if opens and not any(re.match(r"(?:except|else|elif|finally|catch)\b|[}\])]", x) for x in at_low):
        deeper = sorted({len(_indent_of(ln)) for ln in rest if len(_indent_of(ln)) > len(low)})
        unit = (deeper[0] - len(low)) if deeper else 4
        return low[: max(0, len(low) - unit)]
    return low


def _layout(old: str, f: Path | None) -> tuple[str, str, str]:
    """(lead, base, code0): the whitespace before the selection on its first line, the block's base indentation and
    the selection re-based to level 0 (what the model sees)."""
    lead = ""
    text = f.read_text(errors="replace") if f and f.is_file() else ""
    if text and text.count(old) == 1:
        i = text.index(old)
        before = text[text.rfind("\n", 0, i) + 1: i]
        lead = before if not before.strip() else ""
    else:
        lead = _guess_lead(old)
    full = lead + old
    code0 = textwrap.dedent(full)
    first = next((ln for ln in full.splitlines() if ln.strip()), "")
    first0 = next((ln for ln in code0.splitlines() if ln.strip()), "")
    base = first[: len(first) - len(first0)]
    return lead, base, code0


def _context(f: Path | None, old: str, chars: int = 1500) -> str:
    """A little of the file around the selection, so the model knows the names it uses."""
    if not f or not f.is_file():
        return ""
    text = f.read_text(errors="replace")
    i = text.find(old)
    if i < 0:
        return ""
    return (text[max(0, i - chars): i] + "<<SELECTION>>" + text[i + len(old): i + len(old) + chars // 2]).strip("\n")


def _rebase(new0: str, base: str, old: str) -> str:
    out = "\n".join(base + ln if ln.strip() else "" for ln in new0.splitlines())
    return out + "\n" if old.endswith("\n") else out


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


_retry: dict = {}  # the last request that found nothing highlighted: 'I selected it' runs it again


def retry_active() -> bool:
    import time
    return bool(_retry) and time.time() < _retry.get("expires", 0)


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
        lead, base, code0 = _layout(old, f)
        new0 = improve_code(code0, instruction, lang_name, _context(f, old))
        ctx.check()
        if not new0.strip():
            ctx.progress("» No improved code came back; nothing changed.")
            return None
        new = _rebase(new0, base, old)
        out = Path(config.OUTPUTS_DIR) / "code" / f"{Path(name).stem}-improved-{time.strftime('%H%M%S')}{Path(name).suffix or '.txt'}"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(new.rstrip("\n") + "\n", encoding="utf-8")
        _pending.clear()
        _pending.update(old=old, new=new, lead=lead, file=str(f) if f else "", wid=g.wid, term=g.term, title=g.title,
                        expires=time.time() + config.ASSIST_PENDING_TTL_S)
        a, b = old.strip("\n").count("\n") + 1, new.strip("\n").count("\n") + 1
        ctx.progress(f"» Ready: {a} → {b} lines, in the workspace. Replace it?")
        return str(out)
    jobs.get_manager().submit(f"Improve code in {name}", "code", run)
    return f"Improving the selected code in {name}…"


def apply_pending_code() -> str:
    """'yes': put the improved code in place of exactly the code that was selected (at its real indentation)."""
    if not pending_code_active():
        _pending.clear()
        return "No code change is waiting (it expires after a few minutes)."
    p = dict(_pending)
    _pending.clear()
    lead = p.get("lead", "")
    f = Path(p["file"]) if p["file"] else None
    dirty = p["title"].lstrip().startswith(("●", "•"))  # unsaved edits in the editor: don't write the file under it
    if f and f.is_file() and not dirty:
        text = f.read_text(errors="replace")
        if text.count(p["old"]) == 1:  # replace exactly the selected block on disk; the editor reloads the file
            i = text.index(p["old"])
            start = i - len(lead)  # the selection began after the line's own spaces: replace those too
            if text[start:i] != lead:
                start = i
            backup = Path(config.DATA_DIR) / "code_backups" / f"{f.name}.{int(__import__('time').time())}.bak"
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_text(text, encoding="utf-8")
            new = p["new"] if start < i else p["new"][len(lead):] if p["new"].startswith(lead) else p["new"]
            f.write_text(text[:start] + new + text[i + len(p["old"]):], encoding="utf-8")
            return f"Replaced in {f.name}."
    paste = p["new"][len(lead):] if lead and p["new"].startswith(lead) else p["new"]  # the line's spaces stay
    again = rewrite.grab()
    if isinstance(again, rewrite.Grab) and again.text.strip() == p["old"].strip():
        rewrite.put(again, paste)
        return "Replaced. Ctrl+Z undoes it."
    rewrite._xclip(["-selection", "clipboard"], paste)
    return "The code isn't selected anymore, so I put the new code on your clipboard: select the old code, Ctrl+V."


def cancel_pending_code() -> str:
    had = pending_code_active()
    _pending.clear()
    return "Okay, left it as it was." if had else "No code change was waiting."


WHOLE_CODE = re.compile(r"\b(?:whole|entire|full|complete|all\s+(?:of\s+)?(?:the|my))\s+(?:code|file|program|script)\b|"
                        r"\b(?:this|the|my)\s+(?:code\s+)?file\b", re.I)
WHOLE_MAX_CHARS = 10000  # bigger files: select a part (the model must return every line)


def improve_whole_file(request: str) -> str:
    """'format my whole code' / 'fix this file': the file open in VS Code, as one background change that waits
    for a yes like a selection (it replaces the whole file, backup kept)."""
    f = open_file_in_editor()
    if f is None or not f.is_file():
        return "Open the file in VS Code first, then ask again."
    text = f.read_text(errors="replace")
    if not text.strip():
        return f"{f.name} is empty."
    if len(text) > WHOLE_MAX_CHARS:
        return f"{f.name} is too big to rewrite in one go ({text.count(chr(10)) + 1} lines). Select a part and ask again."
    wid, _ = rewrite.target_window()
    g = rewrite.Grab(text, wid, False, False, rewrite._window_name(wid) if wid else f.name)
    return start_code_improve(g, clean_instruction(request))


def _clipboard_text() -> str:
    from jarvis.tools.general import _sys
    try:
        return _sys.clip_get()
    except Exception:  # noqa: BLE001
        return ""


# --- one entry point the tool calls ---------------------------------------------------------------------------
# 'this word' misheard as 'this wood / road / ward': these are pointers at the selection, never text to translate
_SEL_REF = re.compile(r"(?:(?:this|that|the|it|my)\s*)*(?:(?:whole|entire|selected|highlighted)\s+)?(?:word|wood|road|ward|world|"
                      r"words|sentence|paragraph|line|text|part|phrase|one|thing|selection)?s?", re.I)


def run(action: str, request: str = "", lang: str = "", replace: bool = False, path: str = "",
        text: str = "") -> str:
    lang = lang if lang in LANGS else lang_of(request)
    if text.strip() and _SEL_REF.fullmatch(text.strip(" .?!'\"")):
        text = ""  # 'translate this wood' = the highlighted word, not the word 'wood'
    if text.strip() and action in ("explain", "meaning", "translate", "code", "summary"):  # typed, not highlighted
        return {"meaning": lambda: meaning(text, lang or "en"), "translate": lambda: translate(text, lang or "ne"),
                "code": lambda: explain_code(text, lang), "summary": lambda: summary(text, lang)}.get(
            action, lambda: explain(text, lang))()
    if action == "apply_code":
        return apply_pending_code()
    if action == "cancel_code":
        return cancel_pending_code()
    if action == "retry":
        if not retry_active():
            return "Tell me again what to do with the highlighted text."
        r = {k: v for k, v in _retry.items() if k != "expires"}
        _retry.clear()
        return run(**r)
    if action == "write":
        return write_code(request or "the code the user asked for")
    if action == "explain_file":
        from jarvis.core.paths import resolve_target
        target = open_file_in_editor() if path.strip().lower() in ("", "this", "this file", "it") else None
        target = target or resolve_target(path or "this")
        return target if isinstance(target, str) else explain_file(target, lang)
    if action == "improve" and WHOLE_CODE.search(request or ""):  # "format my whole code": the file open in the editor
        return improve_whole_file(request)
    if action == "reply":  # a chat the user selected, or copied (Ctrl+C) before asking
        g = rewrite.grab()
        chat = g.text if isinstance(g, rewrite.Grab) else (text or _clipboard_text())
        if not chat.strip():
            return "Select (or copy) the chat messages first, then say 'reply to this'."
        out = reply(chat, request, lang)
        if not out:
            return "error: no reply came back"
        rewrite._xclip(["-selection", "clipboard"], out)
        return out + "\n(Copied: paste it in the chat.)"
    g = rewrite.grab()
    if isinstance(g, str):
        import time
        _retry.clear()
        _retry.update(action=action, request=request, lang=lang, replace=replace,
                      expires=time.time() + config.ASSIST_PENDING_TTL_S)
        return g + " Or highlight it and say 'done'."
    _retry.clear()
    sel = g.text
    if action == "improve":
        if is_code(sel) or "code" in (request or "").lower():
            return start_code_improve(g, clean_instruction(request))
        else:
            new = rewrite.transform(sel, request or "fix grammar and make it clearer")
        if not new:
            return "error: nothing came back; the selection was not changed"
        rewrite.put(g, new)
        return "Replaced. Ctrl+Z undoes it."
    if action == "translate":
        out = translate(sel, lang or "ne")
        if replace:
            rewrite.put(g, out)
            return f"Replaced with the {LANGS.get(lang or 'ne', '').split(' ')[0]} translation."
        rewrite._xclip(["-selection", "clipboard"], out)
        return out + "\n(Copied. Say 'replace it' to put it in place.)"
    if action == "meaning":  # code selected: what the code does; otherwise the word / sentence meaning
        return explain_code(sel, lang) if is_code(sel) else meaning(sel, lang or "en")
    if action == "code":
        return explain_code(sel, lang)
    if action == "summary":
        return explain_code(sel, lang) if is_code(sel) else summary(sel, lang)
    if not is_code(sel) and len(sel.split()) <= 3:  # one word / short phrase: a dictionary meaning
        return meaning(sel, lang or "en")
    return explain(sel, lang)
