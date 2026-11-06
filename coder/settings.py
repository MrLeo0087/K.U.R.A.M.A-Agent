"""The coding agent's own settings (KURAMA's config only for shared paths)."""
from __future__ import annotations

import os
from pathlib import Path

ASK_TOKENS = int(os.getenv("KURAMA_CODER_ASK_TOKENS", "20000"))  # owner (11-06): bigger runs ask first
MAX_FILES = 14  # files written by the AI in one run (a scaffold may hold more)
MAX_FIX_ROUNDS = 3
MAX_REWRITE_CHARS = 16000  # an existing file longer than this is never rewritten whole (that could lose code)
FILE_CONTEXT_CHARS = 3500  # of each file a new file depends on, shown to the writer
TOKENS = {"easy": 900, "normal": 1600, "hard": 2600}  # rough output per file by difficulty (estimate + max_tokens)
PLAN_TOKENS = 1400
PROJECTS_DIR = os.getenv("KURAMA_PROJECTS_DIR", "~/projects")
CREATE_VITE = "create-vite@5.5.5"  # Node 18 here: create-vite 6+ needs Node 20
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".next", ".cache", ".kurama",
             ".mypy_cache", ".pytest_cache", ".ruff_cache"}


def data_dir() -> Path:
    from jarvis.core import config
    d = Path(config.DATA_DIR) / "coder"
    d.mkdir(parents=True, exist_ok=True)
    return d
