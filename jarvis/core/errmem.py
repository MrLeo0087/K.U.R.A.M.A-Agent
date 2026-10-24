"""Error memory: explain a Python/terminal error once, remember it, and remember how YOU fixed it.

The first time an error shows up, one short fast-tier call explains it from the error line plus the few lines of
YOUR code where it happened (~400-700 tokens). The explanation is stored under a signature that ignores numbers,
paths, names in quotes and memory addresses, so the same error later (another file, another shape) is answered
from memory at 0 tokens, together with the fix you told KURAMA about ("I fixed it by ..."). Training Guard crash
alerts use the same memory.
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from jarvis.core import config, store

_EXC = re.compile(r"^\s*(?P<type>(?:[A-Za-z_][\w.]*\.)?[A-Z]\w*(?:Error|Exception|Exit|Interrupt|Warning)|"
                  r"AssertionError|StopIteration|KeyboardInterrupt)(?::\s*(?P<msg>.*))?$")
_FRAME = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+)(?:, in (?P<fn>\S+))?')
_SHELL = re.compile(r"(?im)^(?:.*?:\s*)?(?:command not found|permission denied|no such file or directory|"
                    r"error:.*|fatal:.*|E:\s.*|npm ERR!.*|ModuleNotFoundError.*|.*\bnot found\b.*)$")


def parse(text: str) -> dict:
    """{'kind': 'ValueError', 'error': 'ValueError: ...', 'frames': [(file, line, fn), ...]} from a traceback or
    terminal output ('' error when nothing recognisable)."""
    lines = [ln.rstrip() for ln in (text or "").splitlines() if ln.strip()]
    frames = [(m.group("file"), int(m.group("line")), m.group("fn") or "") for ln in lines if (m := _FRAME.match(ln))]
    kind = err = ""
    for ln in reversed(lines):
        if m := _EXC.match(ln):
            kind, err = m.group("type").split(".")[-1], ln.strip()
            break
    if not err:
        hits = [m.group(0).strip() for m in _SHELL.finditer(text or "")]
        if hits:
            err, kind = hits[-1], "terminal"
        elif lines:
            err, kind = lines[-1].strip(), "other"
    return {"kind": kind, "error": err[:400], "frames": frames}


def signature(error: str) -> str:
    """Same error, different details -> same signature."""
    s = error.lower()
    s = re.sub(r"0x[0-9a-f]+", "ADDR", s)
    s = re.sub(r"(['\"`]).*?\1", "Q", s)
    s = re.sub(r"(?:/[\w.\-]+)+", "PATH", s)
    s = re.sub(r"\d+(?:\.\d+)?", "N", s)
    s = re.sub(r"\s+", " ", s).strip()
    return hashlib.sha1(s.encode()).hexdigest()[:16]


def user_frames(frames: list[tuple[str, int, str]]) -> list[tuple[str, int, str]]:
    """The frames in the user's own code (not the standard library or installed packages)."""
    return [f for f in frames if "site-packages" not in f[0] and "dist-packages" not in f[0]
            and "/lib/python" not in f[0] and not f[0].startswith("<")]


def code_context(frames: list[tuple[str, int, str]], around: int = 2, max_frames: int = 3) -> str:
    out = []
    for path, line, fn in user_frames(frames)[-max_frames:]:
        try:
            src = Path(path).read_text(errors="replace").splitlines()
        except OSError:
            continue
        lo, hi = max(0, line - 1 - around), min(len(src), line + around)
        body = "\n".join(f"{'>' if i + 1 == line else ' '}{i + 1}: {src[i]}" for i in range(lo, hi))
        out.append(f"{Path(path).name} ({fn}):\n{body}")
    return "\n".join(out)[:1500]


def lookup(error: str) -> dict | None:
    rows = store._exec("SELECT * FROM errors WHERE sig=?", (signature(error),))
    return dict(rows[0]) if rows else None


def _save(error: str, kind: str, explanation: str, where: str) -> dict:
    now = time.time()
    store._exec("INSERT INTO errors(sig, error, kind, explanation, fix, where_, count, first_seen, last_seen) "
                "VALUES (?,?,?,?,?,?,1,?,?) ON CONFLICT(sig) DO UPDATE SET count=count+1, last_seen=excluded.last_seen,"
                " explanation=COALESCE(NULLIF(errors.explanation,''), excluded.explanation)",
                (signature(error), error[:400], kind, explanation, "", where, now, now))
    store.kv_set("errmem_last", signature(error))
    return lookup(error) or {}


PROMPT = ("Explain this error for a Python/ML developer in at most 3 short sentences: what it means, the most "
          "likely cause in THEIR code, and the exact fix. Plain text, no preamble.")


def explain(text: str, use_llm: bool = True) -> dict:
    """{'error', 'kind', 'explanation', 'fix', 'count', 'known': bool, 'where'}; known = answered from memory."""
    p = parse(text)
    if not p["error"]:
        return {"error": "", "explanation": "", "known": False}
    hit = lookup(p["error"])
    where = ", ".join(f"{Path(f).name}:{n}" for f, n, _ in user_frames(p["frames"])[-2:])
    if hit and hit.get("explanation"):
        _save(p["error"], p["kind"], hit["explanation"], where)  # count + last seen
        return {**lookup(p["error"]), "error": p["error"], "known": True, "where": where}  # this time's details
    explanation = ""
    if use_llm:
        from jarvis.core import llm
        ctx = code_context(p["frames"])
        try:
            reply = llm.chat([{"role": "system", "content": PROMPT},
                              {"role": "user", "content": f"Error: {p['error']}" + (f"\nTheir code:\n{ctx}" if ctx else "")
                               + ("\nTraceback tail:\n" + "\n".join(text.splitlines()[-8:])[-600:] if not ctx else "")}],
                             tier="fast", purpose="error_explain", max_tokens=300, temperature=0)
            explanation = " ".join(str(reply).split())[:600]
        except Exception:
            explanation = ""
    row = _save(p["error"], p["kind"], explanation, where)
    return {**row, "error": p["error"], "known": False, "where": where}


def remember_fix(fix: str, error: str = "") -> str:
    sig = signature(error) if error else store.kv_get("errmem_last")
    if not sig or not store._exec("SELECT 1 FROM errors WHERE sig=?", (sig,)):
        return "error: which error did you fix? (explain it to me first, or paste it)"
    store._exec("UPDATE errors SET fix=? WHERE sig=?", (fix.strip()[:500], sig))
    row = store._exec("SELECT error FROM errors WHERE sig=?", (sig,))[0]
    return f"Got it. Next time I see \"{row['error'][:80]}\" I'll remind you: {fix.strip()[:120]}"


def recent(n: int = 8) -> list[dict]:
    return [dict(r) for r in store._exec("SELECT * FROM errors ORDER BY last_seen DESC LIMIT ?", (n,))]


def answer(r: dict) -> str:
    """The user-facing text for one explained error."""
    if not r.get("error"):
        return "I couldn't find an error in that. Paste the full traceback (or copy it and ask again)."
    head = r["error"][:200]
    seen = f" You've hit this {r['count']} times." if r.get("count", 1) > 1 else ""
    body = r.get("explanation") or "I couldn't explain it right now (the model is busy); try again in a minute."
    fix = f"\nLast time you fixed it by: {r['fix']}" if r.get("fix") else ""
    where = f" (at {r['where']})" if r.get("where") else ""
    return f"{head}{where}\n{body}{seen}{fix}"
