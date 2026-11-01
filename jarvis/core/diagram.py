"""Diagrams, 0 tokens, drawn with Pillow (data/outputs/diagrams/*.png):

- project: from the project's README only (headings -> branches, their bullet points -> leaves). No README = no
  diagram (the whole project is never scanned).
- flow: the steps the user says ('login, check the password, open the dashboard').
- code: the Python file open in VS Code: which function calls which (ast, nothing runs).
"""
from __future__ import annotations

import ast
import re
import textwrap
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from jarvis.core import config

BG, FG, MUTED, LINE = (17, 19, 24), (232, 228, 222), (139, 134, 128), (70, 74, 84)
FILL = [(255, 138, 61), (44, 50, 62), (32, 37, 46), (27, 31, 38)]  # by depth: root, branch, leaf...
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
MAX_NODES = 70
README_NAMES = ("README.md", "readme.md", "Readme.md", "README.rst", "README.txt", "README")


def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(BOLD if bold else FONT, size)
    except OSError:
        return ImageFont.load_default()


def _clean(s: str) -> str:
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)|<[^>]+>", "", s)  # images, html
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)  # links -> text
    s = re.sub(r"[*_`#>]|:\w+:", "", s)
    return " ".join(s.split()).strip(" -:")


# ------------------------------------------------------------------ graphs
def readme_tree(text: str, name: str) -> tuple[list[str], list[tuple[int, int]]]:
    """Headings + their first bullets -> (labels, edges parent->child). Code blocks and tables are skipped."""
    labels, edges = [name], []
    stack: list[tuple[int, int]] = [(0, 0)]  # (heading level, node)
    bullets = 0
    in_code = False
    for line in text.splitlines():
        if line.strip().startswith(("```", "~~~")):
            in_code = not in_code
            continue
        if in_code or line.strip().startswith("|"):
            continue
        if m := re.match(r"^(#{1,4})\s+(.+)", line):
            level, title = len(m.group(1)), _clean(m.group(2))
            if not title or (level == 1 and len(labels) == 1):
                labels[0] = title or labels[0]  # the H1 is the root
                continue
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else 0
            labels.append(title[:60])
            edges.append((parent, len(labels) - 1))
            stack.append((level, len(labels) - 1))
            bullets = 0
        elif (m := re.match(r"^(?:\s{0,1})[-*+]\s+(.+)|^\d+[.)]\s+(.+)", line)) and len(stack) > 1 and bullets < 5:
            item = _clean(m.group(1) or m.group(2))
            item = re.split(r"\s*\((?!\))|(?<=\w):|\s[—–-]\s|\.\s", item)[0].strip()  # the point, not its explanation
            if item and len(item) > 2:
                labels.append(item if len(item) <= 48 else item[:46].rsplit(" ", 1)[0] + "…")
                edges.append((stack[-1][1], len(labels) - 1))
                bullets += 1
        if len(labels) >= MAX_NODES:
            break
    return labels, edges


def flow(steps: list[str]) -> tuple[list[str], list[tuple[int, int]]]:
    steps = [s for s in (x.strip(" .") for x in steps) if s][:20]
    return steps, [(i, i + 1) for i in range(len(steps) - 1)]


def split_steps(text: str) -> list[str]:
    """'login, then check the password -> open the dashboard and show the name' -> 4 steps."""
    parts = re.split(r"\s*(?:->|→|=>|;|\n|,\s*(?:and\s+)?then\s+|\bthen\b|,|\band\s+then\b|\bafter\s+that\b|\bfinally\b)\s*", text)
    parts = [re.sub(r"^(?:and|then|first|next)\s+|\s+(?:and|then)$", "", x.strip(" .,"), flags=re.I) for x in parts]
    return [p[0].upper() + p[1:] for p in parts if p]


