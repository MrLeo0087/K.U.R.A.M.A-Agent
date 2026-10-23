"""add_docstrings: add missing docstrings and type hints to a Python file (confirm, token-cheap).
ast finds functions/methods missing a docstring or hints; ONLY their sources (<= 2500 chars per batch,
secrets redacted) go to the fast tier with strict json_schema output {name, docstring,
signature_with_hints}. Edits are ast-guided line edits (header + inserted docstring) so the rest of
the file keeps its formatting; a signature is used only if it keeps the same parameters/defaults and
existing hints and uses known names. A diff summary is shown and the file is written only after a yes
(a .bak is kept). More than 10 functions -> background job that caches the proposal; calling again
reviews/applies it with 0 tokens."""
from __future__ import annotations

import ast
import builtins
import difflib
import hashlib
import io
import json
import re
import shutil
import textwrap
import tokenize
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from jarvis.core import config, safety
from jarvis.core.registry import tool
from jarvis.tools.general import _files
from jarvis.tools.interactive import _proc, _secrets

BUDGET = 2500  # chars of function source per LLM call
FUNC_CAP = 1800  # one function's source is cut beyond this (the signature + gist is enough)
BG_FUNCS = 10  # more functions than this -> background job
MAX_CALLS = 12  # batches per run
WRAP_AT = 100  # long new signatures are split one parameter per line
PROMPT = ("You add Python docstrings and type hints. For EACH function given return: name (exactly as given "
          "after '# '), docstring (Google style: one-line summary, then Args:/Returns: only if useful; at most "
          "6 lines; no quotes), signature_with_hints (one line 'def name(...) -> T:' with the SAME parameters, "
          "defaults and order, adding hints; keep existing hints; never annotate self/cls). Use builtin types "
          "(list[str], dict[str, int], X | None) or names from the 'known names' list only.")


class Doc(BaseModel):
    name: str = Field(description="function name exactly as given")
    docstring: str = Field(description="docstring text without quotes")
    signature_with_hints: str = Field(description="one-line def with type hints")


class Docs(BaseModel):
    items: list[Doc]


@dataclass
class Fn:
    qual: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    need_doc: bool
    need_hints: bool
    src: str


# --- discovery ---
def _params(n: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.arg]:
    a = n.args
    return [*a.posonlyargs, *a.args, *([a.vararg] if a.vararg else []), *a.kwonlyargs,
            *([a.kwarg] if a.kwarg else [])]


def _missing_hints(n, method: bool) -> bool:
    ps = _params(n)
    if method and ps and ps[0].arg in ("self", "cls") and not any(
            isinstance(d, ast.Name) and d.id == "staticmethod" for d in n.decorator_list):
        ps = ps[1:]
    return n.returns is None or any(p.annotation is None for p in ps)


def find(tree: ast.Module, lines: list[str], only: str = "") -> list[Fn]:
    """Top-level functions and class methods (not nested helpers) missing a docstring or hints."""
    out: list[Fn] = []

    def visit(body: list[ast.stmt], prefix: str, in_class: bool) -> None:
        for n in body:
            if isinstance(n, ast.ClassDef):
                visit(n.body, f"{prefix}{n.name}.", True)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = prefix + n.name
                if only and only not in (qual, n.name) and not qual.startswith(only + "."):
                    continue
                if any(isinstance(d, ast.Name) and d.id == "overload" or
                       isinstance(d, ast.Attribute) and d.attr == "overload" for d in n.decorator_list):
                    continue
                one_liner = n.body[0].lineno == n.lineno
                need_doc = ast.get_docstring(n) is None and not one_liner
                need_hints = _missing_hints(n, in_class)
                if need_doc or need_hints:
                    out.append(Fn(qual, n, need_doc, need_hints,
                                  "".join(lines[n.lineno - 1:n.end_lineno]).rstrip()))
    visit(tree.body, "", False)
    return out


