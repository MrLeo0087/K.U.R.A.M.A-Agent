"""Live evaluation: real tasks (like the owner's) on small sample projects, each checked for its RESULT and its
TOKENS. Costs ~25k tokens in all; run after a big change:  python -m coder.evals.live
Results also go to data/coder/evals.json (one line per run), so the numbers can be compared over time.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

WEB = {
    "index.html": '<!doctype html><html><head><link rel="stylesheet" href="style.css"></head><body><div class="wrap">'
                  '<div class="score">You <b id="you">0</b> - <b id="cpu">0</b> CPU</div><div class="choices">'
                  '<button class="choice" data-c="rock">Rock</button><button class="choice" data-c="paper">Paper</button>'
                  '</div><p id="result">Pick one</p></div><script src="app.js"></script></body></html>\n',
    "style.css": "body { font-family: sans-serif; }\n.choice { margin: 4px; }\n#result { color: black; }\n",
    "app.js": 'document.querySelectorAll(".choice").forEach((b) => b.addEventListener("click", () => {\n'
              '  document.getElementById("result").textContent = "You picked " + b.dataset.c;\n}));\n',
}
PY = {"main.py": 'from stats import mean\n\nprint("mean:", mean([3, 5, 8]))\n',
      "stats.py": "def mean(xs):\n    return sum(xs) / len(x)\n"}

# 11-10: the owner's own failure classes from a week of traces (a bug told in plain words, a web page that gets stuck,
# a feature added, a pasted traceback, a rename across files)
SHOP = {
    "index.html": '<!doctype html><html><head><link rel="stylesheet" href="shop.css"></head><body>'
                  '<div class="grid"><div class="product" data-id="1">Shoes</div><div class="product" data-id="2">Bag'
                  '</div></div><div id="modal" hidden><p id="detail"></p><button id="close">Close</button></div>'
                  '<div style="height:2000px"></div><script src="shop.js"></script></body></html>\n',
    "shop.css": ".product { padding: 20px; cursor: pointer; }\n#modal { position: fixed; top: 20%; }\n",
    "shop.js": 'document.querySelectorAll(".product").forEach((p) => p.addEventListener("click", () => {\n'
               '  document.getElementById("detail").textContent = p.textContent;\n'
               '  document.getElementById("modal").hidden = false;\n'
               '  document.body.style.overflow = "hidden";\n}));\n'
               'document.getElementById("close").addEventListener("click", () => {\n'
               '  document.getElementById("modal").hidden = true;\n});\n',
}
CALC = {"calc.py": 'display = ""\n\n\ndef press(key):\n    global display\n    if key == "=":\n'
                   '        display = str(eval(display)) if display else ""\n        return display\n'
                   '    if key.isdigit():\n        display += key\n    return display\n',
        "settings.py": 'SETTINGS = {"name": "calc"}\n',
        "app.py": 'from settings import SETTINGS\n\nprint("Welcome to", SETTINGS["title"])\n'}


def _runs(root: Path, code: str, want: str) -> bool:
    import subprocess
    r = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, timeout=20)
    return r.returncode == 0 and want in r.stdout


TRACE = ('I get this error when I run app.py, fix it:\nTraceback (most recent call last):\n  File "app.py", line 3, in '
         '<module>\n    print("Welcome to", SETTINGS["title"])\nKeyError: \'title\'')

# (name, sample, the request, new project?, a check of the result, the token limit)
CASES = [
    ("css change", "web", "make the choice buttons grey with rounded corners", False,
     lambda root: re.search(r"\.choice[^}]*border-radius", (root / "style.css").read_text()) is not None, 8000),
    ("follow-up", "web", "make them bigger too", False,
     lambda root: re.search(r"\.choice[^}]*(?:font-size|padding)", (root / "style.css").read_text()) is not None, 8000),
    ("run + fix", "py", "run this project and tell me what it prints. If it crashes, fix it and run it again", False,
     lambda root: "len(xs)" in (root / "stats.py").read_text(), 11000),
    ("new tiny app", "none", "a simple calculator as a Python program in the terminal", True,
     lambda root: any(p.suffix == ".py" for p in root.rglob("*.py")), 5000),
    ("stuck page", "shop", "when i click on any product the page stops scrolling and gets stuck .. solve this", False,
     lambda root: re.search(r"overflow\s*=\s*[\"'](?:auto|visible|)[\"']|removeProperty\(\s*[\"']overflow",
                            (root / "shop.js").read_text()) is not None, 8000),
    ("bug in words", "calc", "the + and - signs are not shown, only numbers show, and when i want 9+8 it doesn't work. "
     "fix it", False, lambda root: _runs(root, "import calc\nfor k in '9+8': calc.press(k)\nprint(calc.press('='))",
                                         "17"), 8000),
    ("pasted traceback", "calc", TRACE, False, lambda root: _runs(root, "import runpy; runpy.run_path('app.py')",
                                                               "Welcome to"), 8000),
    ("add a feature", "web", "add a reset button that sets both scores back to 0", False,
     lambda root: re.search(r"reset", (root / "index.html").read_text(), re.I) is not None
     and re.search(r"reset", (root / "app.js").read_text(), re.I) is not None, 8000),
    ("rename", "py", "rename the function mean to average in all files", False,
     lambda root: "def average" in (root / "stats.py").read_text()
     and _runs(root, "import runpy; runpy.run_path('main.py')", "mean:"), 8000),
]


class Quiet:
    class job:  # noqa: N801
        id = 0

    def progress(self, text: str) -> None:
        pass

    def check(self) -> None:
        pass


def run_case(base: Path, name: str, sample: str, request: str, new_project: bool) -> tuple[Path, int]:
    from coder.core.run import new
    from coder.interfaces import link
    link.QUIET = True
    root = base / sample
    if new_project:
        from coder.builder import engine, understand
        root = base / "new"
        run = new(request, root / understand.slug(request))
        run.stack, run.kind = understand.stack_of(request), "new"
        engine.plan_job(run)(Quiet())  # (the plan fills `run` itself; the saved "waiting plan" copy is dropped)
        from coder.interfaces import api
        api.drop()
        engine.build_job(run)(Quiet())
        return run.root, run.tokens
    from coder.agent import loop
    run = new(request, root)
    run.kind = "add"
    loop.task_job(run, request)(Quiet())
    return root, run.tokens


def main() -> int:
    try:
        from jarvis.core import store
        store.init()
    except Exception:  # noqa: BLE001
        pass
    base = Path(tempfile.mkdtemp(prefix="coder-evals-"))
    for name, files in (("web", WEB), ("py", PY), ("shop", SHOP), ("calc", CALC)):
        for rel, text in files.items():
            (base / name / rel).parent.mkdir(parents=True, exist_ok=True)
            (base / name / rel).write_text(text, encoding="utf-8")
    rows, ok_all = [], True
    only = [a.lower() for a in sys.argv[1:]]  # 'python -m coder.evals.live traceback' = only the cases named so
    for name, sample, request, new_project, check, limit in CASES:
        if only and not any(o in name for o in only):
            continue
        t0 = time.time()
        try:
            root, tokens = run_case(base, name, sample, request, new_project)
            passed = bool(check(root))
        except Exception as e:  # noqa: BLE001 - a crash is a failed case, the rest still run
            root, tokens, passed = base, 0, False
            print(f"  {name}: crashed: {e}", file=sys.stderr)
        within = tokens <= limit
        ok_all &= passed and within
        rows.append({"case": name, "result": "ok" if passed else "WRONG", "tokens": tokens, "limit": limit,
                     "within": within, "seconds": round(time.time() - t0)})
        print(f"{'✅' if passed and within else '❌'} {name:14} result {'ok' if passed else 'WRONG':5} "
              f"tokens {tokens / 1000:5.1f}k / {limit / 1000:.0f}k  {time.time() - t0:4.0f} s", flush=True)
    from coder.core import settings
    with (settings.data_dir() / "evals.json").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M"), "rows": rows}) + "\n")
    shutil.rmtree(base, ignore_errors=True)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
