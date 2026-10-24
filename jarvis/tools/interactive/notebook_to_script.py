"""notebook_to_script: convert a Jupyter notebook to a .py script next to it (safe; no LLM).
Code cells in order (with '# %%' markers), markdown/raw cells as comments, IPython magics and !shell lines
turned into comments, outputs never copied. wrap_main=True hoists plain imports and wraps the rest in
main() with an `if __name__ == "__main__"` guard. Overwriting an existing file asks first."""
from __future__ import annotations

import ast
import io
import json
import re
import tokenize
from pathlib import Path

from jarvis.core import safety
from jarvis.core.registry import tool
from jarvis.tools.general import _files

MAGIC = re.compile(r"^\s*(?:%|!)")
SHELL_ASSIGN = re.compile(r"^\s*[A-Za-z_][\w, ]*=\s*[!%]")
HELP = re.compile(r"^\s*(?:\?{1,2}[\w.]+|[\w.]+\?{1,2})\s*$")
PY_CELL_MAGICS = ("%%time", "%%timeit", "%%capture", "%%prun")
IMPORT = re.compile(r"^(?:import\s+[\w.]+(?:\s+as\s+\w+)?(?:\s*,\s*[\w.]+(?:\s+as\s+\w+)?)*"
                    r"|from\s+[\w.]+\s+import\s+[^()\\]+)\s*(?:#.*)?$")


def _src(cell: dict) -> str:
    s = cell.get("source", cell.get("input", ""))
    return "".join(s) if isinstance(s, list) else str(s or "")


def load_cells(nb: dict) -> list[dict]:
    if "cells" in nb:
        return nb["cells"]
    return [c for ws in nb.get("worksheets", []) for c in ws.get("cells", [])]  # nbformat 3


def _comment(text: str, tag: str = "") -> list[str]:
    rows = text.rstrip().splitlines()
    out = [f"# [{tag}]"] if tag else []
    return out + [("# " + r).rstrip() for r in rows]


def clean_code(code: str, stats: dict) -> list[str]:
    rows = code.rstrip().splitlines()
    if not rows:
        return []
    first = rows[0].strip()
    if first.startswith("%%"):
        stats["magics"] += 1
        if first.split()[0] in PY_CELL_MAGICS:
            rows = [f"# {rows[0].strip()}  (cell magic)"] + rows[1:]
        else:
            return [f"# {first}  (cell magic: cell kept as comments)"] + [("# " + r).rstrip() for r in rows[1:]]
    out = []
    for r in rows:
        if r.lstrip().startswith("#"):
            out.append(r)
        elif MAGIC.match(r) or SHELL_ASSIGN.match(r) or HELP.match(r):
            stats["magics"] += 1
            indent = r[:len(r) - len(r.lstrip())]
            out.append(f"{indent}pass  # IPython: {r.strip()}" if indent else f"# IPython: {r.strip()}")
        else:
            out.append(r)
    return out


def _string_rows(code: str) -> set[int]:
    """1-based rows that continue a multi-line string (must not be re-indented)."""
    rows: set[int] = set()
    fstart = []
    try:
        for t in tokenize.generate_tokens(io.StringIO(code).readline):
            if t.type == tokenize.STRING and t.end[0] > t.start[0]:
                rows.update(range(t.start[0] + 1, t.end[0] + 1))
            elif getattr(tokenize, "FSTRING_START", -1) == t.type:
                fstart.append(t.start[0])
            elif getattr(tokenize, "FSTRING_END", -1) == t.type and fstart:
                s = fstart.pop()
                rows.update(range(s + 1, t.end[0] + 1))
    except (tokenize.TokenError, SyntaxError):
        pass
    return rows


def convert(nb: dict, name: str, wrap_main: bool = False) -> tuple[str, dict]:
    stats = {"code": 0, "markdown": 0, "magics": 0}
    blocks: list[list[str]] = []
    for cell in load_cells(nb):
        kind, text = cell.get("cell_type"), _src(cell)
        if not text.strip():
            continue
        if kind == "code":
            rows = clean_code(text, stats)
            if rows:
                stats["code"] += 1
                blocks.append(["# %%"] + rows)
        elif kind in ("markdown", "heading"):
            stats["markdown"] += 1
            blocks.append(["# %% [markdown]"] + _comment(text))
        else:
            blocks.append(_comment(text, "raw"))
    head = f"# Converted from {name} by KURAMA notebook_to_script (outputs removed)."
    if not wrap_main:
        return "\n\n".join([head] + ["\n".join(b) for b in blocks]) + "\n", stats
    imports, body = [], []
    for b in blocks:
        kept = []
        for r in b:
            if IMPORT.match(r) and r == r.lstrip():
                if r not in imports:
                    imports.append(r)
            else:
                kept.append(r)
        if any(x.strip() and x != "# %%" for x in kept):
            body.append("\n".join(kept))
    code = "\n\n".join(body)
    skip = _string_rows(code)
    inner = [("    " + r if r.strip() and i not in skip else r) for i, r in enumerate(code.splitlines(), 1)]
    if not any(r.strip() and not r.strip().startswith("#") for r in inner):
        inner.append("    pass")
    parts = [head, "\n".join(imports)] if imports else [head]
    parts += ["def main() -> None:\n" + "\n".join(inner), 'if __name__ == "__main__":\n    main()']
    return "\n\n\n".join(parts) + "\n", stats


@tool(group="devutils", safety="safe",
      description="Convert a Jupyter notebook (.ipynb) to a .py script next to it; optional main() wrapper.")
def notebook_to_script(path: str, wrap_main: bool = False, output: str = "") -> str:
    """Convert a notebook to a Python script.

    Args:
        path: The .ipynb file.
        wrap_main: Put the code inside a main() function with a __main__ guard.
        output: Output .py path (default: same name next to the notebook).
    """
    p = Path(path).expanduser()
    p = p.resolve() if p.is_absolute() or (Path.cwd() / p).exists() else _files.resolve(path)
    if not p.is_file() or p.suffix != ".ipynb":
        return f"not a notebook (.ipynb): {p}"
    try:
        nb = json.loads(p.read_text("utf-8"))
    except (ValueError, OSError) as e:
        return f"could not read {p.name}: {str(e)[:120]}"
    text, st = convert(nb, p.name, wrap_main)
    out = Path(output).expanduser() if output else p.with_suffix(".py")
    out = out if out.is_absolute() else p.parent / out
    _files.guard(out)
    if out.exists():
        if not safety.ask(f"{out.name} already exists. Overwrite it with the converted notebook?"):
            return f"The user declined: {out} was not overwritten."
    elif not _files.ask_outside(out, "write the script"):
        return "The user declined: nothing written."
    out.write_text(text, encoding="utf-8")
    msg = (f"wrote {out} ({st['code']} code cells, {st['markdown']} markdown as comments, "
           f"{st['magics']} magics/shell lines commented{', wrapped in main()' if wrap_main else ''})")
    try:
        ast.parse(text)
    except SyntaxError as e:
        msg += f"; warning: syntax error at line {e.lineno} (check that cell)"
    return msg
