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

from jarvis.core import config, editor, rewrite

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
# token guard (owner): explanations stay short; when a full answer would be long, the model ends with [more] and
# KURAMA ASKS before writing the long one (one 'yes' within ASSIST_MORE_TTL_S writes it to the workspace)
MORE_TAG = "[more]"
MORE_RULE = (f" Stay within the size above. If a really good answer would need much more, give the short version and end "
             f"with the line {MORE_TAG} (nothing after it).")
SHORT_MAX = {"explain": 320, "summary": 320, "ask_text": 450, "ask_code": 1100, "code": 300}
_more: dict = {}


def _offer_more(reply: str, kind: str, sel: str, request: str = "", source: str = "", lang: str = "") -> str:
    """Strip the [more] tag; when present remember the job so 'yes' can write the long version."""
    import time
    if MORE_TAG not in reply:
        return reply
    short = reply.replace(MORE_TAG, "").rstrip()
    _more.clear()
    _more.update(kind=kind, sel=sel, request=request, source=source, lang=lang, until=time.time() + config.ASSIST_MORE_TTL_S)
    return short + "\nThis needs a longer explanation. Want me to write it (in the workspace)? Say yes."


_file_ref: dict = {}  # "explain this code" with nothing highlighted: "Do you mean test.py?" waits for yes / no


def ask_file_ref(action: str, request: str, f: Path, lang: str = "") -> str:
    import time
    _file_ref.clear()
    _file_ref.update(action=action, request=request, file=str(f), lang=lang, until=time.time() + config.ASSIST_PENDING_TTL_S)
    return (f"Nothing is highlighted. Do you mean the whole {f.name} (open in VS Code)? Say yes, or select the part "
            f"you mean and ask again.")


def file_ref_waiting() -> bool:
    import time
    return bool(_file_ref) and time.time() < _file_ref.get("until", 0)


def answer_file_ref(yes: bool) -> str:
    """'yes': do the asked thing with the whole open file; 'no': drop it."""
    if not file_ref_waiting():
        return "Nothing is waiting."
    r = dict(_file_ref)
    _file_ref.clear()
    if not yes:
        return "Okay. Select the code (or text) you mean, or tell me the file, and ask again."
    f, action, request = Path(r["file"]), r["action"], r["request"]
    text = editor.read(f)
    if not text.strip():
        return f"{f.name} is empty."
    if action in ("explain", "summary"):
        return explain_code(text, r["lang"], f.name) if is_code(text) or f.suffix in _EXT_LANG else summary(text, r["lang"])
    if action in ("complete", "improve"):
        from jarvis.tools.general.code_to_file import start_edit
        return start_edit(request, f)  # the whole file in the background; the change then waits for a yes
    if action == "use":
        return use_code(rewrite.Grab(text, None, False, False, f.name))
    return ask(text, request or "explain it", f.name, r["lang"])


def more_waiting() -> bool:
    import time
    return bool(_more) and time.time() < _more.get("until", 0)


def more() -> str:
    """'yes' after 'Want me to write it?': the long version, one call with a bigger budget."""
    if not more_waiting():
        return "Ask me to explain something first."
    m = dict(_more)
    _more.clear()
    out = LANGS.get(m["lang"] or "en", "English")
    long_sys = f"{CODE_EXPLAIN_LONG} Answer in {out}." if m["kind"] == "code" else (
                f"Write a complete, well organised explanation in simple everyday {out} with short headings and bullets "
                f"(Markdown). {EXPLAIN_RULES}") if m["kind"] != "ask" else (
                "Do exactly what the user asks about the selected code/text, completely this time. Code in fenced blocks.")
    user = m["sel"] if m["kind"] != "ask" else f"Request: {m['request']}\n\nSelected:\n{m['sel']}"
    if m["kind"] == "code" and m.get("source"):
        user = f"File: {m['source']}\n{user}"
    return _llm(long_sys, user[:8000], smart=True, max_tokens=1800, purpose="assist_more")


def cancel_more() -> str:
    _more.clear()
    return "Okay."


EXPLAIN_RULES = ("Do not quote or repeat the text, no 'It says', no headings, bold or word lists, no definitions of "
                 "normal words. If one word is really unusual, add one short line 'word = meaning' at the end.")