def call_graph(src: str, name: str) -> tuple[list[str], list[tuple[int, int]]]:
    """Functions/methods of a Python file and which of them call which (only calls inside the file)."""
    tree = ast.parse(src)
    funcs: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.setdefault(node.name, node)
    labels, idx = [name], {}
    for f in funcs:
        idx[f] = len(labels)
        labels.append(f + "()")
    edges = set()
    called = set()
    for f, node in funcs.items():
        for c in ast.walk(node):
            if isinstance(c, ast.Call):
                callee = c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", "")
                if callee in idx and callee != f:
                    edges.add((idx[f], idx[callee]))
                    called.add(callee)
    top_calls = set()  # module level: what the file runs itself
    for stmt in tree.body:
        if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
            for c in ast.walk(stmt):
                if isinstance(c, ast.Call) and getattr(c.func, "id", "") in idx:
                    top_calls.add(c.func.id)
    for f in funcs:  # entry points hang under the file: called at top level, or never called by another function
        if f in top_calls or f not in called:
            edges.add((0, idx[f]))
    return labels[:MAX_NODES], sorted(e for e in edges if max(e) < MAX_NODES)


# ------------------------------------------------------------------ layout + draw
def _layers(n: int, edges: list[tuple[int, int]]) -> list[int]:
    """Depth of each node (longest path from a root; cycles cut)."""
    kids = defaultdict(list)
    has_parent = set()
    for a, b in edges:
        kids[a].append(b)
        has_parent.add(b)
    depth = [0] * n
    roots = [i for i in range(n) if i not in has_parent] or [0]
    seen = set()
    order = list(roots)
    while order:
        a = order.pop(0)
        if a in seen:
            continue
        seen.add(a)
        for b in kids[a]:
            if b not in seen and depth[b] < depth[a] + 1:
                depth[b] = depth[a] + 1
            order.append(b)
    return depth


def draw(labels: list[str], edges: list[tuple[int, int]], title: str, vertical: bool = False) -> Path:
    """Boxes in columns by depth (left -> right), or one top-down chain for a flow (vertical=True)."""
    from PIL import Image, ImageDraw
    n = len(labels)
    depth = _layers(n, edges)
    f, fb = _font(17), _font(19, True)
    wrap = 22
    lines = {i: textwrap.wrap(labels[i], wrap)[:3] or [""] for i in range(n)}
    box_w, line_h, pad, gap_x, gap_y = 270, 24, 14, 90, 22
    hgt = {i: len(lines[i]) * line_h + 2 * pad for i in range(n)}
    if vertical:
        width = box_w + 160
        height = 120 + sum(hgt[i] + 50 for i in range(n))
    else:
        tree_kids: dict[int, list[int]] = defaultdict(list)  # each node under its first parent only
        placed = set()
        for a, b in edges:
            if b not in placed and b != a:
                tree_kids[a].append(b)
                placed.add(b)
        tops = [i for i in range(n) if i not in placed]
        span: dict[int, float] = {}

        def measure(i: int, seen: frozenset) -> float:  # height of a node's whole subtree
            ks = [k for k in tree_kids[i] if k not in seen]
            span[i] = max(hgt[i], sum(measure(k, seen | {i}) for k in ks) + gap_y * max(0, len(ks) - 1))
            return span[i]

        tree_pos: dict[int, tuple[float, float]] = {}

        def place(i: int, x: float, y: float, seen: frozenset) -> None:  # parent centred on its children
            tree_pos[i] = (x, y + (span[i] - hgt[i]) / 2)
            yy = y + (span[i] - (sum(span[k] for k in tree_kids[i] if k not in seen) +
                                 gap_y * max(0, len([k for k in tree_kids[i] if k not in seen]) - 1))) / 2
            for k in tree_kids[i]:
                if k in seen:
                    continue
                place(k, x + box_w + gap_x, yy, seen | {i})
                yy += span[k] + gap_y
        total_h = sum(measure(t, frozenset()) for t in tops) + gap_y * max(0, len(tops) - 1)
        y = 100.0
        for t in tops:
            place(t, 40, y, frozenset())
            y += span[t] + gap_y
        width = 80 + (max(x for x, _ in tree_pos.values()) + box_w)
        height = 140 + total_h
    width, height = max(width, 700), max(height, 400)
    img = Image.new("RGB", (int(width), int(height)), BG)
    d = ImageDraw.Draw(img)
    d.text((40, 28), title[:90], fill=FG, font=_font(28, True))
    if vertical:  # one top-down chain
        pos = {i: ((width - box_w) / 2, 100 + sum(hgt[j] + 50 for j in range(i))) for i in range(n)}
    else:
        pos = tree_pos
    for a, b in edges:  # lines first, boxes on top
        if a not in pos or b not in pos:
            continue
        (ax, ay), (bx, by) = pos[a], pos[b]
        if vertical:
            sx, sy, ex, ey = ax + box_w / 2, ay + hgt[a], bx + box_w / 2, by
            d.line((sx, sy, ex, ey), fill=LINE, width=3)
            d.polygon([(ex - 7, ey - 12), (ex + 7, ey - 12), (ex, ey - 1)], fill=LINE)
        else:
            sx, sy, ex, ey = ax + box_w, ay + hgt[a] / 2, bx, by + hgt[b] / 2
            mx = (sx + ex) / 2
            d.line([(sx, sy), (mx, sy), (mx, ey), (ex, ey)], fill=LINE, width=2, joint="curve")
            d.polygon([(ex - 10, ey - 6), (ex - 10, ey + 6), (ex, ey)], fill=LINE)
    for i, (x, y) in pos.items():
        lvl = 0 if (i == 0 and not vertical) else min(3, depth[i] + (1 if not vertical else 0)) if not vertical else 1
        fill = FILL[lvl] if not vertical else (FILL[0] if i in (0, n - 1) else FILL[1])
        d.rounded_rectangle((x, y, x + box_w, y + hgt[i]), radius=12, fill=fill,
                            outline=(255, 138, 61) if lvl == 1 and not vertical else None, width=1)
        txt = BG if fill == FILL[0] else FG
        for k, ln in enumerate(lines[i]):
            d.text((x + box_w / 2, y + pad + k * line_h + line_h / 2), ln, fill=txt,
                   font=fb if fill == FILL[0] else f, anchor="mm")
    out = config.OUTPUTS_DIR / "diagrams"
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{datetime.now():%Y%m%d-%H%M%S}-{re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:40] or 'diagram'}.png"
    img.save(p, optimize=True)
    return p


