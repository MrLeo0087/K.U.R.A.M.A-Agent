"""New project in one sentence (owner: a short plan first, then small, effective code; it knows where to put it).
1. The kind of project is picked by meaning (templates.py, 0 tokens) -> the plan is said AT ONCE: folder + files.
2. One smart call writes only the template's code files (small, ~2-3k tokens); requirements + README come from the
   template (+ any extra packages the AI names). Where: "here / in this project" = the folder open in VS Code
   (a sub-folder when it already has files), else ~/projects/<name>. Never over an existing folder.
3. An empty .venv, opened in VS Code. NO package is installed and nothing is run (owner installs them himself);
   requirements.txt + README (how to install, CPU-only PyTorch, how to run). Steps 2-3 run as a background job.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from jarvis.agents.coding import blocks, templates
from jarvis.core import config

_SYS = ("You write small, effective, runnable code for a new project. Write ONLY these files (no others): {files}. "
        "Keep each short and clear (type hints, brief comments, sensible defaults that run on a laptop CPU in a few "
        "minutes). " + blocks.FORMAT_RULE + " If the code needs more pip packages than {reqs}, add a last line "
        "'EXTRA: pkg1 pkg2'.")
_SAFE_RUN = re.compile(r"(?:python3?|uvicorn|flask|streamlit|pytest)(?:\s+[\w./:=@,-]+)*")
_HERE = re.compile(r"\b(?:here|in\s+this\s+(?:project|fold?er|fodler|foldr|workspace|directory)|"
                   r"in\s+the\s+open\s+(?:project|folder)|in\s+vs\s*code|this\s+(?:fold?er|fodler|foldr))\b", re.I)


def _slug(text: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _FILLER][:4]
    return "_".join(words)[:40] or "project"


_FILLER = {"set", "setup", "up", "a", "an", "the", "make", "create", "new", "project", "build", "me", "start", "for",
           "with", "here", "in", "this", "please", "kurama", "folder", "app", "my", "of", "to"}


def _free(base: Path, name: str) -> Path:
    p, i = base / name, 2
    while p.exists() and any(p.iterdir()):
        p, i = base / f"{name}_{i}", i + 1
    return p


def where(description: str) -> Path:
    """The folder the project goes in: the open VS Code project for 'here', else ~/projects."""
    if _HERE.search(description or ""):
        from jarvis.agents.coding.bridge import project_root
        if (root := project_root()) is not None:
            return root
    return Path(config.AGENT_PROJECTS_DIR).expanduser()


def _run(cmd: list[str], cwd: Path, timeout: float) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as e:
        return -9, str(e.stdout or "") + str(e.stderr or "")  # still running = a server that started fine
    except OSError as e:
        return 1, str(e)


def plan(description: str) -> tuple[templates.Template, Path]:
    t = templates.pick(description)
    base = where(description)
    root = base if base.is_dir() and not any(x for x in base.iterdir() if not x.name.startswith(".")) \
        else _free(base, _slug(description))
    return t, root


def build(ctx, description: str, t: templates.Template, root: Path) -> str | None:
    from jarvis.core import llm
    files_txt = "; ".join(f"{p} ({what})" for p, what in t.files.items() if not p.startswith("."))
    ctx.progress(f"writing {len(t.files)} files")
    reply = str(llm.chat([{"role": "system", "content": _SYS.format(files=files_txt, reqs=t.requirements or "none")},
                          {"role": "user", "content": f"Project: {description}\nKind: {t.title}"}], tier="smart",
                         purpose="agent_project", max_tokens=config.AGENT_PROJECT_MAX_TOKENS))
    ctx.check()
    code = {rel: body for rel, body in blocks.parse(reply) if rel in t.files}
    if not code:
        ctx.progress("» The AI returned no code; nothing was created. Try again in a minute.")
        return None
    extra = (re.search(r"^EXTRA:\s*(.+)$", reply, re.M) or [None, ""])[1].split()
    reqs = list(dict.fromkeys([*t.requirements, *[e for e in extra if re.fullmatch(r"[\w.\-\[\]=<>]+", e)]]))
    root.mkdir(parents=True, exist_ok=True)
    for rel, what in t.files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(code.get(rel) or (what + "\n" if rel.startswith(".") else f"# {what}\n"), encoding="utf-8")
    if reqs:
        (root / "requirements.txt").write_text("\n".join(reqs) + "\n")
    torch_pkgs = [r for r in reqs if re.match(r"(?:torch|torchvision|torchaudio)\b", r)]
    install = ""
    if reqs:  # owner: never installed by KURAMA (they pick their own venv); the README says how
        install = ("pip install -r requirements.txt\n" if not torch_pkgs else
                   f"pip install {' '.join(torch_pkgs)} --index-url https://download.pytorch.org/whl/cpu  # CPU-only PyTorch\n"
                   + (f"pip install {' '.join(r for r in reqs if r not in torch_pkgs)}\n" if len(reqs) > len(torch_pkgs) else ""))
    (root / "README.md").write_text(
        f"# {root.name}\n\n{description}\n\n## Files\n\n" + "".join(f"- `{rel}`: {what}\n" for rel, what in t.files.items())
        + (f"\n## Install\n\n```bash\nsource .venv/bin/activate   # the empty .venv made for you (or use your own)\n"
           f"{install}```\n" if install else "")
        + f"\n## Run\n\n```bash\n{t.run}\n```\n")
    ctx.progress("making the .venv (no packages)")
    _run(["python3", "-m", "venv", ".venv"], root, 120)  # owner: a venv yes, packages no (they install them)
    from jarvis.tools.general import _sys
    try:
        _sys.run(["code", str(root)], timeout=15)
    except _sys.SysError:
        pass
    ctx.progress(f"» {root.name} is ready in {root} (opened in VS Code): {', '.join([*t.files, 'requirements.txt', 'README.md'])}. "
                 f"A .venv is ready (empty); nothing was installed: the README says how{' (CPU-only PyTorch)' if torch_pkgs else ''}. Run it with: {t.run}")
    return str(root)


def start(description: str, name: str = "", where_: str = "", confirmed: bool = False) -> str:
    """The plan at once (0 tokens), the building in the background (announced when done)."""
    from jarvis.core import jobs, safety
    if len(description.split()) < 3:
        return "Tell me what the project should do, e.g. 'a FastAPI app for a to-do list'."
    t, root = plan(description)
    if where_:
        root = _free(Path(where_).expanduser(), _slug(name or description))
    est = 400 + config.AGENT_PROJECT_TOKENS_PER_FILE * len([f for f in t.files if not f.startswith(".")])
    if est > config.AGENT_ASK_ABOVE_TOKENS and not confirmed:
        from jarvis.agents.coding import changes
        return changes.ask_cost("project", {"description": description, "name": name, "where_": where_}, est,
                                f"Building this {t.title} project ({len(t.files)} files)")
    job = jobs.get_manager().submit(f"New project: {root.name}", "code", lambda ctx: build(ctx, description, t, root))
    if (started := safety.context().get("jobs")) is not None:
        started.append(job.id)  # the dashboard watches it and says when it's ready
    files = ", ".join([*t.files, *(["requirements.txt"] if t.requirements else []), "README.md"])
    return (f"Plan ({t.title}): {root} — {files}"
            f". Writing it now in the background, nothing gets installed (~{est / 1000:.1f}k tokens); "
            f"I'll tell you when it's ready.")