def explain(text: str, lang: str = "") -> str:
    """'Explain this': what it really means, in easy everyday words, like a friend would say it (owner: practical,
    not fancy). The smart model: the small one quoted the text back and listed silly 'hard words'."""
    out = LANGS.get(lang or "en", "English")
    if is_code(text):
        return explain_code(text, lang)
    reply = _llm(f"The user highlighted this text and wants to understand it. Explain it like a friend, in very simple "
                 f"everyday {out}: what it actually means and what it means for them in practice, 2-4 short sentences. "
                 f"{EXPLAIN_RULES}{MORE_RULE}", text[:6000], smart=True, max_tokens=SHORT_MAX["explain"],
                 purpose="assist_explain")
    return _offer_more(reply, "explain", text, lang=lang)


_use: dict = {}  # the run block waiting for 'yes' (add it) / 'no' (then: try again?)


def use_waiting() -> str:
    """'add' = a run block waits for yes/no; 'retry' = 'should I try again?' waits; '' = nothing."""
    import time
    return _use.get("stage", "") if _use and time.time() < _use.get("until", 0) else ""


def _names(code: str) -> list[str]:
    return [a or b for a, b in re.findall(r"^\s*(?:async\s+)?def\s+(\w+)|^\s*class\s+(\w+)", code, re.M) if not (a or b).startswith("_")]


def use_code(g, feedback: str = "") -> str:
    """'How can I use this function': a small run block that calls the highlighted code, made by the smart model
    from the selection + the whole file, checked to really call it (one retry), put on the clipboard and shown in
    the workspace; then KURAMA ASKS 'Should I add it at the end of <file>?'. yes -> added (written to the file, or
    pasted at its end when the editor has unsaved changes); no -> 'Should I try again?'."""
    import time
    f = open_file_in_editor()
    name = f.name if f else _short(getattr(g, "title", ""))
    whole = editor.read(f) if f and f.is_file() else ""
    sel = g.text if getattr(g, "text", "").strip() else whole
    if not sel.strip():
        return "Highlight the function in VS Code (or open its file), then ask again."
    if whole and re.search(r"^if\s+__name__\s*==\s*['\"]__main__['\"]\s*:", whole, re.M) and not feedback:
        return f"{name} already has a run block (if __name__ == \"__main__\") at the end. Press Run (or: python {name})."
    targets = _names(sel) or _names(whole)
    lang_name = _EXT_LANG.get(f.suffix.lower(), "") if f else ""
    sys = ("You help a learner run their own code. Write ONLY the small block of code to put at the END of their file "
           "so they can run and try the selected code right away (Python: an `if __name__ == \"__main__\":` block that "
           "calls it in a useful way: with realistic sample values, or simply calling it when it asks for input itself; "
           "print results so they see something). If it needs a value only the user has (API key, token, file path, "
           "URL), read it with os.getenv('NAME') or input() and add a short comment. Do not repeat or change their code, "
           "no tests. Last line: 'NEEDS: <values the user must set>' or 'NEEDS: none'." +
           (f" It must call: {', '.join(targets[:3])}." if targets else "") + (f" Language: {lang_name}." if lang_name else ""))
    user = (f"Selected code:\n{sel[:6000]}\n\n" + (f"The whole file {name} (context):\n{whole[:6000]}\n\n" if whole and whole != sel else "")
            + (f"{feedback}\n" if feedback else ""))
    block, needs = "", ""
    for attempt in range(2):
        out = _llm(sys, user + ("" if not attempt else "\nYour last answer did not call the selected code. Call it."),
                   smart=True, max_tokens=500, purpose="assist_use")
        needs = ""
        if m := re.search(r"^\s*NEEDS:\s*(.+)$", out, re.M | re.I):
            needs = "" if m.group(1).strip().lower() in ("none", "-", "nothing") else m.group(1).strip()
            out = out[:m.start()]
        block = _strip_fence(out).strip("\n")
        if block.strip() and (not targets or any(re.search(rf"\b{re.escape(t)}\b", block) for t in targets)):
            break
    if not block.strip():
        return "error: no run code came back"
    rewrite._xclip(["-selection", "clipboard"], block)
    try:
        from jarvis.core import workspace
        workspace.publish(f"run block for {targets[0] if targets else name}", f"# Run block for {name}\n\n```{f.suffix.lstrip('.') if f else ''}\n{block}\n```\n", folder="answers")
    except Exception:  # noqa: BLE001
        pass
    _use.clear()
    _use.update(stage="add", block=block, needs=needs, file=str(f) if f else "", title=getattr(g, "title", ""),
                wid=getattr(g, "wid", None), term=getattr(g, "term", False), sel=sel, whole=whole,
                until=time.time() + config.ASSIST_PENDING_TTL_S)
    call = f"{targets[0]}()" if targets else "your code"
    need = f" It needs {needs} (set it before running)." if needs else ""
    return f"I made a small run block that calls {call} and copied it (it's also in the workspace).{need} Should I add it at the end of {name}? Say yes, or no."