# ------------------------------------------------------------------ entry points
def find_readme(folder: Path) -> Path | None:
    for n in README_NAMES:
        if (folder / n).is_file():
            return folder / n
    return None


def project(folder: Path | None) -> str:
    if folder is None or not folder.is_dir():
        return "Which project? Open it in VS Code or say 'diagram of the project at /path'."
    folder = folder.resolve()
    rd = find_readme(folder)
    if rd is None:
        return f"{folder.name} has no README, so I can't draw it (I only read the README, never the whole project)."
    labels, edges = readme_tree(rd.read_text(errors="replace")[:200_000], folder.name)
    if len(labels) < 2:
        return f"{rd.name} has no headings to draw. Add sections (## Install, ## Usage...) and ask again."
    p = draw(labels, edges, f"{labels[0]} — from {rd.name}")
    return f"I drew {folder.name} from its README ({len(labels)} boxes). It's in the workspace: {p.name}"


def flow_from_text(text: str, title: str = "Flow") -> str:
    steps = split_steps(text)
    if len(steps) < 2:
        return "Tell me the steps, e.g. 'flowchart: login, check the password, open the dashboard'."
    labels, edges = flow(steps)
    p = draw(labels, edges, title, vertical=True)
    return f"I drew the flow ({len(labels)} steps). It's in the workspace: {p.name}"


def code(path: Path | None) -> str:
    if path is None or not path.is_file():
        return "Open the Python file in VS Code (or give its path) and ask again."
    if path.suffix != ".py":
        return "I can draw the calls of Python files; for other code describe the steps and I'll draw a flow."
    try:
        labels, edges = call_graph(path.read_text(errors="replace"), path.name)
    except SyntaxError as e:
        return f"{path.name} has a syntax error (line {e.lineno}), so I can't read it."
    if len(labels) < 2:
        return f"{path.name} has no functions to draw."
    p = draw(labels, edges, f"{path.name}: who calls whom")
    return f"I drew {path.name} ({len(labels) - 1} functions). It's in the workspace: {p.name}"
