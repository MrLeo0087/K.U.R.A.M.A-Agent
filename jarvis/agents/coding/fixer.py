"""Crash -> fix (owner: no more copy-pasting errors to ChatGPT). The last failed terminal command (or a pasted
error) is read here: the traceback's frames in the user's own files give the code to send (whole small files, the
crashing function +- context in big ones), so one smart call (~2-5k tokens) returns the fix as file blocks; it is
staged (diff in the workspace, yes applies + runs the command again). A missing module needs no AI at all:
"pip install <it>" in the project's venv. Error memory (errmem) adds how this error was fixed before.
"""
from __future__ import annotations

import re
from pathlib import Path

from jarvis.agents.coding import blocks, changes, terminal
from jarvis.core import config, editor, errmem

_SYS = ("You fix bugs in the user's project. First line: 'CAUSE: <one short sentence>'. Then the fix. "
        + blocks.FORMAT_RULE + " Change as little as possible; keep names and behaviour; no explanations after the code.")
_MOD = re.compile(r"ModuleNotFoundError: No module named '([\w.]+)'|ImportError: No module named ([\w.]+)")
PIP_NAMES = {"cv2": "opencv-python", "PIL": "pillow", "sklearn": "scikit-learn", "yaml": "pyyaml", "bs4": "beautifulsoup4",
             "dotenv": "python-dotenv", "docx": "python-docx", "fitz": "pymupdf", "Crypto": "pycryptodome"}


def _root(fail: dict) -> Path:
    cwd = Path(fail.get("cwd") or ".")
    for s in editor.states():
        if s.get("root") and str(cwd).startswith(s["root"]):
            return Path(s["root"])
    return cwd if cwd.is_dir() else Path.home()


def _venv_python(root: Path) -> str:
    for d in (".venv", "venv", "env"):
        if (root / d / "bin" / "python").exists():
            return str(root / d / "bin" / "python")
    return "python3"


def _snippet(path: Path, line: int) -> str:
    text = editor.read(path)
    lines = text.splitlines()
    if len(lines) <= config.AGENT_WHOLE_FILE_LINES:
        return text
    lo, hi = max(0, line - 60), min(len(lines), line + 40)
    return f"(lines {lo + 1}-{hi} of {len(lines)})\n" + "\n".join(lines[lo:hi])


def fix(error_text: str = "", hint: str = "") -> str:
    """Fix the last crash (or the pasted error). Shows the change and waits for yes."""
    fail = terminal.last() or {}
    if error_text.strip():
        fail = {"command": fail.get("command", ""), "cwd": fail.get("cwd", ""), "output": error_text}
    if not fail.get("output"):
        return ("I haven't seen a crash yet. With the coding agent on, run your code in the VS Code terminal; when it "
                "fails I'll offer the fix. Or paste the error here.")
    out = fail["output"]
    root = _root(fail)
    p = errmem.parse(out)
    if (m := _MOD.search(out)) and fail.get("command"):  # 0 tokens: install the missing package, then run again
        mod = (m.group(1) or m.group(2)).split(".")[0]
        pkg = PIP_NAMES.get(mod, mod)
        cmd = f"{_venv_python(root)} -m pip install {pkg} && {fail['command']}"
        changes._pending.clear()
        changes._pending.update(files={}, title=f"install {pkg}", then=cmd, cwd=str(root),
                                until=__import__("time").time() + config.AGENT_PENDING_TTL_S)
        return f"The package '{pkg}' is missing. Say yes and I'll install it into this project and run it again."
    frames = [f for f in errmem.user_frames(p.get("frames") or []) if Path(f[0]).exists()]
    files: dict[str, str] = {}
    for path, line, _ in frames[-config.AGENT_FIX_MAX_FILES:]:
        files.setdefault(path, _snippet(Path(path), line))
    if not files and (f := _open_file()):
        files[str(f)] = _snippet(f, 1)
    if not files:
        return f"I can't tell which file this error comes from:\n{p.get('error') or out[-300:]}\nOpen the file in VS Code and say 'fix it' again."
    known = errmem.lookup(p["error"]) if p.get("error") else None
    rel = {k: (str(Path(k).relative_to(root)) if k.startswith(str(root)) else k) for k in files}
    user = (f"Command: {fail.get('command') or '?'}\nError output (end):\n{out[-2500:]}\n\n"
            + "".join(f"# file: {rel[k]}\n```\n{v}\n```\n" for k, v in files.items())
            + (f"\nLast time this error was fixed by: {known['fix']}" if known and known.get("fix") else "")
            + (f"\nThe user says: {hint}" if hint else ""))
    from jarvis.core import llm
    reply = str(llm.chat([{"role": "system", "content": _SYS}, {"role": "user", "content": user}], tier="smart",
                         purpose="agent_fix", max_tokens=config.AGENT_FIX_MAX_TOKENS))
    cause = (re.search(r"CAUSE:\s*(.+)", reply) or [None, ""])[1].strip()
    new = blocks.to_files(reply, root)
    if not new:  # an explanation without code (e.g. "why did it crash?"): say it, offer the change / the big AI
        why = cause or re.sub(r"```.*?```", "", reply, flags=re.S).strip()[:400]
        return (f"{why or 'I could not work out a fix.'}\nSay 'fix it' for the code change, or 'ask ChatGPT about this "
                f"error' for a bigger look.")
    if p.get("error") and cause:  # remembered (0 tokens): the same error later is explained from memory
        errmem._save(p["error"], p.get("kind", ""), cause, ", ".join(Path(f).name for f in files))
        errmem.remember_fix(f"KURAMA's fix: {cause}", p["error"])
    msg = changes.stage(new, f"Fix: {p.get('error') or fail.get('command')}"[:80], then=fail.get("command", ""),
                        cwd=fail.get("cwd", ""), note=f"Cause: {cause}" if cause else "")
    return (f"Cause: {cause}\n" if cause else "") + msg


def _open_file() -> Path | None:
    from jarvis.core import context
    return context.snapshot().get("file")