def apply_use() -> str:
    """'yes': add the run block at the end of the file: written to disk when it is saved (backup), else pasted at the
    end in the editor (Ctrl+End, new line, paste) so the user's unsaved edits stay."""
    import time
    if use_waiting() != "add":
        return "No run code is waiting."
    u = dict(_use)
    _use.clear()
    block, f = u["block"], Path(u["file"]) if u["file"] else None
    imports = [ln for ln in block.splitlines() if re.match(r"(?:import|from)\s+\w", ln)]
    dirty = u["title"].lstrip().startswith(("●", "•"))
    if f and editor._holder(f) is not None:  # the editor link: added in VS Code itself (unsaved edits kept, Ctrl+Z)
        whole = editor.read(f)
        missing = [i for i in imports if i not in whole]
        body = "\n".join(ln for ln in block.splitlines() if ln not in imports)
        new = ("\n".join(missing) + "\n" if missing else "") + whole.rstrip("\n") + "\n\n\n" + body.strip("\n") + "\n"
        if editor.save_text(f, new) == "editor":
            return f"Added at the end of {f.name}. Ctrl+Z in VS Code undoes it. Press Run (or: python {f.name})."
        return f"Added at the end of {f.name}. Press Run in VS Code (or: python {f.name})."
    if f and f.is_file() and not dirty:
        whole = f.read_text(errors="replace")
        backup = Path(config.DATA_DIR) / "code_backups" / f"{f.name}.{int(time.time())}.bak"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(whole, encoding="utf-8")
        missing = [i for i in imports if i not in whole]
        body = "\n".join(ln for ln in block.splitlines() if ln not in imports)
        f.write_text(("\n".join(missing) + "\n" if missing else "") + whole.rstrip("\n") + "\n\n\n" + body.strip("\n") + "\n",
                     encoding="utf-8")
        return f"Added at the end of {f.name}. Press Run in VS Code (or: python {f.name})."
    if u["wid"] is None:
        return "I couldn't find the editor window; the code is on your clipboard (Ctrl+V at the end of the file)."
    # unsaved edits: take the editor's CURRENT text (Ctrl+A, Ctrl+C), add the block at its end here, paste the whole
    # text back (Ctrl+A, Ctrl+V). Exact (no auto-indent pulling the block into the function), the user's unsaved
    # edits stay, and one Ctrl+Z in the editor undoes it.
    from jarvis.core import uiagent
    rewrite._activate(u["wid"])
    time.sleep(0.3)
    sentinel = f"__kurama_buffer_{time.time()}__"
    rewrite._xclip(["-selection", "clipboard"], sentinel)
    uiagent.key("ctrl+a")
    uiagent.key("ctrl+c")
    time.sleep(0.35)
    buf = rewrite._xclip(["-selection", "clipboard"])
    if not buf.strip() or buf == sentinel:
        uiagent.key("ctrl+End")  # nothing selected/copied: leave the cursor at the end; the block is on the clipboard
        rewrite._xclip(["-selection", "clipboard"], block)
        return f"I couldn't read the editor, so the run code is on your clipboard: press Ctrl+V at the end of {f.name if f else 'the file'}."
    if re.search(r"^if\s+__name__\s*==\s*['\"]__main__['\"]\s*:", buf, re.M):
        uiagent.key("ctrl+End")
        return f"{f.name if f else 'The file'} already has a run block. Press Run."
    missing = [i for i in imports if i not in buf]
    body = "\n".join(ln for ln in block.splitlines() if ln not in imports)
    new_text = ("\n".join(missing) + "\n" if missing else "") + buf.rstrip("\n") + "\n\n\n" + body.strip("\n") + "\n"
    rewrite._xclip(["-selection", "clipboard"], new_text)
    uiagent.key("ctrl+a")
    uiagent.key("ctrl+shift+v" if u["term"] else "ctrl+v")
    time.sleep(0.3)
    uiagent.key("ctrl+End")
    rewrite._xclip(["-selection", "clipboard"], block)
    return f"Added at the end of {f.name if f else 'the file'}. Save with Ctrl+S, then press Run (Ctrl+Z undoes it)."


