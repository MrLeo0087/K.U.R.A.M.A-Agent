"""The big-AI bridge (0 tokens): for work too big for the free Groq models, KURAMA writes ONE ready prompt for
ChatGPT / Gemini / Claude on the web (the task, the last error, the open file + selection, the files the error
points to, the project's file tree, and how to format the answer), copies it and can open the site; when the user
copies the answer, "apply the answer" turns its code blocks into file changes (shown first, yes applies).
"""
from __future__ import annotations

import os
from pathlib import Path

from jarvis.agents.coding import blocks, changes, terminal
from jarvis.core import config, editor, errmem

SITES = {"chatgpt": "https://chatgpt.com/", "gemini": "https://gemini.google.com/app", "claude": "https://claude.ai/new"}
_SKIP = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", "dist", "build",
         ".idea", ".vscode", "data", ".ipynb_checkpoints"}


def project_root() -> Path | None:
    from jarvis.core import context
    s = context.snapshot()
    if s.get("root"):
        return Path(s["root"])
    st = editor.states()
    return Path(st[0]["root"]) if st and st[0].get("root") else None


def tree(root: Path, limit: int = 120) -> str:
    out: list[str] = []
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in _SKIP and not x.startswith("."))
        rel = Path(d).relative_to(root)
        if len(rel.parts) > 3:
            dirs[:] = []
            continue
        for f in sorted(files):
            if not f.startswith(".") and not f.endswith((".pyc", ".lock")):
                out.append(str(rel / f) if str(rel) != "." else f)
            if len(out) >= limit:
                return "\n".join(out) + "\n…"
    return "\n".join(out)


def pack(task: str = "", site: str = "") -> str:
    """Build the prompt, copy it, optionally open the site. Returns what was done."""
    from jarvis.core import context
    from jarvis.core.rewrite import _xclip
    root = project_root()
    snap = context.snapshot()
    fail = terminal.last()
    parts = [f"Task: {task.strip() or ('Fix this error.' if fail else 'Review and improve my code.')}"]
    if fail and (not task or any(w in task.lower() for w in ("error", "fix", "crash", "bug", "fail", "work"))):
        parts.append(f"The command `{fail['command']}` failed:\n```\n{fail['output'][-3000:]}\n```")
    sent: set[str] = set()
    files = []
    if fail:
        files += [Path(f) for f, _, _ in errmem.user_frames(errmem.parse(fail["output"]).get("frames") or [])][-3:]
    if snap.get("file"):
        files.insert(0, Path(snap["file"]))
    for f in files:
        if str(f) in sent or not f.exists():
            continue
        sent.add(str(f))
        rel = f.relative_to(root) if root and str(f).startswith(str(root)) else f
        text = editor.read(f)
        if len(text) > config.AGENT_BRIDGE_FILE_CHARS:
            text = text[: config.AGENT_BRIDGE_FILE_CHARS] + "\n# … (cut)"
        parts.append(f"File `{rel}`:\n```{f.suffix.lstrip('.')}\n{text}\n```")
    if snap.get("selection"):
        parts.append(f"The part I mean (selected):\n```\n{snap['selection'][:3000]}\n```")
    if root:
        parts.append(f"Project `{root.name}` files:\n```\n{tree(root)}\n```")
    parts.append(blocks.FORMAT_RULE)
    prompt = "\n\n".join(parts)
    _xclip(["-selection", "clipboard"], prompt)
    n = len(sent)
    what = f"{'the error, ' if fail else ''}{n} file{'s' if n != 1 else ''}{', the project tree' if root else ''}"
    if (s := (site or "").strip().lower()) in SITES:
        import uuid
        pid = uuid.uuid4().hex[:12]
        _prompts.clear()  # one waiting prompt at a time
        _prompts[pid] = prompt
        from jarvis.tools.general.open_url import _open
        _open(f"{SITES[s]}#kurama={pid}")  # the browser extension pastes it there and presses send
        return (f"Opened {s.title()} with the whole problem ({what}); it is pasted and sent by itself (if not: Ctrl+V, "
                f"Enter). When the answer is there, press its copy button and say 'apply the answer'.")
    return (f"Copied a ready prompt ({len(prompt)} characters: {what}). Paste it there (Ctrl+V); when you have the "
            f"answer, copy it and say 'apply the answer'.")


_prompts: dict[str, str] = {}  # id -> the prompt the browser extension fetches once (memory only)


def take_prompt(pid: str) -> str:
    return _prompts.pop(pid, "")


def apply_answer(text: str = "") -> str:
    """The copied answer (or `text`) -> file changes, shown first; yes applies them."""
    from jarvis.core.rewrite import _xclip
    answer = text if "```" in (text or "") else _xclip(["-selection", "clipboard"])
    if "```" not in (answer or ""):
        return "Copy the AI's whole answer first (the part with the code blocks), then say 'apply the answer'."
    root = project_root()
    if root is None:
        return "Open the project in VS Code first, so I know where the files go."
    files = blocks.to_files(answer, root)
    if not files:
        return ("The answer's code blocks don't say which file they belong to. Ask it to put '# file: <path>' as the "
                "first line of each block (the prompt I copy asks for that).")
    fail = terminal.last()
    if blocks.skipped:  # parts that couldn't be placed safely are left out, and said
        note = f" (left out, couldn't place safely: {', '.join(blocks.skipped)})"
        return changes.stage(files, "Apply the AI's answer", then=fail["command"] if fail else "",
                             cwd=fail["cwd"] if fail else "") + note
    return changes.stage(files, "Apply the AI's answer", then=fail["command"] if fail else "", cwd=fail["cwd"] if fail else "")
