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
        + blocks.FORMAT_RULE + " Understand the whole cause first and fix it COMPLETELY in one go: the crash AND every "
        "listed problem, in every file involved (callers and callees agree on names and parameters), so the next run "
        "doesn't crash on the next line. Otherwise change as little as possible; keep names and behaviour; no "
        "explanations after the code.")
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


_PIP_CHAIN = re.compile(r"^(?:python3 -m venv \S+ && )?\S*python3?\S* -m pip install [^&]+&&\s*")


def with_python(command: str, py: str) -> str:
    """'python3 main.py' -> '<py> main.py'; an earlier 'pip install X && ' in front is dropped (installed already)."""
    cmd = _PIP_CHAIN.sub("", (command or "").strip())
    return re.sub(r"^(?:\S*/)?python3?(?=\s)", py, cmd, count=1)


def _snippet(path: Path, line: int) -> str:
    text = editor.read(path)
    lines = text.splitlines()
    if len(lines) <= config.AGENT_WHOLE_FILE_LINES:
        return text
    lo, hi = max(0, line - 60), min(len(lines), line + 40)
    return f"(lines {lo + 1}-{hi} of {len(lines)})\n" + "\n".join(lines[lo:hi])


def fix(error_text: str = "", hint: str = "", confirmed: bool = False) -> str:
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
        py = _venv_python(root)
        make = ""
        if py == "python3":  # no venv yet: make one (installing into the system Python fails / is refused)
            make, py = "python3 -m venv .venv && ", str(root / ".venv" / "bin" / "python")
        # the SAME python installs and runs it (11-06: installed into .venv, ran with python3: the loop "pygame is
        # missing" -> install -> missing again)
        cmd = f"{make}{py} -m pip install {pkg} && {with_python(fail['command'], py)}"
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
    more = _other_problems(root)  # fix EVERYTHING that's wrong at once, not one crash per round (11-06: a loop)
    for line in more:
        f = root / line.split(":", 1)[0]
        if f.is_file() and len(files) < config.AGENT_FIX_MAX_FILES + 2:
            files.setdefault(str(f), _snippet(f, 1))
    known = errmem.lookup(p["error"]) if p.get("error") else None
    rel = {k: (str(Path(k).relative_to(root)) if k.startswith(str(root)) else k) for k in files}
    user = (f"Command: {fail.get('command') or '?'}\nError output (end):\n{out[-2500:]}\n\n"
            + "".join(f"# file: {rel[k]}\n```\n{v}\n```\n" for k, v in files.items())
            + (f"\nLast time this error was fixed by: {known['fix']}" if known and known.get("fix") else "")
            + (f"\nThe user says: {hint}" if hint else "")
            + ("\nAlso fix these problems found in the project (they would crash next):\n" + "\n".join(
                f"- {x}" for x in more) if more else ""))
    est = (len(_SYS) + len(user)) // 4 + 1200
    if est > config.AGENT_ASK_ABOVE_TOKENS and not confirmed:
        return changes.ask_cost("fix", {"error_text": error_text, "hint": hint}, est, "Fixing this (big files)")
    from jarvis.core import llm
    reply = str(llm.chat([{"role": "system", "content": _SYS}, {"role": "user", "content": user}], tier="smart",
                         purpose="agent_fix", max_tokens=config.AGENT_FIX_MAX_TOKENS))
    cause = (re.search(r"CAUSE:\s*(.+)", reply) or [None, ""])[1].strip()
    new = blocks.to_files(reply, root)
    if blocks.skipped and not new:
        return (f"{('Cause: ' + cause + chr(10)) if cause else ''}I couldn't place the fix safely in "
                f"{', '.join(blocks.skipped)}, so I changed nothing. Say 'ask ChatGPT about this error' for a bigger look.")
    if not new:  # an explanation without code (e.g. "why did it crash?"): say it, offer the change / the big AI
        why = cause or re.sub(r"```.*?```", "", reply, flags=re.S).strip()[:400]
        return (f"{why or 'I could not work out a fix.'}\nSay 'fix it' for the code change, or 'ask ChatGPT about this "
                f"error' for a bigger look.")
    if p.get("error") and cause:  # remembered (0 tokens): the same error later is explained from memory
        errmem._save(p["error"], p.get("kind", ""), cause, ", ".join(Path(f).name for f in files))
        errmem.remember_fix(f"KURAMA's fix: {cause}", p["error"])
    py = _venv_python(root)
    then = with_python(fail.get("command", ""), py) if fail.get("command") and py != "python3" else fail.get("command", "")
    msg = changes.stage(new, f"Fix: {p.get('error') or fail.get('command')}"[:80], then=then,
                        cwd=fail.get("cwd", ""), note=f"Cause: {cause}" if cause else "")
    return (f"Cause: {cause}\n" if cause else "") + msg


def _other_problems(root: Path) -> list[str]:
    """Problems the coding agent's checks see in the project's Python files (0 tokens): names, imports and calls
    that don't match between files."""
    try:
        from coder.builder import connect
        from coder.core.run import new
        return connect._py_names(new("fix", root))[:8]
    except Exception:  # noqa: BLE001
        return []


def _open_file() -> Path | None:
    from jarvis.core import context
    return context.snapshot().get("file")
