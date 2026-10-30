"""Read code answers (from Groq, or pasted from ChatGPT / Gemini / Claude) as file changes: each fenced block names
its file ('# file: app/main.py' first line, a ```python app/main.py fence, or the path on the line before the
block). Python blocks that hold only some functions are patched into the file (code_to_file.patch_python); any
other block is the whole new file. 0 tokens.
"""
from __future__ import annotations

import re
from pathlib import Path

_FENCE = re.compile(r"```([^\n`]*)\n(.*?)```", re.S)
_HEAD = re.compile(r"^\s*(?:#|//|--|<!--|/\*)\s*(?:file(?:name)?|path)\s*[:=]\s*(?P<p>[^\s*>]+)\s*(?:-->|\*/)?\s*$", re.I)
_PATHLIKE = re.compile(r"(?:^|[\s`*'\"(])(?P<p>[\w./~-]+\.[A-Za-z0-9]{1,6}|requirements\.txt|Dockerfile|Makefile)[`*'\":)]*\s*$")

FORMAT_RULE = ("Reply with each file you add or change as a fenced code block whose FIRST line is a comment with its "
               "path relative to the project root, like `# file: app/main.py` (`// file: ...` for JS). For a Python "
               "file you change, the block may hold only the complete functions/classes you change plus new imports; "
               "any other file: its complete content.")


def parse(text: str) -> list[tuple[str, str]]:
    """[(relative path, code)] in order; blocks without a recognisable path are skipped."""
    out: list[tuple[str, str]] = []
    for m in _FENCE.finditer(text or ""):
        info, body = m.group(1).strip(), m.group(2)
        lines = body.split("\n")
        path = ""
        if lines and (h := _HEAD.match(lines[0])):
            path, body = h.group("p"), "\n".join(lines[1:])
        elif (parts := info.split()) and len(parts) > 1 and "." in parts[-1]:
            path = parts[-1]  # ```python app/main.py
        elif info and "/" in info or re.fullmatch(r"[\w-]+\.[A-Za-z0-9]{1,6}", info or ""):
            path = info  # ```app/main.py
        else:
            before = text[:m.start()].rstrip().rsplit("\n", 1)[-1]
            if pm := _PATHLIKE.search(before):
                path = pm.group("p")
        path = re.sub(r"^(?:\./)+", "", path.strip("`*'\""))
        if path:
            out.append((path, body.rstrip("\n") + "\n"))
    return out


def _main_span(tree) -> tuple[int, int] | None:
    """(first, last) line of the top-level `if __name__ == "__main__":` block, 1-based."""
    import ast
    for n in tree.body:
        if isinstance(n, ast.If) and "__name__" in ast.unparse(n.test):
            return n.lineno, n.end_lineno
    return None


def patch_main(old: str, code: str) -> str | None:
    """Patch functions/classes/imports (code_to_file.patch_python) AND the `if __name__ == "__main__":` block into the
    file; None when the result isn't valid Python or nothing could be placed."""
    import ast
    from jarvis.tools.general.code_to_file import patch_python
    try:
        ctree = ast.parse(code)
    except SyntaxError:
        return None
    lines = code.splitlines()
    span = _main_span(ctree)
    main_src = "\n".join(lines[span[0] - 1: span[1]]) if span else ""
    rest = "\n".join(lines[: span[0] - 1] + lines[span[1]:]) if span else code
    out = old
    if rest.strip():
        out = patch_python(old, rest)
        if out is None:
            return None
    if main_src:
        try:
            otree = ast.parse(out)
        except SyntaxError:
            return None
        olines = out.splitlines()
        if (ospan := _main_span(otree)) is not None:
            olines[ospan[0] - 1: ospan[1]] = main_src.splitlines()
        else:
            olines += ["", "", *main_src.splitlines()]
        out = "\n".join(olines) + "\n"
    try:
        ast.parse(out)
    except SyntaxError:
        return None
    return out if out != old else None


def to_files(text: str, root: Path) -> dict[Path, str]:
    """{absolute path: complete new text}, Python partial blocks patched into the current file."""
    skipped.clear()
    from jarvis.core import editor
    files: dict[Path, str] = {}
    for rel, code in parse(text):
        p = Path(rel).expanduser()
        p = p if p.is_absolute() else (root / rel)
        p = p.resolve()
        if not str(p).startswith(str(root.resolve()) + "/"):
            continue  # '../../x' or an absolute path elsewhere: never outside the project
        old = files.get(p) or (editor.read(p) if p.exists() else "")
        if p.suffix != ".py" or not old.strip() or _whole(old, code):
            files[p] = code
        elif patched := patch_main(old, code):
            files[p] = patched
        else:  # a piece we can't place: NEVER written as the whole file (that once turned 58 lines into 2)
            skipped.append(rel)
    return files


skipped: list[str] = []  # files of the last to_files() whose code could not be placed safely


def _whole(old: str, new: str) -> bool:
    """The block is the complete file (not just some functions): it keeps most of the old top-level names AND, when
    the file has other top-level code (a main block, calls, constants), some of that too."""
    import ast
    names = lambda s: set(re.findall(r"^(?:async\s+)?(?:def|class)\s+(\w+)", s, re.M))  # noqa: E731

    def others(src: str) -> int:
        try:
            body = ast.parse(src).body
        except SyntaxError:
            return 0
        return sum(not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom))
                   and not (isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant)) for n in body)
    o, n = names(old), names(new)
    if others(old) and not others(new):
        return False  # only functions came back: a patch
    return not o or len(o & n) >= max(1, int(len(o) * 0.8))
