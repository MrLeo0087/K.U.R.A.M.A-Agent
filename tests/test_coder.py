"""The coding agent (coder/): understand, plan, budget, write, connect, check, fix, undo; the AI is mocked."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from coder import api, budget, connect, engine, models, safety, settings, understand, verify
from coder.run import FileSpec, new


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    from jarvis.core import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setattr("coder.link.vscode_root", lambda: None)
    monkeypatch.setattr("coder.link.open_folder", lambda p: None)
    monkeypatch.setattr("coder.link.to_workspace", lambda t, x: "")
    monkeypatch.setattr("coder.link.tell", lambda t, x: None)
    monkeypatch.setattr("coder.link.steps", lambda j, s: None)


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
    assert understand.question("a rock paper scissors game with a nice ui", "").startswith("Should it be a web app")
    assert understand.question("a todo list in python", "python") == ""
    root, kind = understand.folder("create a snake game in pygame")
    assert kind == "new" and root.name.startswith("snake")


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
    monkeypatch.setattr("coder.link.submit", lambda title, fn: started.append(title) or fn(Ctx()) or 7)
    assert "Planning it" in api.start("create a rock paper scissors game in html css and javascript")
    assert api.pending() is not None
    assert api.start("use tailwind instead").startswith("Changing the plan")
    assert "Change: use tailwind" in api.pending().request
    assert api.no().startswith("Okay, I dropped")
    assert api.pending() is None


def test_unclear_asks_then_continues(monkeypatch):
    fake_ai(monkeypatch)
    monkeypatch.setattr("coder.link.submit", lambda title, fn: 3)
    assert api.start("make a rock paper scissors game with a nice ui").startswith("Should it be")
    assert "Planning it" in api.start("web")


def test_github_starter_checks(monkeypatch, tmp_path):
    import io
    import tarfile

    from coder import github

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
