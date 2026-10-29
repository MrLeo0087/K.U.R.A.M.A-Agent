"""dependency_doctor: check a Python project's declared dependencies (safe). Parses requirements*.txt and
pyproject.toml, then reports unpinned and duplicate entries, deps missing from the venv, deps never
imported (ast scan), outdated ones (pip list --outdated), known vulnerabilities when pip-audit is
installed (optional), and torch/GPU baggage. Report stays under ~800 chars."""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import tomllib
from pathlib import Path

from jarvis.core.registry import tool
from jarvis.tools.interactive import _proc
from jarvis.tools.interactive.run_tests import find_python

NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)$")
# Dev tools / servers / build backends: declared on purpose, rarely imported.
NOT_IMPORTED_OK = {"pytest", "ruff", "black", "mypy", "flake8", "isort", "pre-commit", "pip-audit", "coverage",
                   "pytest-cov", "pytest-asyncio", "setuptools", "wheel", "pip", "build", "twine", "uvicorn",
                   "gunicorn", "hatchling", "poetry-core", "tox", "nox", "ipykernel", "jupyter", "python"}
HEAVY = re.compile(r"^(?:torch|torchvision|torchaudio|tensorflow(?:-.*)?|tf-nightly|keras|jax|jaxlib|nvidia-.*|"
                   r"triton|cupy(?:-.*)?|onnxruntime-gpu|tensorrt.*|xformers|bitsandbytes)$")
# One subprocess in the project's interpreter: installed dists + import-name -> dist map.
PROBE = ("import json,importlib.metadata as m\n"
         "d={x.metadata['Name']:x.version for x in m.distributions() if x.metadata['Name']}\n"
         "print(json.dumps({'installed':d,'pkgmap':m.packages_distributions()}))")


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirement(line: str) -> tuple[str, str] | None:
    """(name, spec) from one requirements line; None for comments, options, urls and blanks."""
    line = line.split(" #", 1)[0].split("\t#", 1)[0].strip()
    if not line or line.startswith(("#", "-", "git+", "http:", "https:", "file:", ".", "/")):
        return None
    line = line.split(";", 1)[0].strip()  # environment markers
    m = NAME_RE.match(line)
    return (m.group(1), m.group(3).strip()) if m else None


def is_pinned(spec: str) -> bool:
    return "==" in spec or "@" in spec


