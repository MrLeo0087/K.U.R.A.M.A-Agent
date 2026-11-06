"""The coding agent (coder/): understand, plan, budget, write, connect, check, fix, undo; the AI is mocked."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from coder.interfaces import api
from coder.llm import budget
from coder.builder import connect
from coder.builder import engine
from coder.llm import models
from coder.core import safety
from coder.core import settings
from coder.builder import understand
from coder.builder import verify
from coder.core.run import FileSpec, new


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    from jarvis.core import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setattr("coder.interfaces.link.vscode_root", lambda: None)
    monkeypatch.setattr("coder.interfaces.link.open_folder", lambda p: None)
    monkeypatch.setattr("coder.interfaces.link.to_workspace", lambda t, x: "")
    monkeypatch.setattr("coder.interfaces.link.tell", lambda t, x: None)
    monkeypatch.setattr("coder.interfaces.link.steps", lambda j, s: None)
    monkeypatch.setattr("coder.runtime.preview.selftest", lambda root, seconds=6: [])  # no headless browser in unit tests
    monkeypatch.setattr("coder.tools.builtin.t_screenshot", lambda run: "no screenshot in unit tests")


class Ctx:
    class job:  # noqa: N801
        id = 1

    def __init__(self):
        self.lines = []

    def progress(self, t):
        self.lines.append(t)

    def check(self):
        pass


def test_understand():
    assert understand.stack_of("rock paper scissors in HTML, CSS and JavaScript") == "web"
    assert understand.stack_of("an industry standard react project") == "react"
    assert understand.stack_of("rock paper scissors game in python with a ui") == "pygame"
    assert understand.question("a rock paper scissors game with a nice ui", "").startswith("How should I make it?")
    assert understand.question("a calculator in pygame", "pygame") == ""  # named: no question
    assert understand.question("add a reset button", "", "add") == ""  # an addition: the project decides
    assert understand.choice("2") == understand.CHOICES["2"] and understand.choice("you choose") == ""
    root, kind, ask = understand.folder("create a snake game in pygame")  # nothing open in VS Code
    assert kind == "new" and root.name.startswith("snake") and ask == ""


PLAN = json.dumps({"name": "RPS", "files": [
    {"path": "./index.html", "purpose": "the page", "uses": ["style.css", "app.js"], "level": "normal"},
    {"path": "style.css", "purpose": "styles", "level": "easy"},
    {"path": "app.js", "purpose": "game logic", "uses": ["index.html"], "level": "hard"},
    {"path": ".gitignore", "purpose": "ignores", "level": "easy"},
    {"path": "../evil.py", "purpose": "outside", "level": "easy"}], "run": "open index.html", "notes": "n",
    "todo": ["sounds"]})
FILES = {
    "index.html": '```html\n<!doctype html><link rel="stylesheet" href="style.css"><p id="result"></p>'
                  '<button class="choice">R</button><script src="app.js"></script>\n```',
    "style.css": "```css\nbody{margin:0}\n```",
    "app.js": "```js\ndocument.getElementById('outcome').textContent='x';\n```",  # wrong id: the fix makes it 'result'
    ".gitignore": "```\nnode_modules\n```",
}


def fake_ai(monkeypatch, fixed_js="document.getElementById('result').textContent='x';"):
    calls = []

    def ask(run, role, system, user, max_tokens):
        calls.append(role)
        run.tokens += 500
        if role == "plan":
            return PLAN
        if role == "fix":
            return f"```js\n{fixed_js}\n```"
        name = user.rsplit("Write the complete file `", 1)[1].split("`", 1)[0]
        return FILES[name]
    monkeypatch.setattr(models, "ask", ask)
    return calls


def test_plan_then_build_then_undo(monkeypatch, tmp_path):
    calls = fake_ai(monkeypatch)
    run = new("rock paper scissors in html css js", tmp_path / "projects" / "rps")
    run.stack = "web"
    engine.plan_job(run)(Ctx())
    assert [f.path for f in run.files] == ["index.html", "style.css", "app.js", ".gitignore"]  # '../evil.py' refused
    assert not run.root.exists()  # nothing is written before the yes
    waiting = api.pending()
    assert waiting is not None and waiting.estimate > 0
    ctx = Ctx()
    engine.build_job(waiting)(ctx)
    assert (run.root / "app.js").read_text().strip() == "document.getElementById('result').textContent='x';"
    assert calls.count("fix") == 1 and "all checks passed" in ctx.lines[-1]
    assert "sounds" in (run.root / "TODO.md").read_text() and (run.root / ".kurama" / "project.md").exists()
    assert api.undo_last().startswith("Undone: the new project")


def test_connect_finds_what_doesnt_fit(tmp_path):
    run = new("x", tmp_path)
    run.files = [FileSpec("main.py", ""), FileSpec("game.py", "")]
    (tmp_path / "index.html").write_text('<link href="missing.css"><script src="https://cdn.x/y.js"></script>')
    (tmp_path / "main.py").write_text("import pygame\nfrom game import Game, decide\n")
    (tmp_path / "game.py").write_text("class Game: ...\n")
    probs = connect.check(run)
    assert any("missing.css" in p for p in probs) and not any("cdn" in p for p in probs)
    assert any("imports decide from game" in p for p in probs)
    assert not any("pygame" in p for p in probs)  # a pip package is never "missing"


def test_verify_python_and_js(tmp_path):
    run = new("x", tmp_path)
    (tmp_path / "a.py").write_text("def f(:\n    pass\n")
    (tmp_path / "b.js").write_text("import x from './x.js';\nconst y = ;\n")
    run.written = ["a.py", "b.js"]
    probs = verify.check(run)
    assert any(p.startswith("a.py") for p in probs) and any(p.startswith("b.js") for p in probs)


def test_secret_guard_and_budget(tmp_path):
    run = new("x", tmp_path)
    p = safety.write(run, "cfg.py", 'API_KEY = "gsk_abcdefghijklmnopqrstuvwxyz123456"\n')
    assert "gsk_" not in p.read_text() and "CHANGE_ME" in p.read_text()
    with pytest.raises(ValueError):
        safety.write(run, "../x.py", "x")
    run.files = [FileSpec(f"f{i}.py", "", [], "hard") for i in range(9)]
    assert budget.too_big(run)  # 9 hard files: over 20k, it asks
    run.files = run.files[:2]
    assert not budget.too_big(run)


def test_a_plan_can_be_changed_and_dropped(monkeypatch, tmp_path):
    fake_ai(monkeypatch)
    started = []
    monkeypatch.setattr("coder.interfaces.link.submit", lambda title, fn: started.append(title) or fn(Ctx()) or 7)
    assert "Planning it" in api.start("create a rock paper scissors game in html css and javascript")
    assert api.pending() is not None
    assert api.start("use tailwind instead").startswith("Changing the plan")
    assert "Change: use tailwind" in api.pending().request
    assert api.no().startswith("Okay, I dropped")
    assert api.pending() is None


def test_kind_question_then_cheapest_choice(monkeypatch):
    fake_ai(monkeypatch)
    monkeypatch.setattr("coder.interfaces.link.submit", lambda title, fn: 3)
    assert api.start("make a simple calculator").startswith("How should I make it?")
    assert "Planning it" in api.start("1")
    q = api._question_key()
    assert not q.exists()


def test_github_starter_checks(monkeypatch, tmp_path):
    import io
    import tarfile

    from coder.builder import github

    def tgz(files: dict[str, str]) -> bytes:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for name, text in files.items():
                data = text.encode()
                info = tarfile.TarInfo("repo-main/" + name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        return buf.getvalue()

    class R:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            pass
    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **k: R(tgz({"index.html": "<p>", "../../evil": "x"})))
    assert github.fetch({"full_name": "a/b"}, tmp_path / "s") == ""
    assert (tmp_path / "s" / "index.html").exists() and not (tmp_path / "evil").exists()
    monkeypatch.setattr(httpx, "get", lambda *a, **k: R(tgz({"requirements.txt": "torch==2.0"})))
    assert "GPU" in github.fetch({"full_name": "a/b"}, tmp_path / "t")
    monkeypatch.setattr(httpx, "get", lambda *a, **k: R(tgz({"c.py": 'token = "ghp_abcdefghijklmnopqrstuvwxyz"'})))
    assert "secret" in github.fetch({"full_name": "a/b"}, tmp_path / "u")


def test_coding_tool_routes_to_coder(monkeypatch):
    import coder
    from jarvis.agents.coding import tools
    monkeypatch.setattr(coder, "start", lambda r: "planned " + r)
    monkeypatch.setattr(coder, "pending", lambda: object())
    monkeypatch.setattr(coder, "yes", lambda: "building")
    monkeypatch.setattr(coder, "undo_last", lambda: "undone")
    assert tools.coding("project", request="a snake game in pygame") == "planned a snake game in pygame"
    assert tools.coding("yes") == "building"
    assert tools.coding("undo", request="undo the project") == "undone"


def test_paths_never_escape(tmp_path):
    run = new("x", tmp_path / "p")
    assert Path(safety.write(run, "src/a.js", "x")).is_relative_to(tmp_path / "p")


# ---------------------------------------------------------------- step 2: tests, review, commit, diffs
def test_make_tests_pass_fixes_the_code(monkeypatch, tmp_path):
    from coder.runtime import testing
    root = tmp_path / "calc"
    (root / "tests").mkdir(parents=True)
    (root / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (root / "tests" / "test_calc.py").write_text("from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    (root / "conftest.py").write_text("")

    def ask(run, role, system, user, max_tokens):
        assert "calc.py" in user and "assert" in user  # only the failure and the blamed file
        return "```python\ndef add(a, b):\n    return a + b\n```"
    monkeypatch.setattr(models, "ask", ask)
    ok, out, run = testing.make_pass(root)
    assert ok and "return a + b" in (root / "calc.py").read_text(), out


def test_write_tests(monkeypatch, tmp_path):
    from coder.runtime import testing
    root = tmp_path / "p"
    root.mkdir()
    (root / "util.py").write_text("def double(x):\n    return x * 2\n")
    monkeypatch.setattr(models, "ask", lambda run, role, s, u, m:
                        "```python\nfrom util import double\n\ndef test_double():\n    assert double(2) == 4\n```")
    run, written = testing.write(root)
    assert written == ["tests/test_util.py"] and testing.run_tests(root)[0]


def test_reject_one_file_and_commit(monkeypatch, tmp_path):
    import subprocess

    from coder.runtime import review
    fake_ai(monkeypatch)
    run = new("rps", tmp_path / "projects" / "rps")
    run.stack = "web"
    engine.plan_job(run)(Ctx())
    engine.build_job(api.pending())(Ctx())
    assert review.reject("I don't want style.css") .endswith("went to the trash.")
    root = run.root
    subprocess.run(["git", "init", "-q"], cwd=root)
    subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"], cwd=root)
    monkeypatch.setattr(models, "ask", lambda run, role, s, u, m: "Add the game\n\n- page, logic")
    monkeypatch.setattr("coder.interfaces.link.vscode_root", lambda: root)
    (root / "x.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=root)
    assert api.commit_prepare().startswith("Commit message:\nAdd the game")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "a@b")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "a@b")
    assert api.commit_waiting() and api.commit_yes() == "Committed: Add the game"


# ---------------------------------------------------------------- step 3: the page, run for real
def test_page_errors_become_problems(tmp_path):
    from coder.runtime import preview
    (tmp_path / "app.js").write_text("x")
    errs = [{"kind": "missing", "msg": "could not load http://127.0.0.1:5/nope.css"},
            {"kind": "missing", "msg": "could not load /favicon.ico"},
            {"kind": "error", "msg": "Uncaught TypeError: x is null", "src": "http://127.0.0.1:5/app.js", "line": 2}]
    assert preview.problems_of(errs, tmp_path) == ["index.html: asks for nope.css, which is missing",
                                                   "app.js:2: browser error: Uncaught TypeError: x is null"]


def test_selftest_clicks_through_a_real_page(tmp_path):
    import importlib

    from coder.runtime import preview
    preview = importlib.reload(preview)  # the real one (the fixture replaced selftest)
    if preview.browser() is None:
        pytest.skip("no Chromium-based browser here")
    (tmp_path / "index.html").write_text('<button id="go">Go</button><script src="app.js"></script>')
    (tmp_path / "app.js").write_text("document.getElementById('go').onclick = () => { null.x = 1; };")
    probs = preview.selftest(tmp_path)
    assert probs and probs[0].startswith("app.js:1: browser error")


def test_look_at_the_page(monkeypatch, tmp_path):
    from coder.runtime import preview
    from jarvis.core import llm

    class R:
        text = "- the title is cut\n- add spacing"
    monkeypatch.setattr(preview, "screenshot", lambda root: b"png")
    monkeypatch.setattr(llm, "chat", lambda msgs, **k: R())
    assert preview.look(tmp_path).startswith("- the title is cut")


def test_files_are_written_after_what_they_use():
    from coder.builder import planner
    fs = [FileSpec("app.js", "", ["constants.js", "utils.js"]), FileSpec("index.html", "", ["app.js"]),
          FileSpec("constants.js", ""), FileSpec("utils.js", "", ["constants.js"])]
    assert [f.path for f in planner.order(fs)] == ["constants.js", "utils.js", "app.js", "index.html"]


# ---------------------------------------------------------------- step 4: queue, continue, hand-off, tokens
def test_queue_runs_after_the_build(monkeypatch):
    monkeypatch.setattr(api, "building", lambda: True)
    assert api.start("after that, add a dark mode").startswith("Queued (#1)")
    assert api.queued() == ["add a dark mode"]
    planned = []
    monkeypatch.setattr(api, "start", lambda r: planned.append(r) or "planning")
    assert api.next_queued() == "planning" and planned == ["add a dark mode"] and api.queued() == []


def test_continue_the_project_and_tick(monkeypatch, tmp_path):
    from coder.memory import card as memory
    root = tmp_path / "p"
    root.mkdir()
    (root / "TODO.md").write_text("# TODO\n\n- [x] old\n- [ ] add sounds\n")
    monkeypatch.setattr("coder.interfaces.link.vscode_root", lambda: root)
    got = []
    monkeypatch.setattr("coder.interfaces.link.submit", lambda title, fn: got.append(title) or 5)
    assert "'add sounds'" in api.continue_project() and got == ["Plan: add sounds"]
    memory.tick(root, "add sounds")
    assert "- [x] add sounds" in (root / "TODO.md").read_text() and memory.todo(root) == []


def test_handoff_and_tokens(monkeypatch, tmp_path):
    fake_ai(monkeypatch)
    run = new("big app", tmp_path / "projects" / "big")
    run.stack = "web"
    engine.plan_job(run)(Ctx())
    sent = {}
    monkeypatch.setattr("coder.interfaces.link.claude_code", lambda prompt, folder: sent.update(p=prompt, f=folder) or "Claude Code is building it")
    assert api.handoff() == "Claude Code is building it" and "Follow this plan" in sent["p"] and api.pending() is None
    engine.build_job(new("x", tmp_path / "projects" / "x"))  # (nothing built yet: the report says so)
    assert api.tokens_report().startswith("The coding agent hasn't built anything")


# ---------------------------------------------------------------- memory: the run's, the project's, learning one
def test_run_memory_readme_and_card(monkeypatch, tmp_path):
    from coder.memory import card as memory
    from coder.builder import writer
    fake_ai(monkeypatch)
    run = new("rps", tmp_path / "projects" / "rps")
    engine.plan_job(run)(Ctx())
    run = api.pending()
    seen = []
    real = models.ask

    def spy(r, role, system, user, max_tokens):
        seen.append(user)
        return real(r, role, system, user, max_tokens)
    monkeypatch.setattr(models, "ask", spy)
    engine.build_job(run)(Ctx())
    later = next(u for u in seen if "Write the complete file `app.js`" in u)
    assert "Written so far in this run" in later and "#result" in later  # the page's ids, without the whole page
    card = memory.path(run.root).read_text()
    assert "## Overview" in card and "## Map" in card and "index.html" in card
    assert (run.root / "README.md").read_text().startswith("# RPS")  # every new project gets a README
    assert writer.run_memory(run, run.files[0])  # (and the card is what the next request reads)


def test_learning_a_project_it_didnt_build(monkeypatch, tmp_path):
    from coder.memory import card as memory
    from coder.memory import onboard
    root = tmp_path / "theirs"
    (root / "backend").mkdir(parents=True)
    (root / "backend" / "api.py").write_text("from fastapi import FastAPI\napp = FastAPI()\ndef health():\n    return 1\n")
    (root / "requirements.txt").write_text("fastapi\nuvicorn\n")
    (root / "README.md").write_text("# Theirs\nA small API.")
    got = {}

    def ask(run, role, system, user, max_tokens):
        got.update(role=role, user=user)
        run.tokens += 3000
        return "# Theirs\n## Overview\nA small health API.\n## How to run\n```bash\nuvicorn backend.api:app\n```\n## Key files\n- `backend/api.py`: the app"
    monkeypatch.setattr(models, "ask", ask)
    assert not onboard.known(root)
    line = onboard.learn(root)
    assert got["role"] == "review" and "def health()" in got["user"] and "fastapi" in got["user"]  # facts, not code
    card = memory.path(root).read_text()
    assert "Stack: FastAPI" in card and "Run: `uvicorn backend.api:app`" in card and onboard.known(root)
    assert line.startswith("I learned theirs (FastAPI): A small health API.")



def test_the_project_open_in_vs_code_is_the_one_worked_on(monkeypatch, tmp_path):
    """11-06: with a project open in VS Code, 'make a rock paper scissors game' went to a new folder."""
    small = tmp_path / "mygame"
    small.mkdir()
    (small / "main.py").write_text("print(1)\n")
    monkeypatch.setattr("coder.interfaces.link.vscode_root", lambda: small)
    assert understand.folder("make a rock paper scissors game") == (small, "add", "")
    assert understand.folder("add a score board") == (small, "add", "")
    root, kind, _ = understand.folder("make a snake game in a new folder")
    assert kind == "new" and root.parent != small  # asked for elsewhere
    big = tmp_path / "big"
    big.mkdir()
    for i in range(20):
        (big / f"m{i}.py").write_text("x = 1\n")
    monkeypatch.setattr("coder.interfaces.link.vscode_root", lambda: big)
    root, kind, ask = understand.folder("make a rock paper scissors game")
    assert ask.startswith("Should I build it inside big")  # a big, maybe unrelated project: it asks
    assert understand.folder("make a rock paper scissors game", "here") == (big, "add", "")
    assert understand.folder("make a rock paper scissors game", "new")[1] == "new"
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr("coder.interfaces.link.vscode_root", lambda: empty)
    assert understand.folder("make a rock paper scissors game") == (empty, "new", "")


def test_where_question_then_answer(monkeypatch, tmp_path):
    big = tmp_path / "big"
    big.mkdir()
    for i in range(20):
        (big / f"m{i}.py").write_text("x = 1\n")
    monkeypatch.setattr("coder.interfaces.link.vscode_root", lambda: big)
    started = []
    monkeypatch.setattr("coder.interfaces.link.submit", lambda title, fn: started.append(title) or 9)
    assert api.start("make a rock paper scissors game").startswith("Should I build it inside big")
    assert api.start("here").startswith("On it in big")  # a change in the open project: the agent loop


# ---------------------------------------------------------------- 11-06 traces: a game passed every check, then crashed
def test_cross_file_calls_and_attributes(tmp_path):
    run = new("x", tmp_path)
    (tmp_path / "constants.py").write_text("WIDTH = 800\n")
    (tmp_path / "ui.py").write_text("def create_choice_buttons(surface, y):\n    return []\nclass Button:\n"
                                    "    def __init__(self, rect, text):\n        pass\n")
    (tmp_path / "main.py").write_text("import constants as C\nfrom ui import create_choice_buttons, Button\n"
                                      "print(C.WIDTH, C.FONT_NAME)\ncreate_choice_buttons(None, 3, x_center=10)\n"
                                      "Button((0, 0))\ncreate_choice_buttons(None, 3)\n")
    probs = connect._py_names(run)
    assert any("uses C.FONT_NAME" in p for p in probs)
    assert any("no parameter 'x_center'" in p for p in probs)
    assert any("calls Button with 1 arguments, but it needs 2" in p for p in probs)
    assert len(probs) == 3  # the correct call is fine


def test_smoke_run_catches_a_crash_and_a_missing_package(tmp_path):
    from coder.runtime import runcheck
    run = new("x", tmp_path)
    (tmp_path / "main.py").write_text("import game\ngame.start()\n")
    (tmp_path / "game.py").write_text("def start():\n    raise ValueError('bad size')\n")
    probs, needs = runcheck.smoke(run)
    assert probs and probs[0].startswith("game.py:2: crashes when it starts") and "bad size" in probs[0]
    (tmp_path / "game.py").write_text("import pygame_not_installed_x\ndef start():\n    pass\n")
    assert runcheck.smoke(run) == ([], ["pygame_not_installed_x"])
    (tmp_path / "game.py").write_text("def start():\n    input('name? ')\n")
    assert runcheck.smoke(run) == ([], [])  # waits for typing: not a bug
    (tmp_path / "game.py").write_text("import time\ndef start():\n    time.sleep(30)\n")
    assert runcheck.smoke(run) == ([], [])  # still running: it starts


def test_improve_without_a_web_page_is_a_change(monkeypatch, tmp_path):
    """11-06: 'make the UI better' of a Tkinter calculator -> "I couldn't take a picture of the page"."""
    import coder
    from jarvis.agents.coding import tools
    (tmp_path / "calculator.py").write_text("import tkinter\n")
    monkeypatch.setattr("coder.interfaces.link.vscode_root", lambda: tmp_path)
    monkeypatch.setattr(coder, "start", lambda r: "planned: " + r)
    assert tools.coding("look", request="make the UI more colourful") == "planned: make the UI more colourful"


def test_a_cut_reply_never_leaves_a_fence_in_the_code():
    from coder.builder import writer
    assert writer.code_of("```javascript\nconst a = 1;\n") == "const a = 1;\n"
    assert writer.code_of("```js\nconst b = `x${1}`;\n```") == "const b = `x${1}`;\n"
