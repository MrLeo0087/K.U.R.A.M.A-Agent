"""code_to_file: write code into the file open in VS Code (or a given path), like an editor assistant:
"write a function that ... in this file" -> the AI reads the file (empty is fine), writes the COMPLETE new file
(your code kept when it belongs) and it replaces the file after one yes (backup kept). With no description
("write the generated code here"), the code of the last code request is used. Only code ever goes in."""
from __future__ import annotations

import re
import time
from pathlib import Path

from jarvis.core import config
from jarvis.core.registry import tool

_CODE_EXT = {".py", ".js", ".ts", ".sh", ".go", ".rs", ".java", ".cpp", ".c", ".rb", ".php", ".html", ".css", ".sql"}
# the "where to put it" words; what is left over is the description of the code
_WHERE = re.compile(r"/\S+|\b[\w-]+\.\w{1,5}\b|\b(?:write|generate|create|make|put|paste|insert|add|save|copy|replace|"
                    r"the|this|that|it|a|an|code|codes|generated|new|whole|in|into|to|on|inside|at|open|opened|oopen|"
                    r"current|file|path|vs|vscode|editor|only|just|please|and|here|there|my)\b", re.I)
_EDIT_PROMPT = ("You are an expert programmer editing one file. You get the file's current content (maybe empty) and "
                "a request. Reply with the COMPLETE new content of the file in ONE Markdown fenced code block and "
                "nothing else. Keep every existing line exactly as it is unless the request asks to change it: "
                "'complete' = add only what is missing (unfinished functions, missing imports, a main block); new "
                "code = working, well organized, runnable, with imports, type hints, docstrings, error handling and "
                "logging when asked. An empty file gets the whole new code.")


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
    """The code KURAMA wrote last: a code block in its last chat answer, else the last code job's output."""
    from jarvis.core import store
    from jarvis.core.writer import code_only
    try:
        from langchain_core.messages import AIMessage
        from jarvis.core.agent import get_agent
        for m in reversed(get_agent().history[-4:]):
            if isinstance(m, AIMessage) and "```" in str(m.content):
                return code_only(str(m.content))
    except Exception:  # noqa: BLE001
        pass
    for j in store.jobs_list(10):
        p = Path(j.get("output_path") or "")
        if j.get("kind") == "code" and p.is_file():
            text = p.read_text(errors="replace")
            return text if p.suffix in _CODE_EXT else code_only(text) if "```" in text else ""
    return ""


_PATCH_PROMPT = ("You are an expert programmer editing an existing Python file. Reply with ONE Markdown fenced code "
                 "block holding ONLY what must change: new import lines, and each function or method you add or "
                 "change, written out complete (a method inside its `class Name:` line, indented as in the file). "
                 "Return only the function(s) the request is about and new helpers/imports they need; never return "
                 "a function that already works, even to tidy it. Keep names and signatures unless asked.")


def _blocks(tree) -> dict:
    """name -> node for the top-level functions / classes of a module."""
    import ast
    return {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


def _span(node) -> tuple[int, int]:
    """0-based [start, end) lines of a def/class, decorators included."""
    start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])]) - 1
    return start, node.end_lineno


def _indent(lines: list[str], width: int) -> list[str]:
    import textwrap
    body = textwrap.dedent("\n".join(lines)).splitlines()
    return [(" " * width + ln) if ln.strip() else "" for ln in body]