def known_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for n in tree.body:
        if isinstance(n, ast.Import):
            names.update((a.asname or a.name).split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            names.update(a.asname or a.name for a in n.names if a.name != "*")
        elif isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(n.name)
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif hasattr(ast, "TypeAlias") and isinstance(n, ast.TypeAlias):
            names.add(n.name.id)
    return names


# --- LLM ---
def batches(fns: list[Fn]) -> list[list[Fn]]:
    out, cur, size = [], [], 0
    for f in fns:
        n = min(len(f.src), FUNC_CAP) + len(f.qual) + 4
        if cur and size + n > BUDGET:
            out.append(cur)
            cur, size = [], 0
        cur.append(f)
        size += n
    return out + [cur] if cur else out


def _payload(f: Fn) -> str:
    src = textwrap.dedent(f.src)
    if len(src) > FUNC_CAP:
        src = src[:FUNC_CAP].rsplit("\n", 1)[0] + "\n    ..."
    return f"# {f.qual}\n{_secrets.redact(src)}"


def ask_llm(batch: list[Fn], names: set[str]) -> list[Doc]:
    from jarvis.core import llm

    known = ", ".join(sorted(n for n in names if not n.startswith("_"))[:40]) or "-"
    user = f"known names: {known}\n\n" + "\n\n".join(_payload(f) for f in batch)
    out = llm.structured([{"role": "system", "content": PROMPT}, {"role": "user", "content": user}],
                         Docs, tier="fast", purpose="add_docstrings", max_tokens=1800)
    return list(out.items)


def generate(fns: list[Fn], names: set[str], cancel=None, progress=None) -> tuple[list[Doc], int]:
    """All batches (capped); returns (docs, failed batches)."""
    from jarvis.core import llm

    docs, failed = [], 0
    bs = batches(fns)[:MAX_CALLS]
    for i, b in enumerate(bs, 1):
        if cancel is not None and cancel.is_set():
            break
        if progress:
            progress(f"batch {i}/{len(bs)}")
        try:
            docs += ask_llm(b, names)
        except llm.LLMError:
            failed += 1
    return docs, failed


# --- applying edits ---
def header_end(lines: list[str], n) -> tuple[int, int] | None:
    """(1-based row, col) of the ':' that ends the def header, via tokenize."""
    start, col = n.lineno, n.col_offset
    last = n.body[0].lineno
    chunk = [lines[start - 1][col:]] + lines[start:last]
    depth, seen_def = 0, False
    try:
        for tok in tokenize.generate_tokens(io.StringIO("".join(chunk)).readline):
            if tok.type == tokenize.NAME and tok.string == "def":
                seen_def = True
            elif tok.type == tokenize.OP and seen_def:
                if tok.string in "([{":
                    depth += 1
                elif tok.string in ")]}":
                    depth -= 1
                elif tok.string == ":" and depth == 0:
                    row = start + tok.start[0] - 1
                    return row, tok.start[1] + (col if tok.start[0] == 1 else 0)
    except (tokenize.TokenError, SyntaxError):
        return None
    return None


def _norm(node: ast.AST | None) -> str:
    return ast.dump(node, annotate_fields=False) if node is not None else ""


def _names_in(node: ast.AST | None) -> set[str]:
    return {x.id for x in ast.walk(node) if isinstance(x, ast.Name)} if node is not None else set()


def check_signature(n, sig: str, known: set[str]) -> tuple[str, str]:
    """('async def f(...) -> T:' or '', reason if rejected)."""
    s = re.sub(r"^\s*(?:async\s+)?def\s+", "", (sig or "").strip().strip("`")).rstrip()
    s = s[:-1].rstrip() if s.endswith(":") else s
    text = ("async def " if isinstance(n, ast.AsyncFunctionDef) else "def ") + s + ":"
    try:
        new = ast.parse(text + "\n    pass").body[0]
    except SyntaxError:
        return "", "invalid signature"
    if not isinstance(new, (ast.FunctionDef, ast.AsyncFunctionDef)) or new.name != n.name:
        return "", "different name"
    a, b = n.args, new.args
    shape = lambda x: ([p.arg for p in x.posonlyargs], [p.arg for p in x.args],  # noqa: E731
                       x.vararg and x.vararg.arg, [p.arg for p in x.kwonlyargs], x.kwarg and x.kwarg.arg,
                       [_norm(d) for d in x.defaults], [_norm(d) for d in x.kw_defaults])
    if shape(a) != shape(b):
        return "", "changed parameters"
    for old_p, new_p in zip(_params(n), _params(new)):
        if old_p.annotation is not None and _norm(old_p.annotation) != _norm(new_p.annotation):
            return "", "changed an existing hint"
    if n.returns is not None and _norm(n.returns) != _norm(new.returns):
        return "", "changed the return hint"
    allowed = known | set(dir(builtins))
    unknown = set().union(*(_names_in(p.annotation) for p in _params(new)), _names_in(new.returns)) - allowed
    if unknown:
        return "", f"unknown name {sorted(unknown)[0]}"
    if all(_norm(p.annotation) == _norm(q.annotation) for p, q in zip(_params(n), _params(new))) \
            and _norm(n.returns) == _norm(new.returns):
        return "", "no new hints"
    return text, ""


def _split_params(text: str) -> tuple[str, list[str], str] | None:
    """'def f(a, b) -> T:' -> ('def f(', ['a', 'b'], ') -> T:')."""
    depth, open_i, cuts = 0, -1, []
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError):
        return None
    for t in toks:
        if t.type != tokenize.OP:
            continue
        if t.string in "([{":
            depth += 1
            if depth == 1 and open_i < 0 and t.string == "(":
                open_i = t.start[1]
        elif t.string in ")]}":
            depth -= 1
            if depth == 0 and open_i >= 0:
                parts, prev = [], open_i + 1
                for c in cuts + [t.start[1]]:
                    parts.append(text[prev:c].strip())
                    prev = c + 1
                return text[:open_i + 1], [p for p in parts if p], text[t.start[1]:]
        elif t.string == "," and depth == 1:
            cuts.append(t.start[1])
    return None