def reject_use() -> str:
    import time
    if use_waiting() != "add":
        return "Okay."
    _use.update(stage="retry", until=time.time() + config.ASSIST_PENDING_TTL_S)
    return "Okay, I didn't add it. Should I try again with a better version? Say yes, or no."


def retry_use(feedback: str = "") -> str:
    if use_waiting() != "retry":
        return "Okay."
    u = dict(_use)
    _use.clear()
    from jarvis.core.rewrite import Grab
    g = Grab(u["sel"], u["wid"], False, u["term"], u["title"])
    note = ("The user did NOT like this attempt, make a clearly better and more useful one:\n" + u["block"] +
            (f"\nThey said: {feedback}" if feedback else ""))
    return use_code(g, note)


def cancel_use() -> str:
    _use.clear()
    return "Okay, I left your file as it is."


_TESTS_REQ = re.compile(r"\b(?:tests?|testing|unit\s*tests?|pytest|test\s+cases?)\b", re.I)


def _run_tests(module_code: str, module_name: str, tests: str) -> tuple[bool, str]:
    """Run generated pytest tests against a COPY of the user's code in a temp folder (30 s cap, no stdin).
    (passed, short output)."""
    import subprocess
    import sys
    import tempfile
    with tempfile.TemporaryDirectory(prefix="kurama-tests-") as d:
        Path(d, f"{module_name}.py").write_text(module_code, encoding="utf-8")
        Path(d, f"test_{module_name}.py").write_text(tests, encoding="utf-8")
        try:
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"test_{module_name}.py"],
                               cwd=d, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return False, "the tests did not finish within 30 s (an input()/loop is probably not mocked)"
        out = (r.stdout + r.stderr).strip()
        return r.returncode == 0, out[-2500:]


def verify_tests(answer: str, module_code: str, module_name: str) -> str:
    """'Test this function' (Python): RUN the generated tests on a copy of the code; on failure give the model the
    output (up to two rounds) to fix wrong expectations (a real bug in the user's code is kept as a failing test marked BUG). The
    answer ends with what happened, so the user never gets tests that silently fail."""
    m = re.search(r"```(?:python|py)?\n(.*?)```", answer, re.S)
    if not m or not module_code.strip():
        return answer
    tests = m.group(1)
    ok, out = _run_tests(module_code, module_name, tests)
    for _ in range(2):  # at most two fix rounds
        if ok:
            break
        fix = _llm("These pytest tests were run against the user's code and some failed. Fix the TESTS so every "
                   "expectation matches what the code really does (e.g. '2++2' is valid Python = 4). Only if the CODE "
                   "itself is clearly wrong, keep that test, mark it with a comment '# BUG: ...' and expect the correct "
                   "behaviour. Return the complete corrected test file in one ```python block, nothing else.",
                   f"Code ({module_name}.py):\n{module_code[:6000]}\n\nTests:\n{tests}\n\nRun output:\n{out}",
                   smart=True, max_tokens=1800, purpose="assist_tests_fix")
        m2 = re.search(r"```(?:python|py)?\n(.*?)```", fix, re.S)
        if not m2:
            break
        new_tests = m2.group(1)
        ok, out = _run_tests(module_code, module_name, new_tests)
        answer = answer[:m.start(1)] + new_tests + answer[m.end(1):]
        m = re.search(r"```(?:python|py)?\n(.*?)```", answer, re.S)
        tests = new_tests
    last = out.strip().splitlines()[-1] if out.strip() else ""
    if ok:
        return answer + f"\n\n✅ I ran them on a copy of your code: {last}."
    bug = re.search(r"#\s*BUG:\s*(.+)", tests)
    return answer + (f"\n\n⚠️ I ran them: {last}. " + (f"It looks like a real bug in your code: {bug.group(1).strip()}"
                                                       if bug else "Some still fail; check the output when you run them."))


