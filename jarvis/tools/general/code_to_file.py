"""code_to_file: write code into the file open in VS Code (or a given path), like an editor assistant:
"write a function that ... in this file" -> the AI reads the file (empty is fine), writes the COMPLETE new file
(your code kept when it belongs) and it replaces the file after one yes (backup kept). With no description
("write the generated code here"), the code of the last code request is used. Only code ever goes in."""
from __future__ import annotations

import re
import time
from pathlib import Path

from jarvis.core import config, safety
from jarvis.core.registry import tool

_CODE_EXT = {".py", ".js", ".ts", ".sh", ".go", ".rs", ".java", ".cpp", ".c", ".rb", ".php", ".html", ".css", ".sql"}
# the "where to put it" words; what is left over is the description of the code
_WHERE = re.compile(r"/\S+|\b[\w-]+\.\w{1,5}\b|\b(?:write|generate|create|make|put|paste|insert|add|save|copy|replace|"
                    r"the|this|that|it|a|an|code|codes|generated|new|whole|in|into|to|on|inside|at|open|opened|oopen|"
                    r"current|file|path|vs|vscode|editor|only|just|please|and|here|there|my)\b", re.I)
_EDIT_PROMPT = ("You are an expert programmer editing one file. You get the file's current content (maybe empty) and "
                "a request. Reply with the COMPLETE new content of the file in ONE Markdown fenced code block and "
                "nothing else: working, well organized, runnable code with imports, type hints, docstrings, error "
                "handling and logging when asked, and a short `if __name__ == \"__main__\":` example when it helps. "
                "Keep the existing code when the request adds to it; replace it when the request asks for new code.")


def _spec(request: str) -> str:
    """The description of the code in the request ('' when it only says where to put it)."""
    rest = re.findall(r"[^\W\d_]{2,}", _WHERE.sub(" ", request or ""))
    return request.strip() if len(rest) >= 3 else ""


def _last_spec() -> str:
    """The user's most recent message that described code (the request before 'write it into the file')."""
    try:
        from langchain_core.messages import HumanMessage
        from jarvis.core.agent import get_agent
        for m in reversed(get_agent().history):
            if isinstance(m, HumanMessage) and (s := _spec(str(m.content))) and \
                    re.search(r"\b(?:code|function|module|script|class|program|def|async|pandas|api)\b", s, re.I):
                return s
    except Exception:  # noqa: BLE001
        pass
    return ""


def latest_code() -> str:
    """The code of the last code job (a code file, or the fenced blocks of a Markdown answer)."""
    from jarvis.core import store
    from jarvis.core.writer import code_only
    for j in store.jobs_list(10):
        p = Path(j.get("output_path") or "")
        if j.get("kind") == "code" and p.is_file():
            text = p.read_text(errors="replace")
            return text if p.suffix in _CODE_EXT else code_only(text) if "```" in text else ""
    return ""


def generate(request: str, target: Path, old: str) -> str:
    from jarvis.core import llm
    from jarvis.core.writer import code_only
    reply = llm.chat([{"role": "system", "content": _EDIT_PROMPT},
                      {"role": "user", "content": f"File: {target.name}\nCurrent content:\n```\n{old[-12000:]}\n```\n"
                                                  f"Request: {request}"}],
                     tier="smart", purpose="code_file", max_tokens=config.CODE_FILE_MAX_TOKENS)
    return code_only(str(reply))


def _dirty_note(target: Path) -> str:
    """VS Code never reloads a file that has unsaved edits (● in its tab): say how to see the new code."""
    try:
        from jarvis.core import rewrite
        wid, _ = rewrite.target_window()
        title = rewrite._window_name(wid) if wid else ""
    except Exception:  # noqa: BLE001
        return ""
    if title.lstrip().startswith(("●", "•")) and target.name in title:
        return (f" VS Code still shows your unsaved version of {target.name}: press Ctrl+Shift+P, type "
                f"'Revert File' and Enter to see the new code.")
    return ""


def _backup(target: Path, old: str) -> None:
    backup = Path(config.DATA_DIR) / "backups" / f"{target.name}.{time.strftime('%Y%m%d-%H%M%S')}"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(old, encoding="utf-8")


def _start_job(spec: str, target: Path) -> str:
    """Generate in the background, then write the file (you asked for this file; the old version is backed up)."""
    from jarvis.core import jobs

    def run(ctx) -> str | None:
        ctx.progress(f"writing the code for {target.name}")
        old = target.read_text(errors="replace") if target.is_file() else ""
        body = generate(spec, target, old)
        ctx.check()
        if not body.strip():
            ctx.progress("» No code came back; nothing changed.")
            return None
        if old.strip():
            _backup(target, old)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        copy = Path(config.OUTPUTS_DIR) / "code" / f"{target.stem}-{time.strftime('%H%M%S')}{target.suffix or '.txt'}"
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_text(body, encoding="utf-8")
        ctx.progress(f"» Wrote {len(body.splitlines())} lines of code into {target.name}"
                     + (" (the old version is backed up)." if old.strip() else ".") + _dirty_note(target))
        return str(copy)
    jobs.get_manager().submit(f"Write code into {target.name}", "code", run)
    return f"Writing the code into {target.name}… I'll tell you when it's there (about 20 seconds)."


def _target(path: str) -> Path | None:
    from jarvis.core import assist, context
    if path.strip():
        p = Path(path.strip()).expanduser()
        if p.is_absolute():
            return p
        from jarvis.core.paths import smart_path
        return smart_path(path.strip(), want="file") or None
    return context.snapshot().get("file") or assist.open_file_in_editor()


@tool(group="clipboard", safety="safe",
      description="Write code into the file open in VS Code (or `path`), like an editor assistant: `request` = what "
                  "the code should do (it reads the file, writes the complete runnable file, replaces it after one "
                  "yes, backup kept); empty request = the code of the last code request. `code` = exact code to put.")
def code_to_file(request: str = "", path: str = "", code: str = "") -> str:
    """Code into a file.

    Args:
        request: What the code should do (the user's words); empty = the code from the last code request.
        path: The file (empty = the one open in VS Code).
        code: Exact code to write instead of generating it.
    """
    from jarvis.core.writer import code_only
    target = _target(path)
    if target is None:
        return "error: open the file in VS Code (or give its full path), then ask again"
    target = Path(target)
    old = target.read_text(errors="replace") if target.is_file() else ""
    spec = _spec(request)
    body = code_only(code) if code.strip() else "" if spec else latest_code()  # "put it in test.py": the code we have
    if not body.strip() and not code.strip():
        spec = spec or _last_spec()
        if spec:  # writing a whole file takes 10-40 s: a background job, never a stuck reply
            return _start_job(spec, target)
    if not body.strip():
        return "error: tell me what the code should do (or ask me to write the code first)"
    if old.strip() and old.strip() != body.strip():
        if not safety.ask(f"Write the new code into {target.name}? ({len(body.splitlines())} lines; "
                          f"the old version is backed up)"):
            return "The user declined: the file was not changed."
        _backup(target, old)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return f"Wrote {len(body.splitlines())} lines of code into {target.name}." + _dirty_note(target)