def format_header(text: str, indent: str) -> list[str]:
    if len(indent) + len(text) <= WRAP_AT:
        return [indent + text]
    sp = _split_params(text)
    if not sp or not sp[1]:
        return [indent + text]
    head, params, tail = sp
    return [indent + head] + [f"{indent}    {p}," for p in params] + [indent + tail]


def render_doc(doc: str, indent: str) -> list[str]:
    d = doc.strip().strip('"').strip("'").strip().replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    rows = d.splitlines()[:12] or ["TODO."]
    first, rest = rows[0].strip(), textwrap.dedent("\n".join(rows[1:])).splitlines()
    if not rest:
        if first.endswith('"'):
            first += " "
        return [f'{indent}"""{first}"""']
    return [f'{indent}"""{first}'] + [indent + r if r.strip() else "" for r in rest] + [f'{indent}"""']


def apply(src: str, fns: list[Fn], docs: list[Doc], known: set[str]) -> tuple[str, dict]:
    lines = src.splitlines(keepends=True)
    nl = "\r\n" if "\r\n" in src else "\n"
    by_name = {}
    for d in docs:
        by_name.setdefault(d.name.strip().lstrip("# ").strip(), d)
    edits: list[tuple[int, int, list[str]]] = []  # (start, end) 0-based half-open, new lines
    report = {"docs": [], "hints": [], "skipped": []}
    for f in fns:
        d = by_name.get(f.qual) or by_name.get(f.node.name)
        if d is None:
            report["skipped"].append(f"{f.qual} (no reply)")
            continue
        he = header_end(lines, f.node)
        if he is None:
            report["skipped"].append(f"{f.qual} (header)")
            continue
        row, ccol = he
        n = f.node
        if f.need_hints:
            text, why = check_signature(n, d.signature_with_hints, known)
            if text:
                first = lines[n.lineno - 1]
                indent = first[:n.col_offset]
                suffix = lines[row - 1].rstrip("\r\n")[ccol + 1:]
                new = format_header(text, indent)
                new[-1] += suffix
                edits.append((n.lineno - 1, row, [x + nl for x in new]))
                report["hints"].append(f.qual)
            elif why != "no new hints":
                report["skipped"].append(f"{f.qual} hints ({why})")
        if f.need_doc and d.docstring.strip():
            b0 = n.body[0]
            b_line = min([b0.lineno] + [x.lineno for x in getattr(b0, "decorator_list", [])])
            body_txt = lines[b_line - 1]
            indent = body_txt[:len(body_txt) - len(body_txt.lstrip())]
            edits.append((row, row, [x + nl for x in render_doc(d.docstring, indent)]))
            report["docs"].append(f.qual)
    for start, end, new in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        lines[start:end] = new
    return "".join(lines), report


def summarize(old: str, new: str, report: dict, name: str) -> tuple[str, str]:
    """(one-line summary, compact diff preview)."""
    diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0))
    plus = sum(1 for x in diff if x.startswith("+") and not x.startswith("+++"))
    minus = sum(1 for x in diff if x.startswith("-") and not x.startswith("---"))
    names = lambda xs: ", ".join(xs[:6]) + (f" +{len(xs) - 6}" if len(xs) > 6 else "")  # noqa: E731
    parts = []
    if report["docs"]:
        parts.append(f"{len(report['docs'])} docstrings ({names(report['docs'])})")
    if report["hints"]:
        parts.append(f"{len(report['hints'])} signatures with hints ({names(report['hints'])})")
    line = f"{name}: " + ("; ".join(parts) or "no usable changes") + f", +{plus}/-{minus} lines"
    if report["skipped"]:
        line += f"; skipped {names(report['skipped'])}"
    preview = "\n".join(x for x in diff[2:] if not x.startswith("@@"))
    return line, _proc.clip(preview, 900)