def ask(sel: str, request: str, source: str = "", lang: str = "") -> str:
    """Anything else about the highlighted code/text ('give me code to test this function', 'show an example of using
    this', 'add type hints and show me', 'write a docstring for it'): the selection + the request, one call. The
    answer goes to the chat (long code lands in the workspace by the chat rule); the selection is NOT changed."""
    out = LANGS.get(lang or "en", "English")
    code = is_code(sel)
    mod = re.sub(r"\.py$", "", source) if source.endswith(".py") else ""
    hint = (f" The code is in the file '{source}'" + (f" (import it with 'from {mod} import ...')." if mod else ".")
            if source else "")
    sys = ("The user highlighted the code below and asks for something about it. Do exactly what they ask, using the "
           "code as the context; don't rewrite the selection unless asked. If they want tests: pytest tests that cover "
           "the normal cases, edge cases and errors (mock input()/print with monkeypatch/capsys when the code reads input "
           "or prints), plus one line saying how to run them." + hint if code else
           "The user highlighted the text below and asks for something about it. Do exactly what they ask, using the "
           "text as the context.")
    sys += (f" Code in one fenced block (at most ~70 lines). Explanations in simple {out}, short." if code else
            f" Answer in simple {out}, short.") + MORE_RULE
    reply = _llm(sys, f"Request: {request}\n\nSelected {'code' if code else 'text'}:\n{sel[:8000]}", smart=True,
                 max_tokens=SHORT_MAX["ask_code" if code else "ask_text"], purpose="assist_ask")
    reply = _offer_more(reply, "ask", sel, request, source, lang)
    if code and mod and _TESTS_REQ.search(request or ""):  # tests: run them before handing them over
        f = open_file_in_editor()
        disk = editor.read(f) if f and f.is_file() else ""
        module = disk if re.search(r"\bdef\s+\w+|\bclass\s+\w+", disk) else sel  # unsaved editor: the selection
        reply = verify_tests(reply, module, mod)
    return reply


def summary(text: str, lang: str = "") -> str:
    """'Summary of this paragraph / what does it want to say': the main points, simply."""
    out = LANGS.get(lang or "en", "English")
    reply = _llm(f"Summarise the user's highlighted text in very simple everyday {out}: first one sentence with the main "
                 f"message, then 2-4 short bullets with the key points (fewer for a short text). What it wants to tell "
                 f"the reader, not a retelling. {EXPLAIN_RULES}{MORE_RULE}", text[:8000], smart=True,
                 max_tokens=SHORT_MAX["summary"], purpose="assist_summary")
    return _offer_more(reply, "summary", text, lang=lang)


def meaning(text: str, lang: str = "en") -> str:
    """A word / phrase -> a 1-2 line dictionary meaning (English by default, or in the language asked);
    a sentence -> what it means, briefly. Short on purpose: it stays in the chat."""
    out = LANGS.get(lang or "en", "English")
    if (lang or "en") == "en" and len(text.split()) <= 3:
        from jarvis.core import dictionary
        if found := dictionary.lookup(text):  # offline WordNet: 0 tokens
            return found
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


CODE_EXPLAIN_LONG = ("Explain this code to a student: first one line on what it does overall, then the important steps "
                     "in order (short bullet lines), then any bug or risk you notice. Plain text, no code blocks unless "
                     "a tiny snippet helps.")


def explain_code(code: str, lang: str = "", name: str = "") -> str:
    """Short first (owner): 2-3 sentences in the chat (~150 tokens), then 'Want the full explanation?'; only a yes
    writes the long, step-by-step one (it goes to the workspace). It used to always write the long one."""
    out = LANGS.get(lang or "en", "English")
    reply = _llm(f"In {out}, say in 2-3 short plain sentences what this code does and the one thing worth knowing "
                 f"about it (a bug or risk if there is one). No lists, no headings, no code.",
                 (f"File: {name}\n" if name else "") + code[:12000], smart=False, max_tokens=SHORT_MAX["code"],
                 purpose="assist_code_explain")
    if not reply.strip() or reply.startswith("error"):
        return reply
    import time
    _more.clear()
    _more.update(kind="code", sel=code, request="", source=name, lang=lang, until=time.time() + config.ASSIST_MORE_TTL_S)
    return reply.strip() + "\nWant the full step-by-step explanation? Say yes."


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
    text = editor.read(f) if f and f.is_file() else ""
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
    text = editor.read(f)
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
    title = rw._window_name(wid, limit=400) if wid else ""  # whole title: a long one was cut before the app name
    if (st := editor.for_window(title)) is not None:  # the editor link says exactly which file (any folder / name)
        return Path(st["file"]) if st.get("file") else None
    if not (vs := vscode_title(title)):
        return None
    from jarvis.core.paths import smart_path
    return smart_path(f"{vs[1]}/{vs[0]}" if vs[1] else vs[0], want="file")


