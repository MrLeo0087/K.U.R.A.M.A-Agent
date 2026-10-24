"""precommit_gate: quick checks on staged files before a commit (safe): Python syntax, ruff (or a small
ast fallback), secrets in the staged diff, files over 5 MB, merge-conflict markers, breakpoints and
debug prints. install_hook=True asks first, then writes .git/hooks/pre-commit that runs
`python -m jarvis.tools.interactive.precommit_gate`; an existing hook is never replaced without a yes.

No longer a tool of its own: the merged tool calls precommit_gate() (old name kept as an alias)."""
from __future__ import annotations

import ast
import re
import shutil
import sys
from pathlib import Path

from jarvis.core.registry import tool
from jarvis.tools.interactive import _proc, _secrets

MAX_BYTES = 5 * 1024 * 1024
HOOK_MARK = "# installed by KURAMA precommit_gate"
BREAKPOINT = re.compile(r"\bbreakpoint\(\)|\b(?:i?pdb|pudb)\.set_trace\(|^\s*import\s+i?pdb\b|^\s*debugger\s*;?\s*$")
# Without a project ruff config: only real errors (syntax, undefined names, unused imports/variables).
RUFF_DEFAULT_RULES = "E9,F63,F7,F82,F401,F811,F841"
DEBUG_PRINT = re.compile(r"^\s*(?:print\(|console\.log\()")


def has_ruff_config(root: Path) -> bool:
    if (root / "ruff.toml").exists() or (root / ".ruff.toml").exists():
        return True
    pp = root / "pyproject.toml"
    return pp.exists() and "[tool.ruff" in pp.read_text("utf-8", "replace")


def find_ruff() -> str | None:
    own = Path(sys.executable).with_name("ruff")
    return str(own) if own.exists() else shutil.which("ruff")