# --- background proposal cache ---
def _cache_path(src: str) -> Path:
    return config.OUTPUTS_DIR / "docstrings" / (hashlib.sha1(src.encode()).hexdigest()[:16] + ".json")


def load_cache(src: str, only: str) -> list[Doc] | None:
    p = _cache_path(src)
    try:
        data = json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("only", "") != only:
        return None
    return [Doc(**d) for d in data.get("items", [])]


def _background(p: Path, src: str, fns: list[Fn], known: set[str], only: str) -> str:
    from jarvis.core import jobs

    def job(ctx) -> str:
        docs, failed = generate(fns, known, ctx.job.cancel_event, ctx.progress)
        cp = _cache_path(src)
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps({"path": str(p), "only": only, "items": [d.model_dump() for d in docs]}),
                      encoding="utf-8")
        new, report = apply(src, fns, docs, known)
        line, _ = summarize(src, new, report, p.name)
        out = config.OUTPUTS_DIR / f"docstrings-{p.stem}-{datetime.now():%Y%m%d-%H%M%S}.md"
        diff = "\n".join(difflib.unified_diff(src.splitlines(), new.splitlines(), str(p), str(p), lineterm=""))
        out.write_text(f"# Docstring proposal for {p}\n\n{line}{f' ({failed} batches failed)' if failed else ''}"
                       f"\n\nSay 'add docstrings to {p.name}' again to review and apply it (no new tokens).\n\n"
                       f"```diff\n{diff}\n```\n", encoding="utf-8")
        return str(out)

    j = jobs.get_manager().submit(f"docstrings {p.name}", "docstrings", job, str(p))
    return (f"started job #{j.id}: drafting docstrings/hints for {len(fns)} functions in {p.name}. "
            f"When it's done, ask again to review the diff and apply it (no new tokens).")


def _resolve(path: str) -> Path:
    p = Path(path).expanduser()
    if p.is_absolute():
        return p.resolve()
    return (Path.cwd() / p).resolve() if (Path.cwd() / p).exists() else _files.resolve(path)


@tool(group="devutils", safety="confirm", max_chars=1400,
      description="Add missing docstrings and type hints to a Python file's functions (diff first, .bak kept).")
def add_docstrings(path: str, name: str = "", dry_run: bool = False) -> str:
    """Generate docstrings / type hints for functions that lack them.

    Args:
        path: The .py file.
        name: Only this function, method (Class.method) or class's methods (optional).
        dry_run: Only show the proposed changes; never write.
    """
    from jarvis.core import store

    p = _resolve(path)
    if not p.is_file() or p.suffix != ".py":
        return f"not a Python file: {p}"
    src = p.read_text("utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return f"{p.name} has a syntax error at line {e.lineno}; fix it first"
    lines = src.splitlines(keepends=True)
    only = (name or "").strip()
    fns = find(tree, lines, only)
    if not fns:
        what = f"'{only}'" if only else "every function"
        return f"nothing to do: {what} in {p.name} already has docstrings and type hints (or wasn't found)"
    known = known_names(tree)
    docs = load_cache(src, only)
    tokens, failed, cached = 0, 0, docs is not None
    if docs is None:
        if len(fns) > BG_FUNCS:
            return _background(p, src, fns, known, only)
        before = store.tokens_for_purpose("add_docstrings")
        docs, failed = generate(fns, known)
        tokens = store.tokens_for_purpose("add_docstrings") - before
    new, report = apply(src, fns, docs, known)
    cost = "cached proposal, 0 tokens" if cached else f"~{tokens} tokens"
    if failed:
        cost += f", {failed} batches failed"
    if new == src:
        return f"no usable changes for {p.name} ({cost})"
    try:
        ast.parse(new)
    except SyntaxError as e:
        return f"the edit would break {p.name} (line {e.lineno}); nothing written ({cost})"
    line, preview = summarize(src, new, report, p.name)
    if dry_run:
        return f"{line} ({cost}). Dry run, nothing written.\n{preview}"
    where = "" if _files.in_safe_roots(p) else " It's outside your project folders."
    if not safety.ask(f"Apply to {line}? A .bak copy is kept.{where}"):
        return f"Not written. Proposed: {line} ({cost})."
    shutil.copy2(p, p.with_name(p.name + ".bak"))
    p.write_text(new, encoding="utf-8")
    _cache_path(src).unlink(missing_ok=True)
    return f"updated {line} ({cost}); backup at {p.name}.bak"