def vscode_title(title: str) -> tuple[str, str] | None:
    """'● test.py - Tara-Assistant [SSH: x] - Visual Studio Code' -> ('test.py', 'Tara-Assistant') (also with a profile
    name after the folder: 'test.py - KURAMA - Claude-1 - Visual Studio Code'); folder names may
    hold '-', files may have no extension (Makefile). None: not a VS Code editor window."""
    parts = [p.strip() for p in re.sub(r"\s+-\s+Visual Studio Code(?: - Insiders)?\s*$", "\n", title or "").split("\n")[0]
             .split(" - ")] if re.search(r"\s-\sVisual Studio Code", title or "") else []
    f = parts[0].lstrip("●• ").strip() if parts else ""
    if not f or "/" in f or f.lower() in ("welcome", "settings", "keyboard shortcuts", "extensions", "untitled"):
        return None
    d = re.sub(r"\s*\[[^\]]*\]\s*$", "", parts[1]).strip() if len(parts) > 1 else ""  # then e.g. a profile name
    return f, d


def write_code(request: str) -> str:
    """New code at the cursor of the front editor, in that file's language, with the file around it as context."""
    f = open_file_in_editor()
    lang_name = _EXT_LANG.get(f.suffix.lower(), "") if f else ""
    context = ""
    if f and f.is_file() and f.stat().st_size < 400_000:
        context = editor.read(f)[:6000]
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
    if not rewrite.put(g, code + "\n"):
        return "The file changed meanwhile, so I didn't add it: the code is on your clipboard (Ctrl+V)."
    lines = code.count("\n") + 1
    return (f"Wrote {lines} lines of {lang_name or 'code'} at your cursor in {_short(g.title)}. Control Z in the "
            f"editor undoes it.")


def explain_file(path: Path, lang: str = "") -> str:
    if not path.is_file():
        return f"error: {path} isn't a file"
    if path.stat().st_size > 2_000_000:
        return f"{path.name} is too big to explain in one go; select the part you want explained."
    text = editor.read(path)
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


def stage_file_change(f: Path, old: str, new: str) -> str:
    """A whole-file change that waits for 'yes' like a selection change (apply_pending_code writes it, backup kept).
    Returns what the change adds, for the question ('+12 lines: def search(...)')."""
    import difflib
    import time
    wid, _ = rewrite.target_window()
    title = rewrite._window_name(wid) if wid else ""
    _pending.clear()
    _pending.update(old=old, new=new, lead="", file=str(f), wid=wid, term=False, title=title, whole=True,
                    expires=time.time() + config.ASSIST_PENDING_TTL_S)
    added = [ln[1:] for ln in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
             if ln.startswith("+") and not ln.startswith("+++") and ln[1:].strip()]
    gone = sum(1 for ln in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
               if ln.startswith("-") and not ln.startswith("---") and ln[1:].strip())
    first = next((ln.strip() for ln in added if ln.strip().startswith(("def ", "class ", "async def "))), "")
    return (f"+{len(added)} lines" + (f", {gone} changed" if gone else "") + (f" ({first[:60]})" if first else ""))


def pending_code_active() -> bool:
    import time
    return bool(_pending) and time.time() < _pending.get("expires", 0)


def complete_code(code: str, note: str, lang_name: str = "", context: str = "") -> str:
    """'Complete this code': the finished selection (level 0), or 'QUESTION: ...' when its purpose is unclear."""
    system = ("You finish unfinished code. Return ONLY the completed version of the user's selected code (no "
              "explanation, no markdown fences): implement every missing part (empty bodies, TODO, '...', pass, "
              "half-written lines) so it runs, keep the existing code, names and style, add only the imports it needs, "
              "no tests or demo block. If you really cannot tell what the code is meant to do, reply ONLY with "
              "'QUESTION: <one short question to the user>'. Return it at indentation level 0." +
              (f" Language: {lang_name}." if lang_name else ""))
    user = ((f"The user explained: {note}\n\n" if note else "") +
            (f"Surrounding code (context only):\n{context}\n\n" if context else "") + f"Selected code:\n{code[:12000]}")
    out = _llm(system, user, smart=True, max_tokens=min(4000, len(code) + 1500), purpose="assist_code_complete")
    return out.strip() if out.strip().upper().startswith("QUESTION:") else textwrap.dedent(_strip_fence(out).strip("\n"))


