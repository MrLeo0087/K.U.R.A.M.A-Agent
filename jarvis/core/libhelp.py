"""Library help for the highlighted code: what a function takes, and whether YOUR call is right.

0 tokens for Python: the real signature + docstring come from the project's own Python (inspect), the highlighted
call is checked with signature.bind() (wrong / misspelled / missing arguments), and each argument you used gets its
line from the docstring. A project function is read from its source (ast, nothing imported). One small LLM call only
when you ask for a suggestion / example, or when the code isn't Python or the object can't be resolved
(df.groupby on a variable).
"""
from __future__ import annotations

import ast
import difflib
import json
import logging
import re
import subprocess
import textwrap
from pathlib import Path

from jarvis.core import codenav

log = logging.getLogger(__name__)

SUGGEST = re.compile(r"\b(?:suggest\w*|better|improve|example|examples|how\s+(?:should|do|can)\s+i|best\s+way|"
                     r"alternative|recommend\w*|fix|correct\s+it|rewrite)\b", re.I)

_INSPECT = r"""
import importlib, inspect, json, sys
mod, attr, npos, kws = sys.argv[1], sys.argv[2], int(sys.argv[3]), json.loads(sys.argv[4])
out = {}
try:
    obj = importlib.import_module(mod)
    for part in [p for p in attr.split('.') if p]:
        obj = getattr(obj, part)
    out['qual'] = (getattr(obj, '__module__', None) or mod) + '.' + getattr(obj, '__qualname__', attr or mod)
    target = obj.__init__ if inspect.isclass(obj) else obj
    try:
        sig = inspect.signature(obj)
        ps = []
        for p in sig.parameters.values():
            d = '' if p.default is p.empty else repr(p.default)[:40]
            ps.append({'name': p.name, 'kind': p.kind.name, 'default': d,
                       'required': p.default is p.empty and p.kind.name in ('POSITIONAL_ONLY', 'POSITIONAL_OR_KEYWORD', 'KEYWORD_ONLY')})
        out['params'] = ps
        if npos >= 0:
            try:
                sig.bind(*([None] * npos), **{k: None for k in kws})
                out['bind'] = 'ok'
            except TypeError as e:
                out['bind'] = str(e)
    except (TypeError, ValueError):
        out['params'] = None
    out['doc'] = (inspect.getdoc(obj) or inspect.getdoc(target) or '')[:6000]
except Exception as e:
    out = {'error': type(e).__name__ + ': ' + str(e)[:150]}
print(json.dumps(out))
"""


def parse_call(selection: str) -> tuple[str, int, list[str]] | None:
    """'pd.read_csv("a.csv", sep=";")' -> ('pd.read_csv', 1, ['sep']); None when it isn't one call."""
    text = (selection or "").strip().rstrip(":;")
    for src in (text, re.sub(r"^\s*[\w.\[\]'\" ,]+\s*=\s*", "", text, count=1)):
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                try:
                    name = ast.unparse(node.func)
                except Exception:
                    continue
                if any(isinstance(a, ast.Starred) for a in node.args) or any(k.arg is None for k in node.keywords):
                    return name, -1, []  # *args / **kwargs: can't check the count
                return name, len(node.args), [k.arg for k in node.keywords]
    return None


def param_docs(doc: str) -> dict[str, str]:
    """One line per argument from numpy / Google / Sphinx docstrings."""
    out: dict[str, str] = {}
    lines = doc.splitlines()
    for i, ln in enumerate(lines):
        if m := re.match(r"^\s*:param\s+(?:[\w\[\], ]+\s+)?(\w+):\s*(.+)", ln):  # Sphinx
            out.setdefault(m.group(1), m.group(2).strip())
        elif m := re.match(r"^(\w+)(?:\s*,\s*\w+)*\s*:\s*(.*)$", ln):  # numpy: 'sep : str, default ','
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if nxt and i + 1 < len(lines) and lines[i + 1].startswith((" ", "\t")):
                out.setdefault(m.group(1), (m.group(2).strip() + " — " if m.group(2).strip() else "") + nxt)
        elif m := re.match(r"^\s{2,}(\w+)\s*(?:\([^)]*\))?:\s+(.+)", ln):  # Google: '    sep (str): The separator.'
            out.setdefault(m.group(1), m.group(2).strip())
    return {k: v[:160] for k, v in out.items()}