def patch_python(old: str, patch: str) -> str | None:
    """Apply a patch of complete functions / methods / imports to `old`: same name = replaced in place, new =
    added (methods at the end of their class, functions before `if __name__`). None when it can't be applied."""
    import ast
    try:
        new_tree, old_tree = ast.parse(patch), ast.parse(old)
    except SyntaxError:
        return None
    lines, plines = old.splitlines(), patch.splitlines()
    edits: list[tuple[int, int, list[str]]] = []  # (start, end, replacement lines) on the old file
    have = _blocks(old_tree)
    imports = [plines[n.lineno - 1:n.end_lineno] for n in new_tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    imports = [ln for block in imports for ln in block if ln.strip() not in {x.strip() for x in lines}]
    tail_add: list[str] = []
    for name, node in _blocks(new_tree).items():
        a, b = _span(node)
        src = plines[a:b]
        if name in have and isinstance(node, ast.ClassDef) and isinstance(have[name], ast.ClassDef):
            cls = have[name]
            methods = _blocks(cls)
            width = cls.body[0].col_offset if cls.body else cls.col_offset + 4
            insert_at = cls.end_lineno
            for m in node.body:
                if not isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                ma, mb = _span(m)
                msrc = _indent(plines[ma:mb], width)
                if m.name in methods:
                    edits.append((*_span(methods[m.name]), msrc))
                else:
                    edits.append((insert_at, insert_at, [""] + msrc))
        elif name in have:
            edits.append((*_span(have[name]), _indent(src, 0)))
        else:
            tail_add += ["", ""] + _indent(src, 0)
    if not edits and not imports and not tail_add:
        return None
    for a, b, rep in sorted(edits, key=lambda e: e[0], reverse=True):
        lines[a:b] = rep
    if tail_add:
        main = next((i for i, ln in enumerate(lines) if ln.startswith("if __name__")), len(lines))
        lines[main:main] = tail_add + ([""] if main < len(lines) else [])
    if imports:
        last = max((n.end_lineno for n in old_tree.body if isinstance(n, (ast.Import, ast.ImportFrom))), default=0)
        lines[last:last] = imports
    out = "\n".join(lines).rstrip() + "\n"
    try:
        ast.parse(out)
    except SyntaxError:
        return None
    return out


def generate(request: str, target: Path, old: str) -> str:
    """The new content of the file. A Python file with code gets a PATCH (only the functions that change or are
    added), applied in place; anything else (or a patch that can't be applied) gets the complete file."""
    from jarvis.core import llm
    from jarvis.core.writer import code_only
    if old.strip() and target.suffix == ".py":
        reply = llm.chat([{"role": "system", "content": _PATCH_PROMPT},
                          {"role": "user", "content": f"File: {target.name}\n```python\n{old[-12000:]}\n```\n"
                                                      f"Request: {request}"}],
                         tier="smart", purpose="code_patch", max_tokens=config.CODE_FILE_MAX_TOKENS)
        if (patched := patch_python(old, code_only(str(reply)))) is not None:
            return patched
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


def _put(target: Path, old: str, body: str, ctx=None) -> str:
    """A blank file is written at once; a file with code gets the change staged: 'yes' applies it (backup kept)."""
    from jarvis.core import assist
    copy = Path(config.OUTPUTS_DIR) / "code" / f"{target.stem}-{time.strftime('%H%M%S')}{target.suffix or '.txt'}"
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_text(body, encoding="utf-8")
    if not old.strip():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        return f"Wrote {len(body.splitlines())} lines of code into {target.name}." + _dirty_note(target)
    if old.strip() == body.strip():
        return f"{target.name} already has this code."
    what = assist.stage_file_change(target, old, body)
    return f"Ready for {target.name}: {what}. It's in the workspace. Should I add it? (yes / no)"


def start_edit(spec: str, target: Path | None = None) -> str:
    """Generate in the background: the AI reads the file and returns it with only what's missing added / what was
    asked changed; the change then waits for your yes."""
    from jarvis.core import jobs
    target = target or _target("")
    if target is None:
        return "error: open the file in VS Code (or give its full path), then ask again"

    def run(ctx) -> str | None:
        ctx.progress(f"working on {target.name}")
        old = target.read_text(errors="replace") if target.is_file() else ""
        body = generate(spec, target, old)
        ctx.check()
        if not body.strip():
            ctx.progress("» No code came back; nothing changed.")
            return None
        ctx.progress("» " + _put(target, old, body))
        return None
    jobs.get_manager().submit(f"Code for {target.name}", "code", run)
    return f"Working on {target.name}… I'll show you what I add and ask before changing it."


def _start_job(spec: str, target: Path) -> str:
    return start_edit(spec, target)


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
    spec = _spec(request) or (request.strip() if re.search(r"\b(?:complete|finish)\b", request or "", re.I) else "")
    body = code_only(code) if code.strip() else "" if spec else latest_code()  # "put it in test.py": the code we have
    if not body.strip() and not code.strip():
        spec = spec or _last_spec()
        if spec:  # writing a whole file takes 10-40 s: a background job, never a stuck reply
            return _start_job(spec, target)
    if not body.strip():
        return "error: tell me what the code should do (or ask me to write the code first)"
    return _put(target, old, body)
