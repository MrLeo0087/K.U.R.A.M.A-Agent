"""GitHub in one line (plan 11-09 phase 9):

- "push my work": the project open in VS Code (or a named folder) -> a commit message from the changed files (one
  small AI call on the diff summary; 0 tokens when the AI is busy), shown with the files, ONE yes, then commit + push.
  A secret file (.env, keys) about to be committed stops it.
- "new project <name>": ~/projects/<name> with `uv init` + git + a first commit, opened in VS Code; with
  GITHUB_TOKEN in .env also a private GitHub repo and the first push (over SSH, like the owner's other repos).
- "did my build pass?": the last GitHub Actions run of the open project's repo.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from jarvis.core import config

SECRET = re.compile(r"(?:^|/)(?:\.env(?:\..*)?|.*\.pem|id_rsa.*|.*\.key|credentials\.json|token\.json)$", re.I)


def _git(root: Path, *args: str, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=timeout)


def project(folder: str = "") -> Path | None:
    if folder.strip():
        try:
            from jarvis.tools.interactive._proc import resolve_dir
            return resolve_dir(folder)
        except Exception:  # noqa: BLE001
            return None
    try:
        from coder.interfaces import link
        return link.vscode_root()
    except Exception:  # noqa: BLE001
        return None


def _message(root: Path, files: list[str]) -> str:
    stat = _git(root, "diff", "HEAD", "--stat").stdout[-1500:] or "\n".join(files)
    diff = _git(root, "diff", "HEAD", "--unified=1").stdout[:3500]
    try:
        from jarvis.core import llm
        r = llm.chat([{"role": "system", "content": "Write ONE git commit message line (max 72 chars, imperative, "
                                                    "no quotes, no prefix like 'feat:') for these changes."},
                      {"role": "user", "content": f"{stat}\n\n{diff}"}], tier="fast", purpose="commit_message",
                     max_tokens=60)
        msg = (r.text or "").strip().splitlines()[0].strip("\"' ")[:72]
        if msg:
            return msg
    except Exception:  # noqa: BLE001 - a plain message instead
        pass
    names = [Path(f).name for f in files[:3]]
    return "Update " + ", ".join(names) + (f" and {len(files) - 3} more" if len(files) > 3 else "")


def push(folder: str = "", ask=None) -> str:
    root = project(folder)
    if root is None or not root.is_dir():
        return "Which project? Open it in VS Code (or say 'push my work in <folder>')."
    if not (root / ".git").exists() and _git(root, "rev-parse", "--git-dir").returncode != 0:
        return f"{root.name} isn't a git repository yet. Say 'new project {root.name}' to start one, or run git init."
    st = _git(root, "status", "--porcelain").stdout.splitlines()
    files = [ln[3:].strip().strip('"') for ln in st if ln.strip()]
    if not files and not _git(root, "log", "@{u}..", "--oneline").stdout.strip():
        return f"Nothing to push in {root.name}: no changes, and everything is already on GitHub."
    if bad := [f for f in files if SECRET.search(f)]:
        return (f"Stopped: {', '.join(bad)} would go to GitHub (a secret file). Add it to .gitignore first, then "
                f"say 'push my work' again.")
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "main"
    msg = _message(root, files) if files else ""
    shown = ", ".join(files[:8]) + (f" +{len(files) - 8} more" if len(files) > 8 else "")
    q = (f"Commit {len(files)} file(s) in {root.name} ({shown}) as “{msg}” and push to {branch}?" if files
         else f"Push the commits waiting in {root.name} to {branch}?")
    if ask is not None and not ask(q):
        return "OK, nothing committed or pushed."
    if files:
        _git(root, "add", "-A")
        c = _git(root, "commit", "-m", msg)
        if c.returncode != 0:
            return f"error: commit failed: {(c.stderr or c.stdout).strip()[:200]}"
    p = _git(root, "push", "-u", "origin", branch, timeout=120)
    if p.returncode != 0:
        err = (p.stderr or p.stdout).strip()
        if "No such remote" in err or "does not appear to be a git repository" in err:
            return f"Committed “{msg}”, but {root.name} has no GitHub remote yet (git remote add origin <url>)."
        return f"Committed “{msg}”, but the push failed: {err[:200]}"
    return f"✅ Pushed {root.name} to {branch}" + (f": “{msg}” ({len(files)} files)." if files else ".")


def _slug(name: str) -> str:
    return re.sub(r"[^\w.-]+", "-", name.strip().lower()).strip("-") or "new-project"


def new_project(name: str, private: bool = True) -> str:
    slug = _slug(name)
    base = Path(os.getenv("KURAMA_PROJECTS_DIR", str(Path.home() / "projects"))).expanduser()
    root = base / slug
    if root.exists() and any(root.iterdir()):
        return f"{root} already exists and isn't empty. Pick another name."
    root.mkdir(parents=True, exist_ok=True)
    did = []
    uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    if Path(uv).exists() and subprocess.run([uv, "init", "--no-readme", "."], cwd=root, capture_output=True,
                                            timeout=60).returncode == 0:
        did.append("uv project")
    (root / "README.md").write_text(f"# {name.strip()}\n")
    gi = root / ".gitignore"
    gi.write_text((gi.read_text() if gi.exists() else "") + "\n.env\n.venv/\n__pycache__/\n")
    if _git(root, "init", "-b", "main").returncode == 0:
        _git(root, "add", "-A")
        _git(root, "commit", "-m", "Start the project")
        did.append("git")
    token = os.getenv("GITHUB_TOKEN", "").strip()
    remote = ""
    if token:
        try:
            import httpx
            r = httpx.post("https://api.github.com/user/repos", json={"name": slug, "private": private},
                           headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                           timeout=20)
            if r.status_code in (201, 422):  # 422: it exists already
                user = httpx.get("https://api.github.com/user", headers={"Authorization": f"Bearer {token}"},
                                 timeout=15).json().get("login")
                remote = f"git@github.com:{user}/{slug}.git"
                _git(root, "remote", "add", "origin", remote)
                if _git(root, "push", "-u", "origin", "main", timeout=120).returncode == 0:
                    did.append(f"GitHub repo ({'private' if private else 'public'}) pushed")
        except Exception as e:  # noqa: BLE001
            did.append(f"(GitHub repo failed: {str(e)[:80]})")
    if shutil.which("code"):
        subprocess.Popen(["code", str(root)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        did.append("opened in VS Code")
    tip = "" if token else (" For the GitHub repo too: put GITHUB_TOKEN=<a token with 'repo' scope> in .env "
                            "(github.com → Settings → Developer settings → Tokens), then say it again.")
    return f"📁 New project {root}: {', '.join(did)}.{tip}"


def ci(folder: str = "") -> str:
    root = project(folder)
    if root is None:
        return "Open the project in VS Code first."
    url = _git(root, "remote", "get-url", "origin").stdout.strip()
    m = re.search(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?$", url)
    if not m:
        return f"{root.name} has no GitHub remote."
    import httpx
    h = {"Accept": "application/vnd.github+json"}
    if t := os.getenv("GITHUB_TOKEN", "").strip():
        h["Authorization"] = f"Bearer {t}"
    try:
        r = httpx.get(f"https://api.github.com/repos/{m.group(1)}/{m.group(2)}/actions/runs", params={"per_page": 1},
                      headers=h, timeout=15)
        runs = r.json().get("workflow_runs") or []
    except Exception as e:  # noqa: BLE001
        return f"error: GitHub didn't answer ({str(e)[:80]})."
    if not runs:
        return f"{m.group(2)} has no GitHub Actions runs (no CI set up)."
    x = runs[0]
    icon = {"success": "✅", "failure": "❌", "cancelled": "⏹"}.get(x.get("conclusion") or "", "⏳")
    return (f"{icon} {m.group(2)}: last build “{x.get('name')}” on {x.get('head_branch')} — "
            f"{x.get('conclusion') or x.get('status')} ({x.get('html_url')})")
