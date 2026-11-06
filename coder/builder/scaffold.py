"""The starting files, made without the AI (0 tokens), so the structure is industry standard:
  react    `npm create vite` (React + TypeScript template: Vite, ESLint, tsconfig) -- nothing is installed
           (the README says `npm install`, which the owner runs: installs need their yes)
  github   a starter repository (github.py): only when asked ("from GitHub", "use a template / boilerplate")
Everything else starts from an empty folder and the plan."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from coder.memory import repomap
from coder.core import settings  # noqa: F401
from coder.core.run import Run

GENERATORS = {"react": "vite-react-ts"}
_WANTS_GITHUB = re.compile(r"\b(?:github|git\s*hub|starter|boilerplate|template)\b", re.I)


def wants_github(request: str) -> bool:
    return bool(_WANTS_GITHUB.search(request or ""))


def vite_react(run: Run) -> str:
    """npm create vite (React + TS) into run.root. Returns '' or why it couldn't."""
    if not shutil.which("npm"):
        return "npm isn't installed, so I'll write the React files myself"
    parent, name = run.root.parent, run.root.name
    parent.mkdir(parents=True, exist_ok=True)
    if run.root.exists() and any(run.root.iterdir()):
        return "the folder isn't empty"
    try:
        r = subprocess.run(["npm", "create", "--yes", settings.CREATE_VITE, name, "--", "--template", "react-ts"],
                           cwd=parent, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"npm create vite failed ({e})"
    if r.returncode != 0 or not (run.root / "package.json").exists():
        return "npm create vite failed: " + (r.stderr or r.stdout)[-200:]
    return ""


# the files `npm create vite --template react-ts` makes (create-vite 5.5): the plan builds on them
VITE_REACT_TS = ["index.html", "package.json", "vite.config.ts", "tsconfig.json", "tsconfig.app.json",
                 "tsconfig.node.json", "eslint.config.js", "README.md", "public/vite.svg", "src/main.tsx",
                 "src/App.tsx", "src/App.css", "src/index.css", "src/vite-env.d.ts", "src/assets/react.svg"]


def choose(run: Run) -> list[str]:
    """At plan time (before the yes): what the project will start from, and its files for the planner.
    Nothing is written into the project here."""
    if run.kind != "new":
        return []
    if wants_github(run.request):
        from coder.builder import github
        if github.starter(run):
            return [p.relative_to(github.staging(run)).as_posix() for p in repomap.files(github.staging(run))]
    if GENERATORS.get(run.stack) == "vite-react-ts" and shutil.which("npm"):
        run.scaffold = "npm create vite (React + TypeScript)"
        return VITE_REACT_TS
    return []


def make(run: Run) -> str:
    """After the yes: put the chosen start into run.root. Returns '' or why it couldn't (then the plan's files
    are written on an empty folder)."""
    if run.scaffold.startswith("github:"):
        from coder.builder import github
        n = github.copy_in(run)
        return "" if n else "the GitHub starter was empty"
    if run.scaffold.startswith("npm create vite"):
        from coder.core import safety
        safety.begin(run)
        return vite_react(run)
    return ""


def fixed_run_cmd(run: Run) -> None:
    """A scaffolded React app runs with npm (whatever the plan said)."""
    if run.scaffold.startswith("npm create vite"):
        run.run_cmd = "npm install && npm run dev"