def _summary(doc: str) -> str:
    para = doc.strip().split("\n\n")[0] if doc else ""
    return " ".join(para.split())[:240]


def _project_info(name: str, root: Path | None, here: Path | None) -> dict | None:
    """Signature/doc of a function defined in the project, read from its source (nothing is run)."""
    r = codenav.find(name, root, here)
    if "error" in r or r.get("where") != "project" or r["file"].suffix != ".py":
        return None
    try:
        node = ast.parse(textwrap.dedent(r["code"])).body[0]  # a method is indented inside its class
    except (SyntaxError, IndexError, ValueError):
        return None
    if isinstance(node, ast.ClassDef):
        node = next((n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"), None)
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    a = node.args
    pos = a.posonlyargs + a.args
    defaults = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
    ps = [{"name": p.arg, "kind": "POSITIONAL_OR_KEYWORD", "default": ast.unparse(d) if d is not None else "",
           "required": d is None} for p, d in zip(pos, defaults) if p.arg not in ("self", "cls")]
    if a.vararg:
        ps.append({"name": a.vararg.arg, "kind": "VAR_POSITIONAL", "default": "", "required": False})
    for p, d in zip(a.kwonlyargs, a.kw_defaults):
        ps.append({"name": p.arg, "kind": "KEYWORD_ONLY", "default": ast.unparse(d) if d is not None else "",
                   "required": d is None})
    if a.kwarg:
        ps.append({"name": a.kwarg.arg, "kind": "VAR_KEYWORD", "default": "", "required": False})
    return {"qual": f"{codenav._rel(r['file'], root)}:{r['line']} {node.name}", "params": ps,
            "doc": ast.get_docstring(node) or "", "project": True}


def _check(params: list[dict], npos: int, kws: list[str]) -> str:
    """signature.bind() for a project function, without running anything."""
    names = {p["name"] for p in params}
    if any(p["kind"] == "VAR_KEYWORD" for p in params):
        bad = []
    else:
        bad = [k for k in kws if k not in names]
    if bad:
        return f"got an unexpected keyword argument '{bad[0]}'"
    positional = [p for p in params if p["kind"] in ("POSITIONAL_ONLY", "POSITIONAL_OR_KEYWORD")]
    if npos > len(positional) and not any(p["kind"] == "VAR_POSITIONAL" for p in params):
        return f"takes {len(positional)} positional arguments but {npos} were given"
    filled = {p["name"] for p in positional[:max(npos, 0)]} | set(kws)
    missing = [p["name"] for p in params if p["required"] and p["name"] not in filled]
    return f"missing a required argument: '{missing[0]}'" if missing and npos >= 0 else "ok"


def info(selection: str, root: Path | None, here: Path | None) -> dict:
    """{qual, params, doc, bind, call, name} or {error}."""
    call = parse_call(selection)
    name = call[0] if call else codenav.name_from(selection)
    if not name:
        return {"error": "Highlight the function or call you want help with, then ask again."}
    name = re.sub(r"^(?:self|cls)\.", "", name)
    npos, kws = (call[1], call[2]) if call else (-1, [])
    src = here.read_text(errors="replace") if here and here.suffix == ".py" and here.is_file() else ""
    module, attr = codenav._imported_from(name, src) if src else ("", "")
    if not module and "." in name:
        module, attr = name.split(".", 1)
    top = module.split(".")[0]
    local = bool(root and ((root / top).is_dir() or (root / f"{top}.py").is_file()))
    if (not module or local) and (pi := _project_info(name.rsplit(".", 1)[-1], root, here)):
        pi.update(name=name, call=bool(call), bind=_check(pi["params"], npos, kws) if call else "")
        return pi
    if not module:
        import builtins
        if hasattr(builtins, name):  # print(), open(), sorted()...
            module, attr = "builtins", name
        else:
            return {"error": "unresolved", "name": name}
    try:
        r = subprocess.run([codenav._python_for(root), "-I", "-c", _INSPECT, module, attr, str(npos if call else -1),
                            json.dumps(kws)], capture_output=True, text=True, timeout=20, cwd=str(root) if root else None)
        out = json.loads(r.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError) as e:
        return {"error": f"couldn't read it ({str(e)[:80]})", "name": name}
    if "error" in out:
        return {"error": "unresolved", "name": name, "why": out["error"]}
    out.update(name=name, call=bool(call), bind=out.get("bind", ""))
    return out


def _fmt_param(p: dict) -> str:
    star = {"VAR_POSITIONAL": "*", "VAR_KEYWORD": "**"}.get(p["kind"], "")
    return f"{star}{p['name']}" + (f"={p['default']}" if p["default"] else "")


def render(i: dict, kws: list[str]) -> str:
    params = i.get("params") or []
    doc = i.get("doc", "")
    pdocs = param_docs(doc)
    head = f"**{i['qual']}**" + (f": {_summary(doc)}" if _summary(doc) else "")
    lines = [head]
    if i.get("call"):
        b = i.get("bind", "")
        named = {p["name"] for p in params if p["kind"] not in ("VAR_POSITIONAL", "VAR_KEYWORD")}
        loose = [k for k in kws if k not in named] if any(p["kind"] == "VAR_KEYWORD" for p in params) else []
        if b == "ok" and loose:  # **kwargs swallows typos: 'indnt=2' is accepted but does nothing useful
            for k in loose:
                close = difflib.get_close_matches(k, list(named), n=1, cutoff=0.6)
                lines.append(f"⚠️ `{k}` isn't one of its named arguments (it goes into **{next(p['name'] for p in params if p['kind'] == 'VAR_KEYWORD')})"
                             + (f". Did you mean `{close[0]}`?" if close else ". Check the spelling."))
        elif b == "ok":
            lines.append("✅ Your call looks right: the arguments match.")
        elif b:
            msg = "❌ " + b[0].upper() + b[1:] + "."
            if m := re.search(r"unexpected keyword argument '(\w+)'", b):
                close = difflib.get_close_matches(m.group(1), [p["name"] for p in params], n=1, cutoff=0.6)
                if close:
                    msg += f" Did you mean `{close[0]}`?"
            lines.append(msg)
    req = [p["name"] for p in params if p["required"]]
    if params:
        lines.append(f"Takes ({', '.join(_fmt_param(p) for p in params[:12])}{', ...' if len(params) > 12 else ''})"
                     + (f". Required: {', '.join(req)}" if req else ". Nothing is required") + ".")
    used = [k for k in kws if k in pdocs] or ([k for k in req if k in pdocs][:3] if not kws else [])
    for k in used[:6]:
        lines.append(f"- `{k}`: {pdocs[k]}")
    return "\n".join(lines)


def _llm_help(selection: str, request: str, i: dict | None, here: Path | None) -> str:
    from jarvis.core import assist
    ctx = ""
    if i and "qual" in i:
        ctx = (f"Real signature of {i['qual']}: ({', '.join(_fmt_param(p) for p in (i.get('params') or [])[:30])})\n"
               f"Docs (start): {i.get('doc', '')[:1500]}\n")
    lang = assist._EXT_LANG.get(here.suffix.lower(), "") if here else ""
    return assist._llm(
        "You help a programmer with a library call they highlighted. Answer in at most 5 short lines: say if the "
        "call is correct, the arguments that matter, and one corrected or better example line in a code block. "
        "Use only real arguments (the signature given is the truth).",
        f"{ctx}Language: {lang or 'unknown'}\nHighlighted code:\n{selection[:1500]}\nRequest: {request or 'help with this'}",
        smart=False, max_tokens=400, purpose="libhelp")


def help_for(selection: str, request: str, root: Path | None, here: Path | None) -> str:
    """The answer for 'help me with this library / what arguments does it take / is this syntax right'."""
    if not (selection or "").strip():
        return "Highlight the function or the line you want help with, then ask again."
    is_py = (here is None or here.suffix == ".py")
    i = info(selection, root, here) if is_py else None
    call = parse_call(selection) if is_py else None
    if i and "error" not in i:
        text = render(i, call[2] if call else [])
        if request and SUGGEST.search(request):
            text += "\n\n" + _llm_help(selection, request, i, here)
        return text
    if i and i.get("error") not in ("unresolved", None) and "Highlight" in i["error"]:
        return i["error"]
    return _llm_help(selection, request, None, here)  # not Python, or a method on a variable (df.groupby)
