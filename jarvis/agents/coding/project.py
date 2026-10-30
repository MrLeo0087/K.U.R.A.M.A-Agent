"""New project in one sentence (owner: setting up projects takes time): one smart call plans and writes a small,
runnable project (at most AGENT_PROJECT_MAX_FILES files, requirements.txt, README); KURAMA writes it into
~/projects/<name> (never over an existing folder), makes a .venv, installs the requirements, opens it in VS Code
and runs it once; a crash on that first run becomes the failure 'fix it' fixes. Runs as a background job.
"""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

from jarvis.agents.coding import blocks, terminal
from jarvis.core import config

_SYS = ("You create small, complete, runnable Python projects. Reply with: a line 'NAME: <snake_case_name>', a line "
        "'RUN: <the command that runs it from the project root>', then every file. " + blocks.FORMAT_RULE +
        " Always include requirements.txt (only what is needed, no versions unless required) and a short README.md "
        "(what it is, how to run). Keep it small: at most {n} files, clear code, type hints, basic error handling. "
        "A web app must listen on 127.0.0.1.")


_SAFE_RUN = re.compile(r"(?:python3?|uvicorn|flask|streamlit|pytest)(?:\s+[\w./:=@,-]+)*")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")[:40] or "project"


def _free(base: Path, name: str) -> Path:
    p, i = base / name, 2
    while p.exists() and any(p.iterdir()):
        p, i = base / f"{name}_{i}", i + 1
    return p


def _run(cmd: list[str], cwd: Path, timeout: float) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as e:
        return -9, str(e.stdout or "") + str(e.stderr or "")  # still running = a server that started fine
    except OSError as e:
        return 1, str(e)


def build(ctx, description: str, name: str = "", where: str = "") -> str | None:
    from jarvis.core import llm
    ctx.progress("planning the project")
    reply = str(llm.chat([{"role": "system", "content": _SYS.format(n=config.AGENT_PROJECT_MAX_FILES)},
                          {"role": "user", "content": description}], tier="smart", purpose="agent_project",
                         max_tokens=config.AGENT_PROJECT_MAX_TOKENS))
    ctx.check()
    m_name = re.search(r"NAME:\s*([\w-]+)", reply)
    m_run = re.search(r"RUN:\s*`?([^`\n]+)`?", reply)
    base = Path(where).expanduser() if where else Path(config.AGENT_PROJECTS_DIR).expanduser()
    root = _free(base, _slug(name or (m_name.group(1) if m_name else description)))
    files = blocks.parse(reply)[: config.AGENT_PROJECT_MAX_FILES + 2]
    if not files:
        ctx.progress("» The AI didn't return any files; nothing was created. Try describing it again.")
        return None
    for rel, code in files:
        p = (root / rel).resolve()
        if str(p).startswith(str(root.resolve())):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(code, encoding="utf-8")
    ctx.progress(f"wrote {len(files)} files; making the venv")
    _run(["python3", "-m", "venv", ".venv"], root, 120)
    py = str(root / ".venv" / "bin" / "python")
    if (root / "requirements.txt").exists() and (root / "requirements.txt").read_text().strip():
        ctx.progress("installing the requirements")
        code, out = _run([py, "-m", "pip", "install", "-q", "-r", "requirements.txt"], root, config.AGENT_PIP_TIMEOUT_S)
        if code not in (0,):
            terminal.record(f"{py} -m pip install -r requirements.txt", str(root), code, out)
            ctx.progress(f"» {root.name} is written, but installing the requirements failed. Say 'fix it'.")
            return str(root)
    ctx.check()
    from jarvis.tools.general import _sys
    try:
        _sys.run(["code", str(root)], timeout=15)
    except _sys.SysError:
        pass
    run = (m_run.group(1).strip() if m_run else "python main.py")
    if not _SAFE_RUN.fullmatch(run):  # the AI's run command is never executed blindly
        ctx.progress(f"» {root.name} is ready in {root} ({len(files)} files, opened in VS Code). Run it with: {run}")
        return str(root)
    run_cmd = re.sub(r"^python3?\b", py, run)
    run_cmd = re.sub(r"^(uvicorn|flask|streamlit|pytest)\b", rf"{root}/.venv/bin/\1", run_cmd)
    ctx.progress(f"running it once: {run}")
    code, out = _run(["bash", "-lc", run_cmd], root, config.AGENT_FIRST_RUN_S)
    if code in (0, -9):
        ctx.progress(f"» {root.name} is ready in {root} ({len(files)} files, opened in VS Code). "
                     f"Run it with: {run}" + (" (it started fine)" if code == -9 else ""))
    else:
        terminal.record(run_cmd, str(root), code, out)
        ctx.progress(f"» {root.name} is ready in {root}, but the first run crashed. Say 'fix it' and I'll fix it.")
    return str(root)


def start(description: str, name: str = "", where: str = "") -> str:
    from jarvis.core import jobs
    if len(description.split()) < 3:
        return "Tell me what the project should do, e.g. 'a FastAPI app for a to-do list with SQLite'."
    jobs.get_manager().submit(f"New project: {description[:50]}", "code",
                              lambda ctx: build(ctx, description, name, where))
    return ("Setting it up in the background: files, requirements, venv, VS Code, a first run "
            f"(about a minute; ~{config.AGENT_PROJECT_MAX_TOKENS // 1000 + 1}k tokens at most). I'll tell you when it's ready.")
