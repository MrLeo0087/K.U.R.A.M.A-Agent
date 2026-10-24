"""where_was_i: back to a project after a break: what you were doing, what's unfinished, what broke last, and what
to do next (safe; can open the project in VS Code). Facts come from git, the time machine, the error memory and
Training Guard (0 tokens); one short call words them as 2-3 sentences (config.WHERE_WAS_I_LLM)."""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

from jarvis.core import config, store, timemachine as tm
from jarvis.core.registry import tool

PROMPT = ("You help a developer resume work. From these facts write 2-3 short plain sentences: what they were "
          "working on, what is unfinished or broken, and the obvious next step. No lists, no preamble.")


def _ago(t: float) -> str:
    d = time.time() - t
    return f"{int(d // 60)} min ago" if d < 3600 else (f"{int(d // 3600)} h ago" if d < 86400 else f"{int(d // 86400)} days ago")


def facts(p: Path) -> list[str]:
    out = [f"Project: {p.name} ({p})"]
    git = (p / ".git").exists()
    run = lambda *a: subprocess.run(["git", "-C", str(p), *a], capture_output=True, text=True, timeout=20).stdout  # noqa: E731
    files: list[tuple[float, str]] = []
    if git:
        branch = run("rev-parse", "--abbrev-ref", "HEAD").strip()
        status = [ln[3:].strip().strip('"') for ln in run("status", "--porcelain", "-uall").splitlines() if len(ln) > 3]
        out.append(f"Branch {branch}; {len(status)} uncommitted file(s)")
        for rel in status:
            try:
                files.append(((p / rel).stat().st_mtime, rel))
            except OSError:
                files.append((0, rel + " (deleted)"))
        log = run("log", "-3", "--format=%s (%cr)").strip()
        if log:
            out.append("Last commits: " + "; ".join(log.splitlines()))
    if not files:
        files = sorted(((f.stat().st_mtime, str(f.relative_to(p))) for f in p.rglob("*.py")
                        if f.is_file() and "venv" not in f.parts), reverse=True)[:5]
    files.sort(reverse=True)
    if files:
        out.append("Recently edited: " + ", ".join(f"{n} ({_ago(t)})" if t else n for t, n in files[:5]))
    todos = []
    for _, rel in files[:5]:
        try:
            for i, ln in enumerate((p / rel).read_text(errors="replace").splitlines(), 1):
                if re.search(r"#\s*(TODO|FIXME|XXX|HACK)\b", ln):
                    todos.append(f"{rel}:{i} {ln.strip()[:80]}")
        except OSError:
            continue
    if todos:
        out.append("TODOs: " + "; ".join(todos[:4]))
    names = {Path(n).name for _, n in files}
    errs = [dict(r) for r in store._exec("SELECT * FROM errors WHERE last_seen > ? ORDER BY last_seen DESC LIMIT 5",
                                         (time.time() - 3 * 86400,))]
    errs = [e for e in errs if not e["where_"] or any(n in e["where_"] for n in names)]
    if errs:
        e = errs[0]
        out.append(f"Last error ({_ago(e['last_seen'])}): {e['error'][:120]}" + (f" at {e['where_']}" if e["where_"] else ""))
    runs = [w for w in store.watches_list() if str(p) in str((w.get("state") or {}).get("cwd", "")) + w["target"]][:2]
    for w in runs:
        from jarvis.core import training
        out.append("Training: " + training.describe(w))
    try:
        if tm.shadow(p).joinpath("HEAD").exists():
            out.append("Snapshots: " + tm.history(p, n=3).split("\n", 1)[-1].replace("\n", "; "))
    except tm.TMError:
        pass
    return out


@tool(group="git", safety="safe",
      description="Where was I? Resume a project after a break: what you were doing, unfinished changes, TODOs, the "
                  "last error and training run, and the next step; can open it in VS Code.")
def where_was_i(project: str = "", open_editor: bool = False) -> str:
    """Resume work on a project.

    Args:
        project: The project (loose names work); empty = the one you changed most recently.
        open_editor: Also open the project in VS Code.
    """
    try:
        p = tm.resolve(project)
    except tm.TMError as e:
        return f"error: {e}"
    lines = facts(p)
    summary = ""
    if config.WHERE_WAS_I_LLM:
        from jarvis.core import llm
        try:
            summary = " ".join(str(llm.chat([{"role": "system", "content": PROMPT},
                                             {"role": "user", "content": "\n".join(lines)[:2500]}],
                                            tier="fast", purpose="where_was_i", max_tokens=250, temperature=0.2)).split())
        except Exception:
            summary = ""
    if open_editor and shutil.which("code"):
        subprocess.Popen(["code", str(p)], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        lines.append("Opened in VS Code.")
    return (summary + "\n\n" if summary else "") + "\n".join(lines)