def collect(root: Path) -> tuple[list[tuple[str, str, str]], list[str]]:
    """([(name, spec, source_file)], files read)."""
    deps: list[tuple[str, str, str]] = []
    files: list[str] = []
    for p in sorted(root.glob("requirements*.txt")) + sorted((root / "requirements").glob("*.txt")):
        files.append(str(p.relative_to(root)))
        for ln in p.read_text("utf-8", "replace").splitlines():
            r = parse_requirement(ln)
            if r:
                deps.append((r[0], r[1], files[-1]))
    pp = root / "pyproject.toml"
    if pp.exists():
        try:
            data = tomllib.loads(pp.read_text("utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            data = {}
        if data:
            files.append("pyproject.toml")
        proj = data.get("project", {})
        lines = list(proj.get("dependencies", []))
        for extra in proj.get("optional-dependencies", {}).values():
            lines += list(extra)
        for ln in lines:
            r = parse_requirement(ln)
            if r:
                deps.append((r[0], r[1], "pyproject.toml"))
        poetry = data.get("tool", {}).get("poetry", {})
        for sect in (poetry.get("dependencies", {}), *[g.get("dependencies", {}) for g in
                                                        poetry.get("group", {}).values()]):
            for name, spec in sect.items():
                if name.lower() != "python":
                    v = spec if isinstance(spec, str) else (spec.get("version", "") if isinstance(spec, dict) else "")
                    deps.append((name, "==" + v if re.match(r"^\d", v or "") else v, "pyproject.toml"))
    return deps, files


def imported_modules(root: Path, limit: int = 3000) -> set[str]:
    mods: set[str] = set()
    n = 0
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if x not in _proc.EXCLUDES and not x.startswith(".")]
        for name in names:
            if not name.endswith(".py"):
                continue
            n += 1
            if n > limit:
                return mods
            try:
                tree = ast.parse(Path(d, name).read_text("utf-8", "replace"))
            except (SyntaxError, ValueError, OSError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    mods.add(node.module.split(".")[0])
    return mods


def probe_env(py: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    cp = _proc.run([py, "-c", PROBE], timeout=30)
    if cp.returncode != 0:
        raise _proc.ProcError(f"could not inspect the environment: {cp.stderr.strip()[-160:]}")
    data = json.loads(cp.stdout)
    return {norm(k): v for k, v in data["installed"].items()}, data["pkgmap"]


def outdated(py: str, timeout: float = 25) -> dict[str, tuple[str, str]] | str:
    try:
        cp = _proc.run([py, "-m", "pip", "list", "--outdated", "--format=json", "--disable-pip-version-check",
                        "--no-input"], timeout=timeout)
    except _proc.ProcError as e:
        return f"skipped ({e})"
    if cp.returncode != 0:
        return "skipped (pip failed; offline?)"
    try:
        return {norm(x["name"]): (x["version"], x["latest_version"]) for x in json.loads(cp.stdout or "[]")}
    except (ValueError, KeyError):
        return "skipped (unreadable pip output)"


def audit(root: Path, py: str, req_files: list[str]) -> list[str] | str:
    """Known vulnerabilities via pip-audit if it is installed (never required)."""
    exe = Path(py).with_name("pip-audit")
    exe = str(exe) if exe.exists() else shutil.which("pip-audit")
    if not exe:
        return "pip-audit not installed (skipped)"
    reqs = [f for f in req_files if f.endswith(".txt")]
    args = [exe, "--format", "json", "--progress-spinner", "off"] + [a for f in reqs[:3] for a in ("-r", f)]
    try:
        cp = _proc.run(args, cwd=root, timeout=90)
        data = json.loads(cp.stdout or "{}")
    except (_proc.ProcError, ValueError) as e:
        return f"pip-audit failed ({str(e)[:60]})"
    items = data.get("dependencies", data) if isinstance(data, dict) else data
    return [f"{d['name']} {d.get('version', '')} ({', '.join(v['id'] for v in d['vulns'][:2])})"
            for d in items if isinstance(d, dict) and d.get("vulns")]


def _short(items: list[str], n: int = 5) -> str:
    return ", ".join(items[:n]) + (f" +{len(items) - n}" if len(items) > n else "")


@tool(group="codequality", safety="safe",
      description="Check a Python project's dependencies: unpinned, duplicate, missing, unused, outdated, vulnerable, torch/GPU baggage.")
def dependency_doctor(repo: str = ".", check_outdated: bool = True) -> str:
    """Diagnose the project's declared Python dependencies.

    Args:
        repo: Project folder (default: current folder).
        check_outdated: Ask pip which packages are outdated (needs network, ~25 s max).
    """
    root = _proc.resolve_dir(repo)
    deps, files = collect(root)
    if not files:
        return f"dependency_doctor {root.name}: no requirements*.txt or pyproject.toml found"
    py, _ = find_python(root)
    installed, pkgmap = probe_env(py)
    names = [norm(n) for n, _s, _f in deps]
    seen: dict[str, set[str]] = {}
    for (n, s, _f), key in zip(deps, names):
        seen.setdefault(key, set()).add(s or "*")
    dupes = [k for k in dict.fromkeys(names) if names.count(k) > 1]
    conflicts = [k for k in dupes if len(seen[k]) > 1]
    unpinned = [n for n, s, _f in deps if not is_pinned(s)]
    missing = [k for k in dict.fromkeys(names) if k not in installed]
    used_dists = {norm(d) for m in imported_modules(root) for d in pkgmap.get(m, [m])}
    unused = [k for k in dict.fromkeys(names)
              if k in installed and k not in used_dists and k not in NOT_IMPORTED_OK]
    heavy = sorted(k for k in installed if HEAVY.match(k))
    lines = [f"dependency_doctor {root.name}: {len(set(names))} deps in {', '.join(files)} ({os.path.relpath(py, root)})"]
    if unpinned:
        lines.append(f"unpinned: {_short(unpinned)}")
    if dupes:
        lines.append(f"duplicates: {_short(dupes)}" + (f" (conflicting specs: {_short(conflicts, 3)})" if conflicts else ""))
    if missing:
        lines.append(f"missing from venv: {_short(missing)}")
    if unused:
        lines.append(f"never imported (maybe transitive/CLI): {_short(unused, 6)}")
    if check_outdated:
        od = outdated(py)
        if isinstance(od, str):
            lines.append(f"outdated: {od}")
        else:
            mine = [f"{k} {od[k][0]}->{od[k][1]}" for k in dict.fromkeys(names) if k in od]
            lines.append(f"outdated: {_short(mine, 4)}" if mine else "outdated: none")
    vul = audit(root, py, files)
    lines.append(f"vulnerable: {_short(vul, 3) if vul else 'none known'}" if isinstance(vul, list) else f"vulns: {vul}")
    if heavy:
        declared = [h for h in heavy if h in names]
        lines.append(f"torch/GPU baggage installed: {_short(heavy, 4)}" + (" (declared!)" if declared else " (transitive)"))
    else:
        lines.append("torch/GPU baggage: none")
    if not (unpinned or dupes or missing or unused):
        lines.insert(1, "all deps pinned, installed and imported")
    return _proc.clip("\n".join(lines))
