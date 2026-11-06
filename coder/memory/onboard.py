"""Learning a project KURAMA didn't build, once, within the token budget:

  1. facts without the AI (0 tokens): the folder tree in numbers, the manifests (package.json scripts and
     dependencies, requirements.txt, pyproject.toml, Makefile targets), the README's start, the likely entry points,
     the last commits, and the project map (every file's functions / classes / exports: repomap)
  2. ONE call to the fast model reads those facts (~5k tokens, never the code itself) and writes the overview:
     what the project does, how its parts connect, how to run it, its conventions, the key files
  3. the project card .kurama/project.md is written; from then on every request reads the card + a fresh map
     (0 tokens) and only the 2-3 files that matter, and every change the agent makes updates the card
"""
from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path

from coder.core.run import Run, new
from coder.llm import models
from coder.memory import card as memory
from coder.memory import repomap

_SYS = ("You are onboarding onto a codebase from facts about it (not its full code). Write a concise project card in "
        "Markdown with exactly these sections:\n## Overview\n(3-6 lines: what it does, for whom)\n## Architecture\n(how "
        "the parts connect: entry points, layers, data flow; 4-10 lines)\n## How to run\n(commands)\n## Conventions\n"
        "(frameworks, patterns, style to follow when changing it; 2-6 bullets)\n## Key files\n(- `path`: role, the 10-20 "
        "most important)\nOnly what the facts support; say 'unknown' instead of guessing.")
_ENTRY = re.compile(r"(?:^|/)(?:main|app|manage|server|index|cli|__main__|wsgi|asgi)\.(?:py|js|ts|tsx|jsx|html)$")


def _read(p: Path, n: int) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:n] if p.is_file() else ""
    except OSError:
        return ""


def facts(root: Path) -> str:
    """Everything the AI needs to understand the project, in ~12k characters at most."""
    files = repomap.files(root, 600)
    rel = [f.relative_to(root).as_posix() for f in files]
    top = Counter(r.split("/")[0] if "/" in r else "(root)" for r in rel)
    ext = Counter(Path(r).suffix or "(none)" for r in rel)
    out = [f"Project folder: {root.name}", f"{len(rel)} source files. By folder: "
           + ", ".join(f"{k} {v}" for k, v in top.most_common(12)) + ". By type: "
           + ", ".join(f"{k} {v}" for k, v in ext.most_common(8)) + "."]
    pj = root / "package.json"
    if pj.is_file():
        try:
            d = json.loads(_read(pj, 50000))
            out.append("package.json: name " + str(d.get("name")) + "; scripts " + json.dumps(d.get("scripts") or {})[:600]
                       + "; dependencies " + ", ".join(list((d.get("dependencies") or {}))[:30])
                       + "; dev " + ", ".join(list((d.get("devDependencies") or {}))[:20]))
        except ValueError:
            pass
    for name in ("requirements.txt", "pyproject.toml", "Makefile", "docker-compose.yml", "Dockerfile"):
        if t := _read(root / name, 1200):
            out.append(f"--- {name} (start) ---\n{t}")
    for name in ("README.md", "readme.md", "README.rst", "README"):
        if t := _read(root / name, 1800):
            out.append(f"--- {name} (start) ---\n{t}")
            break
    entries = [r for r in rel if _ENTRY.search(r)][:8]
    if entries:
        out.append("Likely entry points: " + ", ".join(entries))
    try:
        log = subprocess.run(["git", "log", "--oneline", "-8"], cwd=root, capture_output=True, text=True, timeout=10).stdout
        if log.strip():
            out.append("Last commits:\n" + log.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    out.append("Project map (file: what it defines):\n" + repomap.text(root, 6000))
    return "\n\n".join(out)[:12000]


def learn(root: Path, run: Run | None = None) -> str:
    """Write the project card for a project the agent doesn't know yet. Returns a one-line summary."""
    run = run or new(f"learn {root.name}", root)
    text = models.ask(run, "review", _SYS, facts(root), 1100).strip()  # the fast model: reading facts is easy work
    text = re.sub(r"\A\s*#\s+[^\n]*\n+", "", text)  # its own title line (the card has one)
    if not text:
        return "I couldn't read the project right now."
    p = memory.path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    stack = _stack(root)
    how = memory.section(text, "How to run")
    run_cmd = next((ln.strip() for ln in how.splitlines()
                    if ln.strip() and not ln.strip().startswith(("#", "```", "-", "*")) and len(ln) < 120), "")
    run_cmd = re.sub(r"\s+#.*$", "", run_cmd)
    p.write_text(f"# {root.name}\n\n{memory.HEADER}\n\nStack: {stack}\n\nRun: `{run_cmd or '?'}`\n\n{text}\n\n"
                 f"## Map (functions, classes, ids per file; refreshed every run)\n\n{repomap.text(root, 5000)}\n\n"
                 f"## Decisions\n\n- {__import__('time').strftime('%Y-%m-%d')}: learned the project (card written)\n",
                 encoding="utf-8")
    overview = memory.section(text, "Overview").split("\n")[0][:200]
    return f"I learned {root.name} ({stack}): {overview} (card: .kurama/project.md, {run.tokens / 1000:.1f}k tokens, once)."


def _stack(root: Path) -> str:
    parts = []
    pj = _read(root / "package.json", 50000)
    for name, label in (("next", "Next.js"), ("react", "React"), ("vue", "Vue"), ("svelte", "Svelte"),
                        ("express", "Express"), ("typescript", "TypeScript"), ("vite", "Vite")):
        if f'"{name}"' in pj:
            parts.append(label)
    py = _read(root / "requirements.txt", 5000) + _read(root / "pyproject.toml", 5000)
    for name, label in (("fastapi", "FastAPI"), ("flask", "Flask"), ("django", "Django"), ("langchain", "LangChain"),
                        ("pygame", "Pygame"), ("streamlit", "Streamlit"), ("torch", "PyTorch")):
        if re.search(rf"\b{name}\b", py, re.I):
            parts.append(label)
    if not parts:
        exts = Counter(f.suffix for f in repomap.files(root, 300))
        parts = [{".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".html": "HTML/CSS/JS", ".jsx": "React (JSX)",
                  ".tsx": "React (TSX)", ".go": "Go", ".rs": "Rust", ".java": "Java", ".php": "PHP"}.get(e, e)
                 for e, _ in exts.most_common(2) if e]
    return ", ".join(dict.fromkeys(parts)) or "unknown"


def known(root: Path) -> bool:
    return memory.path(root).is_file()