_ask_back: dict = {}  # 'complete this code' asked the user a question: their next reply is the answer


def ask_back_waiting() -> bool:
    import time
    return bool(_ask_back) and time.time() < _ask_back.get("until", 0)


def answer_back(reply: str) -> str:
    if not ask_back_waiting():
        return "Nothing is waiting for an answer."
    d = dict(_ask_back)
    _ask_back.clear()
    return start_code_improve(d["g"], "", mode="complete", note=(d.get("note", "") + " " + reply).strip())


def start_code_improve(g, instruction: str, mode: str = "improve", note: str = "") -> str:
    """Improve (or, mode 'complete', finish) the highlighted code as a background job; the result goes to the
    workspace and waits for a yes."""
    import time
    from jarvis.core import jobs
    f = open_file_in_editor()
    lang_name = _EXT_LANG.get(f.suffix.lower(), "") if f else ""
    old, name = g.text, (f.name if f else _short(g.title))

    def run(ctx) -> str | None:
        ctx.progress("completing the code" if mode == "complete" else "improving the code")
        lead, base, code0 = _layout(old, f)
        if mode == "complete":
            new0 = complete_code(code0, note, lang_name, _context(f, old))
            if new0.upper().startswith("QUESTION:"):  # unsure what it should do: ask first, never guess
                _ask_back.clear()
                _ask_back.update(g=g, note=note, until=time.time() + config.ASSIST_PENDING_TTL_S)
                ctx.progress("» Before I complete it: " + new0.split(":", 1)[1].strip())
                return None
        else:
            new0 = improve_code(code0, instruction, lang_name, _context(f, old))
        ctx.check()
        if not new0.strip():
            ctx.progress("» No improved code came back; nothing changed.")
            return None
        new = _rebase(new0, base, old)
        tag = "completed" if mode == "complete" else "improved"
        out = Path(config.OUTPUTS_DIR) / "code" / f"{Path(name).stem}-{tag}-{time.strftime('%H%M%S')}{Path(name).suffix or '.txt'}"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(new.rstrip("\n") + "\n", encoding="utf-8")
        _pending.clear()
        _pending.update(old=old, new=new, lead=lead, file=str(f) if f else "", wid=g.wid, term=g.term, title=g.title,
                        expires=time.time() + config.ASSIST_PENDING_TTL_S)
        a, b = old.strip("\n").count("\n") + 1, new.strip("\n").count("\n") + 1
        ctx.progress(f"» I {'completed' if mode == 'complete' else 'improved'} the code ({a} → {b} lines). It's in the "
                     f"workspace. Should I replace it in {name}?")
        return str(out)
    jobs.get_manager().submit(f"{'Complete' if mode == 'complete' else 'Improve'} code in {name}", "code", run)
    return f"{'Completing' if mode == 'complete' else 'Improving'} the selected code in {name}…"


def apply_pending_code() -> str:
    """'yes': put the improved code in place of exactly the code that was selected (at its real indentation)."""
    if not pending_code_active():
        _pending.clear()
        return "No code change is waiting (it expires after a few minutes)."
    p = dict(_pending)
    _pending.clear()
    if p.get("whole"):  # a whole-file change (complete / write code into the file): the file on disk, backup kept
        from jarvis.tools.general.code_to_file import _backup, _dirty_note
        f = Path(p["file"])
        cur = editor.read(f)
        if cur.strip():
            _backup(f, cur)
        how = editor.save_text(f, p["new"])
        return f"Added to {f.name}." + (" Ctrl+Z in VS Code undoes it." if how == "editor" else _dirty_note(f))
    lead = p.get("lead", "")
    f = Path(p["file"]) if p["file"] else None
    if f is not None and editor._holder(f) is not None:  # the editor link: replace exactly that code in VS Code
        live = editor.read(f)
        if live.count(p["old"]) == 1:
            i = live.index(p["old"])
            old, new = p["old"], p["new"]
            if lead and live[max(0, i - len(lead)):i] == lead and new.startswith(lead):
                new = new[len(lead):]  # the selection began after the line's own spaces: they stay
            if editor.replace_once(f, old, new):
                backup = Path(config.DATA_DIR) / "code_backups" / f"{f.name}.{int(__import__('time').time())}.bak"
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_text(live, encoding="utf-8")
                return f"Replaced in {f.name}. Ctrl+Z in VS Code undoes it."
        if p["old"] not in live:
            rewrite._xclip(["-selection", "clipboard"], p["new"])
            return f"That code isn't in {f.name} anymore, so I put the new code on your clipboard (Ctrl+V where you want it)."
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
    if isinstance(again, rewrite.Grab) and again.text.strip() == p["old"].strip() and rewrite.put(again, paste):
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
    text = editor.read(f)
    if not text.strip():
        return f"{f.name} is empty."
    if len(text) > WHOLE_MAX_CHARS:
        return f"{f.name} is too big to rewrite in one go ({text.count(chr(10)) + 1} lines). Select a part and ask again."
    wid, _ = rewrite.target_window()
    g = rewrite.Grab(text, wid, False, False, rewrite._window_name(wid) if wid else f.name)
    return start_code_improve(g, clean_instruction(request))


