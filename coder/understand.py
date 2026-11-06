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


def folder(request: str) -> tuple[Path, str]:
    """(project root, 'new' | 'add'). 'here' with an empty folder = build in it; with files = a new sub-folder for
    a new project, or the folder itself when the request adds to it ('add a scoreboard')."""
    here = link.vscode_root() if _HERE.search(request or "") else None
    adding = not _NEW.search(request or "") or bool(re.search(r"\b(?:add|extend|improve|update|upgrade)\b", request or "", I))
    if here is not None and here.is_dir():
        if _empty(here):
            return here, "new"
        if adding:
            return here, "add"
        return _free(here, slug(request)), "new"
    base = Path(settings.PROJECTS_DIR).expanduser()
    return _free(base, slug(request)), "new"


def question(request: str, stack: str) -> str:
    """Never asks about the stack (owner 11-06: "the stacks were examples: build it well"): when the words don't
    name one, the planner picks the best fit for the request and says which in the plan (change it with 'use X')."""
    return ""
