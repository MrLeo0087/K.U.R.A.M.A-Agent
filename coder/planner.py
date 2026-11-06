"""The plan, in ONE call: the files (each with its job, the files it uses and how hard it is), how they connect,
the command to run it and what is left for later. For a scaffolded project (React via Vite, a GitHub starter) the
plan lists only the files to add or replace on top of it; for an existing project it gets the project's map and
memory, never its whole code."""
from __future__ import annotations

import json
import re

from coder import models, settings
from coder.run import FileSpec, Run

_SYS = """You are a senior engineer planning a small, well-organized, runnable project for a laptop (Linux, no GPU).
Return ONLY a JSON object, no prose:
{"name": "<short project name>",
 "files": [{"path": "<relative path>", "purpose": "<what it holds, one line>", "uses": ["<other planned files it imports/links>"], "level": "easy|normal|hard"}],
 "run": "<the exact command to run it>",
 "notes": "<2-4 lines: how the files connect, key design choices>",
 "todo": ["<good next improvements, max 4>"]}
Rules: industry-standard structure and names for the stack; as FEW files as a clean design needs (max %d), no tests
unless asked, no binary files (images, sounds, fonts: the code draws them with SVG / emoji / CSS / code), no
package lock files; a plain HTML/CSS/JS project must open by double-clicking index.html: classic <script> tags in
dependency order, NO ES modules / import statements (browsers block them on file://); order files so each comes after the files it uses; level:
easy = styles/config/README/small helpers, hard = the core logic; never put secrets in code (read them from
environment variables; .env.example ONLY when the project really needs a key or setting)."""


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("the plan wasn't JSON")
    raw = m.group(0)
    try:
        return json.loads(raw)
    except ValueError:
        return json.loads(re.sub(r",\s*([}\]])", r"\1", raw))  # a trailing comma


def _ok_path(p: str) -> bool:
    return bool(p) and not p.startswith(("/", "~")) and ".." not in p.split("/") and len(p) < 120 and \
        not re.search(r"(?:^|/)(?:node_modules|\.git|\.venv|venv)/|package-lock\.json$|\.(?:png|jpg|ico|zip)$", p)


def order(files: list[FileSpec]) -> list[FileSpec]:
    """Each file after the files it uses (the writer sees them), the plan's order otherwise. A page comes before
    its styles and scripts (they must use the page's ids and classes), whatever the page 'uses'."""
    by = {f.path: f for f in files}
    out: list[FileSpec] = []
    seen: set[str] = set()

    def add(f: FileSpec, stack: tuple[str, ...]) -> None:
        if f.path in seen or f.path in stack:
            return
        for u in ([] if f.path.endswith(".html") else f.uses):
            if u in by:
                add(by[u], (*stack, f.path))
        if f.path not in seen:
            seen.add(f.path)
            out.append(f)
    for f in files:
        add(f, ())
    return out


def make(run: Run, existing: str = "", memory_text: str = "", scaffold_files: list[str] | None = None) -> None:
    """Fill run.files / run_cmd / notes / plan_name from one smart call."""
    user = [f"Request: {run.request}", f"Stack: {run.stack or 'choose the best fit'}"]
    if scaffold_files:
        user.append("Already scaffolded (keep; list a file only if you REPLACE it or add a new one):\n"
                    + "\n".join(scaffold_files[:60]))
    if existing:
        user.append("Existing project map (add to it; list only files to change or add):\n" + existing)
    if memory_text:
        user.append("Project memory:\n" + memory_text)
    out = models.ask(run, "plan", _SYS % settings.MAX_FILES, "\n\n".join(user), settings.PLAN_TOKENS)
    d = _json(out)
    seen: set[str] = set()
    files = []
    for f in d.get("files") or []:
        path = re.sub(r"^(?:\./)+", "", str(f.get("path") or "").strip())  # (lstrip('./') ate '.gitignore')
        if not _ok_path(path) or path in seen:
            continue
        seen.add(path)
        level = str(f.get("level") or "normal").lower()
        files.append(FileSpec(path, str(f.get("purpose") or "")[:200],
                              [re.sub(r"^(?:\./)+", "", u) for u in (f.get("uses") or []) if isinstance(u, str)][:6],
                              level if level in settings.TOKENS else "normal"))
    if not files:
        raise ValueError("the plan has no files")
    run.files = order(files[: settings.MAX_FILES])
    run.plan_name = str(d.get("name") or run.root.name)[:60]
    run.run_cmd = str(d.get("run") or "")[:200]
    run.notes = str(d.get("notes") or "")[:800]
    run.todo = [str(t)[:120] for t in (d.get("todo") or [])][:4]
    run.save()


def text(run: Run) -> str:
    """The plan as the owner sees it in the workspace."""
    lines = [f"# Plan: {run.plan_name}", "", f"Folder: `{run.root}`", f"Stack: {run.stack or 'auto'}"
             + (f" (starts from {run.scaffold})" if run.scaffold else ""), ""]
    lines += [f"{i}. `{f.path}` ({f.level}): {f.purpose}" for i, f in enumerate(run.files, 1)]
    if run.notes:
        lines += ["", "How it fits together: " + run.notes]
    if run.run_cmd:
        lines += ["", f"Run: `{run.run_cmd}`"]
    if run.estimate:
        lines += ["", f"Cost: about {run.estimate / 1000:.1f}k tokens"]
    return "\n".join(lines)
