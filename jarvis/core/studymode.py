"""Study mode's engine (plan 11-09 phase 7): the best at reading and writing, few tokens.

Context (0 tokens): the highlighted text + its paragraph + the heading above it + the page title / URL (browser
extension 1.5), a PDF from its file (pdftotext, offline), any other app's highlight (X primary selection).
The page is summarized ONCE (~1.5k tokens, cached by URL) so every answer knows what the page is about.
One call per answer (smart tier; Gemini when Groq is used up, llm.py's chain). Short by default; "more" = the long
version of the last answer. Nothing is saved unless you say so (owner 11-10: "I did not say to save"): "save this"
puts the last answer in your notes (data/study/notes/<day>/<document>.md, offline), and a short term also in the
glossary (data/study/glossary.md). One thread per document: follow-ups ("simpler", "in nepali",
"more") know the last answers about that page.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

from jarvis.core import config

TASKS = ("explain", "meaning", "simpler", "nepali", "hindi", "summary", "page_summary", "quiz", "more", "ask",
         "translate", "write", "save")
_last: dict = {}  # the last answer (context, task, request, answer): what "save this" saves
ROOT = config.DATA_DIR / "study"
SUMMARY_TOKENS = 450
_threads: dict[str, list[tuple[str, str]]] = {}  # document -> [(question, answer)] (last 4, memory)

SYSTEM = ("You are a patient tutor for a CSIT student (AI/ML, exams soon). Answer about the text the student "
          "selected, in the context of the page it is on. Plain words, short: 3-6 lines unless asked for more; one "
          "small example; the key term in **bold**; code only when the page itself is code / documentation. Never "
          "invent what the page says; if the selection isn't enough, say what is missing.")

ASK = {
    "explain": "Explain the selected text in this context.",
    "meaning": "What does the selected word / phrase mean HERE (in this context)? One line meaning, one example.",
    "simpler": "Explain it again much simpler, like to a beginner, with an everyday example.",
    "nepali": "Explain it in simple Nepali (Devanagari), keeping technical terms in English.",
    "hindi": "Explain it in simple Hindi (Devanagari), keeping technical terms in English.",
    "summary": "Summarize the selected section in 3-5 bullet points.",
    "page_summary": "Summarize the whole page in 5-7 bullet points: the main idea first.",
    "quiz": "Make 3 short exam-style questions on this (mix: one definition, one why, one example), then the "
            "answers under a line 'Answers:'.",
    "more": "Give the full, detailed version of your last answer (with steps, examples and pitfalls).",
    "translate": "Translate the selected text into simple English (or into the language the student asked for).",
    "write": "Write what the student asks (a paragraph / short essay) based on this page, in clear student English.",
    "ask": "",
}


def _slug(s: str) -> str:
    return (re.sub(r"[^\w-]+", "-", (s or "").lower()).strip("-") or "page")[:60]


def doc_key(c: dict) -> str:
    return c.get("url") or c.get("title") or "selection"


def _pdf_text(url: str) -> str:
    """A PDF open in the browser (a file:// or http(s) link ending in .pdf): its text, offline (pdftotext)."""
    try:
        if url.startswith("file://"):
            path = Path(re.sub(r"^file://", "", url).split("#")[0])
        else:
            import urllib.request
            path = ROOT / "pdf" / (hashlib.md5(url.encode()).hexdigest()[:12] + ".pdf")
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                with urllib.request.urlopen(url, timeout=20) as r:  # noqa: S310 - the page the user has open
                    path.write_bytes(r.read(30_000_000))
        out = subprocess.run(["pdftotext", "-layout", "-l", "40", str(path), "-"], capture_output=True, text=True,
                             timeout=30).stdout
        return out[:15000]
    except Exception:  # noqa: BLE001 - no PDF text: the answer uses the selection only
        return ""


def context() -> dict:
    """{'text', 'paragraph', 'heading', 'title', 'url', 'page', 'source'}: what is selected and around it."""
    from jarvis.core import browsertab
    from jarvis.core import context as ctx
    c = {"text": "", "paragraph": "", "heading": "", "title": "", "url": "", "page": "", "source": ""}
    sel = browsertab.selection_context()
    if browsertab.selection().strip():
        c.update({k: sel.get(k) or "" for k in ("text", "paragraph", "heading", "title", "url", "page")},
                 source="browser")
    else:
        s = ctx.snapshot()
        if s.get("file") is not None and s.get("selection"):
            f = Path(s["file"])
            c.update(text=s["selection"], title=f.name, url=str(f), source="editor")
            try:
                c["page"] = f.read_text(errors="replace")[:15000]
            except OSError:
                pass
        elif (p := ctx._primary().strip()) and len(p) < 20000:
            c.update(text=p, source="screen")
            if s.get("tab"):
                c["url"], c["title"] = s["tab"]
    if not c["page"] and re.search(r"\.pdf(?:$|[?#])", c["url"], re.I):
        c["page"] = _pdf_text(c["url"])
    c["text"] = c["text"][:6000]
    return c


def page_summary(c: dict) -> str:
    """The page in ~5 lines, made ONCE per page (cached in kv by URL)."""
    if not c.get("page") or len(c["page"]) < 600:
        return ""
    from jarvis.core import llm, store
    key = "study_sum:" + hashlib.md5(doc_key(c).encode()).hexdigest()[:16]
    if hit := store.kv_get(key):
        return hit
    try:
        r = llm.chat([{"role": "system", "content": "Summarize this page for a student in 5 short lines: topic, main "
                                                    "ideas, key terms. No intro."},
                      {"role": "user", "content": f"Title: {c.get('title')}\n\n{c['page'][:9000]}"}],
                     tier="fast", purpose="study_page_summary", max_tokens=SUMMARY_TOKENS)
        text = (r.text or "").strip()
    except Exception:  # noqa: BLE001 - no summary: answers still use the paragraph
        return ""
    if text:
        store.kv_set(key, text)
    return text


def build(task: str, request: str, c: dict, summary: str) -> list[dict]:
    parts = []
    if c.get("title") or c.get("url"):
        parts.append(f"Page: {c.get('title') or ''} {('(' + c['url'] + ')') if c.get('url') else ''}".strip())
    if summary:
        parts.append(f"What the page is about:\n{summary}")
    if c.get("heading"):
        parts.append(f"Section: {c['heading']}")
    if c.get("paragraph") and c["paragraph"].strip() != c.get("text", "").strip():
        parts.append(f"The paragraph it is in:\n{c['paragraph']}")
    if c.get("text"):
        parts.append(f"Selected text:\n\"\"\"\n{c['text']}\n\"\"\"")
    thread = _threads.get(doc_key(c), [])[-2:]
    if thread and task in ("simpler", "nepali", "hindi", "more", "ask", "quiz"):
        parts.append("Earlier in this study session:\n" + "\n".join(f"Q: {q}\nA: {a[:600]}" for q, a in thread))
    ask = ASK.get(task) or ""
    q = (request or "").strip()
    parts.append(f"Task: {ask} {('The student said: ' + q) if q else ''}".strip())
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n\n".join(parts)}]


def _save(c: dict, task: str, request: str, answer: str) -> Path | None:
    """Notes per document and day (Markdown, offline); short terms into the glossary."""
    try:
        day = time.strftime("%Y-%m-%d")
        d = ROOT / "notes" / day
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{_slug(c.get('title') or Path(c.get('url') or 'selection').name)}.md"
        new = not f.exists()
        with f.open("a", encoding="utf-8") as fh:
            if new:
                fh.write(f"# {c.get('title') or 'Study notes'}\n{c.get('url') or ''}\n\n")
            sel = (c.get("text") or "").strip()
            fh.write(f"## {time.strftime('%H:%M')} · {task}{(': ' + request) if request else ''}\n")
            if sel:
                fh.write("> " + sel[:600].replace("\n", "\n> ") + "\n\n")
            fh.write(answer.strip() + "\n\n")
        sel = (c.get("text") or "").strip()
        if task in ("meaning", "explain") and 0 < len(sel.split()) <= 4:
            g = ROOT / "glossary.md"
            first = re.split(r"(?<=[.!?;])\s", answer.strip().replace("\n", " "), maxsplit=1)[0]
            first = re.sub(r"^\W*" + re.escape(sel) + r"\W*(?:[-–—:]|means|is)?\s*", "", first, flags=re.I)[:220]
            with g.open("a", encoding="utf-8") as fh:
                fh.write(f"- **{sel}** — {first} ({day}{', ' + c['title'] if c.get('title') else ''})\n")
        return f
    except OSError:
        return None


def save_last() -> str:
    """'save this': the last study answer into today's notes (and a short term into the glossary)."""
    if not _last:
        return "Nothing to save yet: ask me about something first, then say 'save this'."
    f = _save(_last["c"], _last["task"], _last["request"], _last["answer"])
    if f is None:
        return "error: I couldn't write the notes file."
    return f"📝 Saved to your notes: {f} (say 'show my notes' to see today's)."


def answer(task: str = "explain", request: str = "") -> str:
    """One study answer about the highlighted text (or the page)."""
    if task == "save":
        return save_last()
    task = task if task in TASKS else "ask"
    c = context()
    key = doc_key(c)
    if not c["text"] and task not in ("page_summary", "more", "quiz", "ask", "write", "simpler", "nepali", "hindi"):
        return ("Select the text first (in the browser, a PDF or VS Code), then say 'explain this'. For the whole page: "
                "'summarize this page'.")
    if not c["text"] and task in ("simpler", "nepali", "hindi", "more") and not _threads.get(key):
        return "Select the text you mean first, then ask again."
    if task == "page_summary" and not c["page"]:
        return "I can't read this page's text yet: highlight any word on it once (the extension then sends the page)."
    summary = page_summary(c) if task != "page_summary" else ""
    if task == "page_summary":
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Page: {c.get('title')} ({c.get('url')})\n\n{c['page'][:9000]}\n\n"
                                            f"Task: {ASK['page_summary']}"}]
    else:
        msgs = build(task, request, c, summary)
    from jarvis.core import llm
    try:
        r = llm.chat(msgs, tier="smart", purpose=f"study_{task}",
                     max_tokens=900 if task in ("more", "write", "quiz", "page_summary") else 400)
        out = re.sub(r"【[^】]*】", "", (r.text or "")).strip()
    except Exception as e:  # noqa: BLE001
        return f"error: the AI didn't answer ({str(e)[:120]}). Try again in a minute."
    if not out:
        return "error: the AI gave an empty answer. Try again."
    _threads.setdefault(key, []).append((request or task, out))
    _threads[key] = _threads[key][-4:]
    _last.clear()
    _last.update(c=c, task=task, request=request, answer=out)
    return out


def notes_today() -> str:
    d = ROOT / "notes" / time.strftime("%Y-%m-%d")
    files = sorted(d.glob("*.md")) if d.is_dir() else []
    if not files:
        return "No study notes today yet: after an answer you like, say 'save this'."
    return "📝 Today's notes:\n" + "\n".join(f"• {f.stem} ({f.read_text(errors='replace').count('## ')} answers) — {f}"
                                           for f in files)


def glossary(n: int = 15) -> str:
    g = ROOT / "glossary.md"
    if not g.exists():
        return "Your glossary is empty: ask 'what does this mean' about a word, then say 'save this'."
    rows = [r for r in g.read_text(errors="replace").splitlines() if r.startswith("- ")]
    return f"📖 Your glossary ({len(rows)} terms, newest last):\n" + "\n".join(rows[-n:]) + f"\n\nFile: {g}"


def state() -> str:
    return json.dumps({k: len(v) for k, v in _threads.items()})
