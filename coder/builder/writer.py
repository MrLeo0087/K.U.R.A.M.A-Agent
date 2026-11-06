"""Each planned file, one call each: the writer sees the whole plan (so names and connections agree), the files
this one uses (already written, cut to settings.FILE_CONTEXT_CHARS) and, for a file that exists, its current text;
never the whole project. Hard files -> the smart model, easy ones -> the fast model (models.py)."""
from __future__ import annotations

import re

from coder.memory import card as memory
from coder.llm import models
from coder.core import safety
from coder.core import settings
from coder.core.run import FileSpec, Run

_SYS = ("You are a senior engineer writing ONE file of a project, production quality: correct, complete, clean and "
        "readable, consistent with the plan (same file names, ids, function names and APIs as the other files), short "
        "comments where they help, no placeholders or TODOs for core features, nothing that needs a GPU. Never put "
        "secrets in code (read them from environment variables). Never reference image, sound or font files that "
        "are not in the plan: draw with inline SVG, emoji, CSS or code instead. For a UI: modern and polished (a clear "
        "visual hierarchy, a pleasant colour palette, spacing, hover/active states, small transitions), responsive "
        "and accessible. "
        "Reply with ONLY the complete file content in one fenced code block.")
_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)


def plan_brief(run: Run) -> str:
    files = "\n".join(f"- {f.path}: {f.purpose}" + (f" (uses {', '.join(f.uses)})" if f.uses else "") for f in run.files)
    return (f"Project: {run.plan_name}\nRequest: {run.request}\nStack: {run.stack or 'auto'}"
            + (f" (scaffold: {run.scaffold})" if run.scaffold else "") + f"\nFiles:\n{files}\n"
            + (f"How they connect: {run.notes}\n" if run.notes else "") + (f"Run: {run.run_cmd}\n" if run.run_cmd else ""))


def code_of(reply: str) -> str:
    m = _FENCE.search(reply or "")
    body = m.group(1) if m else (reply or "")
    return body.strip("\n") + "\n"


def _show(run: Run, rel: str) -> str:
    p = run.root / rel
    try:
        t = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return t if len(t) <= settings.FILE_CONTEXT_CHARS else t[: settings.FILE_CONTEXT_CHARS] + "\n… (cut)"


def run_memory(run: Run, f: FileSpec) -> str:
    """The run's own short memory: every file written so far and what it defines (functions, classes, ids), so a
    long build (a whole website) stays consistent without re-sending whole files. 0 tokens (repomap)."""
    from coder.memory import repomap
    lines = []
    for rel in run.written:
        if rel == f.path:
            continue
        p = run.root / rel
        syms = repomap.symbols(p)
        if p.suffix == ".html":
            try:
                ids = __import__("re").findall(r"""\bid\s*=\s*["']([\w-]+)""", p.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                ids = []
            syms = syms + [f"#{i}" for i in ids[:25]]
        purpose = next((x.purpose for x in run.files if x.path == rel), "")
        lines.append(f"- {rel}: {purpose}" + (f" | defines: {', '.join(syms[:25])}" if syms else ""))
    return "\n".join(lines)


def related(run: Run, f: FileSpec) -> list[str]:
    """The already-written files this one must agree with: the ones it uses, then the ones that use it (script.js
    must use the ids index.html has: 11-06 the first build's script looked for #result-message, the page had
    #round-result)."""
    users = [o.path for o in run.files if f.path in o.uses]
    out = [u for u in dict.fromkeys([*f.uses, *users]) if u != f.path and (run.root / u).exists()]
    return out


def write_one(run: Run, f: FileSpec) -> str:
    """Write one planned file. Returns '' or a problem line."""
    parts = [plan_brief(run)]
    if mem := memory.read(run.root, 1500):
        parts.append("Project memory:\n" + mem)
    if done := run_memory(run, f):
        parts.append("Written so far in this run (what each file defines):\n" + done)
    for u in related(run, f)[:3]:
        if shown := _show(run, u):
            parts.append(f"--- {u} (already written: use exactly its names, ids and classes) ---\n{shown}")
    target, cur_len = run.root / f.path, 0
    if target.exists():  # an existing file is rewritten from ALL of it (never from a cut view: that loses code)
        cur = target.read_text(encoding="utf-8", errors="replace")
        if len(cur) > settings.MAX_REWRITE_CHARS:
            return (f"{f.path}: too long ({len(cur) // 1000}k characters) to rewrite safely in one go; say 'ask "
                    "ChatGPT about this' for a big change there")
        parts.append(f"--- {f.path} (current content: change it as the plan says, keep everything else) ---\n{cur}")
        cur_len = len(cur)
    parts.append(f"Write the complete file `{f.path}`: {f.purpose}")
    want = min(6000, max(settings.TOKENS[f.level] * 2, cur_len // 3 + 800))  # room for the whole file
    try:
        reply = models.ask(run, "easy" if f.level == "easy" else "hard" if f.level == "hard" else "normal",
                           _SYS, "\n\n".join(parts), want)
    except Exception as e:  # noqa: BLE001 - one file failing must not lose the others
        return f"{f.path}: the AI call failed ({str(e)[:120]})"
    body = code_of(reply)
    if len(body.strip()) < 2:
        return f"{f.path}: the AI returned nothing"
    safety.write(run, f.path, body)
    run.written.append(f.path)
    return ""
