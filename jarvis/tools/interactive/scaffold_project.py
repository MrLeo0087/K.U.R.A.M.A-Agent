"""scaffold_project: create a new Python project skeleton (src layout, tests, README...) (confirm)."""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path
from typing import Literal

from jarvis.core import config
from jarvis.core.registry import tool
from jarvis.tools.interactive import _proc

Kind = Literal["python-cli", "fastapi", "langgraph-agent", "data-science"]

GITIGNORE = """# environments and secrets
venv/
.venv/
env/
.env
.env.*
!.env.example
# python
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
build/
dist/
# editors and OS
.vscode/
.idea/
.DS_Store
"""
DS_IGNORE = "# data and notebooks\ndata/raw/*\ndata/processed/*\n!data/**/.gitkeep\n.ipynb_checkpoints/\n"

REQUIREMENTS = {
    "python-cli": ["pytest"],
    "fastapi": ["fastapi", "uvicorn[standard]", "httpx", "pytest"],
    "langgraph-agent": ["langgraph", "langchain-groq", "python-dotenv", "pytest"],
    "data-science": ["numpy", "pandas", "matplotlib", "scikit-learn", "jupyter", "pytest"],
}

MAIN = {
    "python-cli": '''"""Command-line entry point."""
import argparse


def greet(name: str) -> str:
    return f"Hello, {{name}}!"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="{name}")
    parser.add_argument("name", nargs="?", default="world")
    args = parser.parse_args(argv)
    print(greet(args.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
    "fastapi": '''"""FastAPI app. Run: uvicorn {pkg}.main:app --reload --app-dir src"""
from fastapi import FastAPI

app = FastAPI(title="{name}")


@app.get("/health")
def health() -> dict:
    return {{"status": "ok"}}
''',
    "langgraph-agent": '''"""Minimal LangGraph agent on Groq. Needs GROQ_API_KEY in .env."""
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

load_dotenv()
MODEL = "{model}"


class State(TypedDict):
    messages: Annotated[list, add_messages]


def call_model(state: State) -> dict:
    from langchain_groq import ChatGroq

    return {{"messages": [ChatGroq(model=MODEL).invoke(state["messages"])]}}


def build_graph():
    g = StateGraph(State)
    g.add_node("model", call_model)
    g.add_edge(START, "model")
    g.add_edge("model", END)
    return g.compile()


if __name__ == "__main__":
    out = build_graph().invoke({{"messages": [("user", "Say hello in one line.")]}})
    print(out["messages"][-1].content)
''',
    "data-science": '''"""Data loading and processing helpers."""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW, PROCESSED = ROOT / "data" / "raw", ROOT / "data" / "processed"


def load_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(RAW / name)


def clean(df: pd.DataFrame) -> pd.DataFrame:
    return df.dropna(how="all").drop_duplicates()
''',
}

TESTS = {
    "python-cli": "from {pkg}.main import greet, main\n\n\ndef test_greet():\n    assert greet(\"Ada\") == \"Hello, Ada!\"\n\n\ndef test_main():\n    assert main([\"Ada\"]) == 0\n",
    "fastapi": "from fastapi.testclient import TestClient\n\nfrom {pkg}.main import app\n\n\ndef test_health():\n    assert TestClient(app).get(\"/health\").json() == {{\"status\": \"ok\"}}\n",
    "langgraph-agent": "from {pkg}.main import build_graph\n\n\ndef test_graph_builds():\n    assert build_graph() is not None\n",
    "data-science": "import pandas as pd\n\nfrom {pkg}.data import clean\n\n\ndef test_clean_drops_duplicates():\n    df = pd.DataFrame({{\"a\": [1, 1, None]}})\n    assert len(clean(df)) == 2\n",
}

RUN_HINT = {
    "python-cli": "python -m {pkg}.main",
    "fastapi": "uvicorn {pkg}.main:app --reload --app-dir src",
    "langgraph-agent": "python -m {pkg}.main",
    "data-science": "jupyter notebook notebooks/",
}


def package_name(name: str) -> str:
    return re.sub(r"\W+", "_", name.lower()).strip("_") or "app"


def files_for(name: str, kind: str) -> dict[str, str]:
    pkg = package_name(name)
    fmt = {"name": name, "pkg": pkg, "model": config.LLM_FAST}
    module = "data.py" if kind == "data-science" else "main.py"
    files = {
        "README.md": (f"# {name}\n\nA {kind} project.\n\n## Setup\n\n```bash\npython3 -m venv venv\n"
                      f"source venv/bin/activate\npip install -r requirements.txt\n```\n\n## Run\n\n"
                      f"```bash\n{RUN_HINT[kind].format(**fmt)}\npytest -q\n```\n"),
        ".gitignore": GITIGNORE + (DS_IGNORE if kind == "data-science" else ""),
        "requirements.txt": "\n".join(REQUIREMENTS[kind]) + "\n",
        "pytest.ini": "[pytest]\npythonpath = src\ntestpaths = tests\n",
        f"src/{pkg}/__init__.py": f'"""{name}."""\n__version__ = "0.1.0"\n',
        f"src/{pkg}/{module}": MAIN[kind].format(**fmt),
        "tests/__init__.py": "",
        f"tests/test_{module}": TESTS[kind].format(**fmt),
    }
    if kind == "langgraph-agent":
        files[".env.example"] = "GROQ_API_KEY=\n"
    if kind == "data-science":
        files.update({"data/raw/.gitkeep": "", "data/processed/.gitkeep": "", "notebooks/.gitkeep": ""})
    return files


def _make_venv(target: Path) -> str:
    py = Path(sys.executable).with_name("python3")
    py_cmd = str(py) if py.exists() else (shutil.which("python3") or "python3")
    try:
        cp = _proc.run([py_cmd, "-m", "venv", str(target / "venv")], timeout=180)
        return "venv created" if cp.returncode == 0 else f"venv failed: {cp.stderr.strip()[:120]}"
    except _proc.ProcError as e:
        return f"venv failed: {e}"


@tool(group="dev", safety="confirm",
      description="Scaffold a new Python project (python-cli, fastapi, langgraph-agent or data-science).")
def scaffold_project(name: str, kind: Kind = "python-cli", path: str = "~/projects", create_venv: bool = False) -> str:
    """Create a project skeleton.

    Args:
        name: Project folder name.
        kind: python-cli, fastapi, langgraph-agent or data-science.
        path: Parent folder (default ~/projects).
        create_venv: Also create a venv inside it.
    """
    name = (name or "").strip()
    if not re.fullmatch(r"[A-Za-z][\w.-]{0,63}", name):
        return "error: project name must start with a letter and use only letters, digits, - _ ."
    if kind not in REQUIREMENTS:
        return f"error: kind must be one of {', '.join(REQUIREMENTS)}"
    base = Path(path or "~/projects").expanduser()
    if not base.is_absolute() or not base.is_dir():  # "project1", "project1 then tara": spoken folders
        from jarvis.core.paths import smart_path
        base = smart_path(path or "", want="dir") or (base if base.is_absolute() else Path.home() / base)
    target = base.resolve() / name
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        return f"refused: {target} already exists and is not empty"
    files = files_for(name, kind)
    for rel, text in files.items():
        f = target / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    extra = f"; {_make_venv(target)}" if create_venv else ""
    return (f"created {kind} project at {target} ({len(files)} files: src/{package_name(name)}, tests, "
            f"README, .gitignore, requirements.txt){extra}")
