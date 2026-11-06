"""What to build and where, without the AI: the stack from the words (react, pygame, html/css/js, fastapi...), the
folder ("here / this folder / in VS Code" = the project open in VS Code, else ~/projects/<name>), new project or
an addition to an existing one. It never asks which stack: the plan picks the best one and shows it."""
from __future__ import annotations

import re
from pathlib import Path

from coder import link, settings

I = re.I
# (stack, words that name it): the first that matches wins; order = most specific first
STACKS: list[tuple[str, str]] = [
    ("react", r"\breact(?:\s*js)?\b|\bvite\b"),
    ("next", r"\bnext\s*\.?\s*js\b|\bnextjs\b"),
    ("pygame", r"\bpygame\b|\bpython\b.*\b(?:game|ui|gui|window)\b|\b(?:game|gui)\b.*\bpython\b"),
    ("tkinter", r"\btkinter\b|\bdesktop\s+app\b.*\bpython\b"),
    ("web", r"\bhtml\b|\bcss\b|\bjavascript\b|\bjs\b|\bwebsite\b|\bweb\s*page\b|\blanding\s+page\b|\bbrowser\s+game\b"),
    ("fastapi", r"\bfast\s*api\b|\brest\s+api\b"),
    ("flask", r"\bflask\b"),
    ("streamlit", r"\bstreamlit\b"),
    ("node", r"\bnode(?:\.?js)?\b|\bexpress\b"),
    ("python", r"\bpython\b|\bscript\b|\bcli\b|\bcommand[- ]line\b"),
]
_HERE = re.compile(r"\b(?:here|in\s+this\s+(?:project|fold?er|workspace|directory|repo)|this\s+fold?er|"
                   r"in\s+(?:the\s+)?(?:open|current)\s+(?:project|folder)|in\s+vs\s*code)\b", I)
_NEW = re.compile(r"\b(?:new|create|make|build|start|set\s*up|generate|scaffold)\b", I)
_FILLER = {"set", "setup", "up", "a", "an", "the", "make", "create", "new", "project", "build", "me", "start", "for",
           "with", "here", "in", "this", "please", "kurama", "folder", "app", "my", "of", "to", "i", "want", "very",
           "good", "nice", "now", "and", "it", "code", "vs", "using", "industry", "standard", "level", "simple"}


def stack_of(request: str) -> str:
    for name, rx in STACKS:
        if re.search(rx, request or "", I):
            return name
    return ""


def slug(request: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", (request or "").lower()) if w not in _FILLER and len(w) > 1]
    words = [w for w in words if not re.fullmatch(r"html|css|js|javascript|python|react|ui|game|with|in", w)][:3] or words[:3]
    return "-".join(words)[:40] or "project"


def _empty(p: Path) -> bool:
    return p.is_dir() and not any(x for x in p.iterdir() if not x.name.startswith("."))


def _free(base: Path, name: str) -> Path:
    p, i = base / name, 2
    while p.exists() and not _empty(p):
        p, i = base / f"{name}-{i}", i + 1
    return p


_ELSEWHERE = re.compile(r"\b(?:new|separate|another|own)\s+(?:folder|project|directory|repo)\b|\bin\s+(?:~/|/)\S+|"
                        r"\bin\s+(?:my\s+)?(?:projects|downloads|documents|desktop)\b", I)
_NEW_APP = re.compile(r"\b(?:create|make|build|start|generate|set\s*up)\b.{0,40}\b(?:game|app|application|website|site|"
                      r"page|project|tool|bot|api|dashboard|clone)\b", I)
BIG_PROJECT_FILES = 15  # an open project this big + a request for a whole new app: ask where (it may be unrelated)


def folder(request: str, answer: str = "") -> tuple[Path, str, str]:
    """(project root, 'new' | 'add', a question or ''). The project open in VS Code is the one being worked on
    (owner 11-06: "if a project is open in VS Code, work on that project, not a random folder; ask if unsure"):
      empty open folder                      -> build in it
      the request adds / changes something   -> into the open project
      a whole new app while a big project is open -> ask: into it, or a new folder? (answer: 'here' / 'new folder')
      'in a new folder', 'in ~/x', nothing open -> a new folder (~/projects/<name>)"""
    here = link.vscode_root()
    base = Path(settings.PROJECTS_DIR).expanduser()
    elsewhere = bool(_ELSEWHERE.search(request or "")) or answer == "new"
    if here is None or not here.is_dir() or elsewhere:
        return _free(base, slug(request)), "new", ""
    if _empty(here):
        return here, "new", ""
    if answer == "here" or _HERE.search(request or ""):
        return here, "add", ""
    from coder import repomap
    if _NEW_APP.search(request or "") and len(repomap.files(here, BIG_PROJECT_FILES + 1)) > BIG_PROJECT_FILES:
        return here, "add", (f"Should I build it inside {here.name} (the project open in VS Code), or in a new folder "
                             "of its own? Say 'here' or 'new folder'.")
    return here, "add", ""


def question(request: str, stack: str) -> str:
    """Never asks about the stack (owner 11-06: "the stacks were examples: build it well"): when the words don't
    name one, the planner picks the best fit for the request and says which in the plan (change it with 'use X')."""
    return ""