def _screen_chat() -> str:
    """Nothing highlighted: read the chat window you're looking at (screenshot + tesseract, 0 tokens)."""
    try:
        from jarvis.core import ocr
        shot = ocr.grab_window()
        if isinstance(shot, str):
            return ""
        text = ocr.tesseract(shot).text
        return text if len(text.strip()) >= 30 else ""
    except Exception:  # noqa: BLE001
        return ""


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
    if action == "more":
        return more()
    if action in ("file_yes", "file_no"):
        return answer_file_ref(action == "file_yes")
    if action == "file_ask":  # text = what to do with it (explain / improve / complete / ask...), path = the open file
        return ask_file_ref(text or "explain", request, Path(path), lang)
    if action == "answer_back":
        return answer_back(request)
    if action == "use_yes":
        return apply_use()
    if action == "use_no":
        return reject_use()
    if action == "use_retry":
        return retry_use(request)
    if action == "use_cancel":
        return cancel_use()
    if action == "cancel_more":
        return cancel_more()
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
        chat = g.text if isinstance(g, rewrite.Grab) else (text or _screen_chat() or _clipboard_text())
        if not chat.strip():
            return "Open the chat (or select / copy the messages), then say 'what should I reply'."
        out = reply(chat, request, lang)
        if not out:
            return "error: no reply came back"
        rewrite._xclip(["-selection", "clipboard"], out)
        return out + "\n(Copied: paste it in the chat.)"
    g = rewrite.grab()
    if isinstance(g, str) and action in ("complete", "improve") and open_file_in_editor() is not None:
        # nothing highlighted, but a file is open: complete / change the whole file (only what's missing is added)
        from jarvis.tools.general.code_to_file import start_edit
        return start_edit(request or ("complete the code" if action == "complete" else "improve the code"))
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
        if getattr(g, "editable", None) is False:  # page text (an article, an AI chat): nothing to replace there
            rewrite._xclip(["-selection", "clipboard"], new)
            return f"Here it is (also copied to your clipboard; that page text can't be edited in place):\n\n{new}"
        if not rewrite.put(g, new):
            return "The text changed meanwhile, so I didn't replace it: the new version is on your clipboard (Ctrl+V)."
        if getattr(g, "editable", None) is None and not getattr(g, "editor", None):
            return ("Done: pasted over your selection (if that text can't be edited, it's on your clipboard).\n\n" + new)
        return "Replaced. Ctrl+Z undoes it."
    if action == "translate":
        out = translate(sel, lang or "ne")
        if replace:
            if not rewrite.put(g, out):
                return "The text changed meanwhile, so I didn't replace it: the new version is on your clipboard (Ctrl+V)."
            return f"Replaced with the {LANGS.get(lang or 'ne', '').split(' ')[0]} translation."
        rewrite._xclip(["-selection", "clipboard"], out)
        return out + "\n(Copied. Say 'replace it' to put it in place.)"
    if action == "meaning":  # code selected: what the code does; otherwise the word / sentence meaning
        return explain_code(sel, lang) if is_code(sel) else meaning(sel, lang or "en")
    if action == "code":
        return explain_code(sel, lang)
    if action == "summary":
        return explain_code(sel, lang) if is_code(sel) else summary(sel, lang)
    if action == "ask":
        return ask(sel, request or "explain it", _short(g.title), lang)
    if action == "use":
        return use_code(g)
    if action == "complete":
        return start_code_improve(g, "", mode="complete", note=clean_instruction(request))
    if not is_code(sel) and len(sel.split()) <= 3:  # one word / short phrase: a dictionary meaning
        return meaning(sel, lang or "en")
    return explain(sel, lang)