def ast_lint(src: str, path: str) -> list[str]:
    """pyflakes-lite: unused imports and functions/classes defined twice at module level."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    out: list[str] = []
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.value.id for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
    exported = re.findall(r"['\"](\w+)['\"]", src.split("__all__", 1)[1][:2000]) if "__all__" in src else []
    if not path.endswith("__init__.py"):
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)) and not (
                    isinstance(node, ast.ImportFrom) and node.module == "__future__"):
                for a in node.names:
                    name = (a.asname or a.name).split(".")[0]
                    if name != "*" and name not in used and name not in exported:
                        out.append(f"{path}:{node.lineno} unused import {name}")
    seen: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in seen and not node.decorator_list:
                out.append(f"{path}:{node.lineno} {node.name} redefined (first at line {seen[node.name]})")
            seen[node.name] = node.lineno
    return out


def staged(root: Path) -> list[str]:
    out = _proc.git(["diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"], root)
    return [f for f in out.split("\0") if f]


def run_checks(root: Path) -> dict:
    files = staged(root)
    res: dict = {"files": files, "fail": {}, "warn": {}}
    if not files:
        return res
    fail, warn = res["fail"], res["warn"]

    def add(bucket: dict, key: str, item: str) -> None:
        bucket.setdefault(key, []).append(item)

    py = []
    for f in files:
        p = root / f
        try:
            size = int(_proc.git(["cat-file", "-s", f":{f}"], root).strip() or 0)
        except (_proc.ProcError, ValueError):
            size = p.stat().st_size if p.exists() else 0
        if size > MAX_BYTES:
            add(fail, "large files", f"{f} ({size / 1048576:.1f} MB)")
            continue
        if f.endswith(".py") and p.exists():
            py.append(f)
            src = p.read_text("utf-8", "replace")
            try:
                compile(src, f, "exec", dont_inherit=True)
            except SyntaxError as e:
                add(fail, "syntax", f"{f}:{e.lineno} {e.msg}")
    ruff = find_ruff()
    if py and ruff:
        rules = [] if has_ruff_config(root) else ["--isolated", "--select", RUFF_DEFAULT_RULES]
        cp = _proc.run([ruff, "check", "--quiet", "--no-cache", "--output-format=concise", *rules, *py],
                       cwd=root, timeout=60)
        for ln in cp.stdout.splitlines():
            if re.match(r"^\S+:\d+:\d+: ", ln):
                add(fail, "ruff", ln.strip())
    elif py:
        for f in py:
            for item in ast_lint((root / f).read_text("utf-8", "replace"), f):
                add(fail, "lint", item)
    diff = _proc.git(["diff", "--cached", "--unified=0", "--no-color", "--no-ext-diff"], root, timeout=30)
    for f in _secrets.scan_diff(diff, limit=50):
        add(fail, "secrets", f"{f.path}:{f.line} {f.kind} {f.preview}")
    for _sha, path, ln, text in _secrets.added_lines(diff):
        if _secrets.CONFLICT.match(text):
            add(fail, "conflict markers", f"{path}:{ln}")
        elif BREAKPOINT.search(text):
            add(fail, "breakpoints", f"{path}:{ln}")
        elif DEBUG_PRINT.match(text) and not path.startswith(("tests/", "scripts/")) and "__main__" not in path:
            add(warn, "debug prints", f"{path}:{ln}")
    return res


def summary(res: dict, root: Path) -> str:
    files, fail, warn = res["files"], res["fail"], res["warn"]
    if not files:
        return f"pre-commit gate {root.name}: nothing staged"
    nfail = sum(len(v) for v in fail.values())
    head = (f"pre-commit gate {root.name}: {'FAIL' if fail else 'PASS'} "
            f"({nfail} problem(s), {sum(len(v) for v in warn.values())} warning(s) in {len(files)} staged file(s))")
    lines = [head]
    for label, bucket in (("x", fail), ("!", warn)):
        for key, items in bucket.items():
            more = f" (+{len(items) - 3} more)" if len(items) > 3 else ""
            lines.append(f"{label} {key}: {'; '.join(items[:3])}{more}")
    return _proc.clip("\n".join(lines))


def hook_script() -> str:
    jarvis_root = Path(__file__).resolve().parents[3]
    return ("#!/bin/sh\n" f"{HOOK_MARK}\n"
            f'PYTHONPATH="{jarvis_root}${{PYTHONPATH:+:$PYTHONPATH}}" '
            f'exec "{sys.executable}" -m jarvis.tools.interactive.precommit_gate "$@"\n')


def install(root: Path) -> str:
    from jarvis.core import safety

    hooks = Path(_proc.git(["rev-parse", "--git-path", "hooks"], root).strip())
    hook = (hooks if hooks.is_absolute() else root / hooks) / "pre-commit"
    if hook.exists():
        mine = HOOK_MARK in hook.read_text("utf-8", "replace")
        if mine:
            return f"pre-commit hook already installed at {hook}"
        if not safety.ask(f"A pre-commit hook already exists in {root.name}. Replace it (a .bak copy is kept)?"):
            return "kept the existing pre-commit hook (not replaced)"
        hook.with_suffix(".bak").write_text(hook.read_text("utf-8", "replace"), encoding="utf-8")
    elif not safety.ask(f"Install a pre-commit hook in {root.name} that runs KURAMA's checks before each commit?"):
        return "pre-commit hook not installed"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(hook_script(), encoding="utf-8")
    hook.chmod(0o755)
    return f"installed pre-commit hook at {hook}"


def precommit_gate(repo: str = ".", install_hook: bool = False) -> str:
    """Run quick checks on the staged files.

    Args:
        repo: Repository folder (default: current folder).
        install_hook: Also install a git pre-commit hook that runs these checks (asks first).
    """
    root = _proc.repo_root(repo)
    out = summary(run_checks(root), root)
    if install_hook:
        out += "\n" + install(root)
    return out


def main() -> int:
    root = _proc.repo_root(".")
    res = run_checks(root)
    print(summary(res, root))
    if res["fail"]:
        print("commit blocked: fix the problems above or use `git commit --no-verify` to skip")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
