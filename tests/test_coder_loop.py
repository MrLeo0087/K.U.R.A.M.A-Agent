"""The coding agent's loop (coder/loop.py) and its tools (coder/tools.py); the AI is mocked."""
from __future__ import annotations

import json

import pytest

from coder.interfaces import link
from coder.agent import loop
from coder.tools import builtin as tools
from coder.core.run import new


@pytest.fixture(autouse=True)
def quiet(tmp_path, monkeypatch):
    from jarvis.core import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    for name in ("steps", "to_workspace", "to_workspace_file", "tell_result", "tell"):
        monkeypatch.setattr(link, name, lambda *a, **k: None)


def test_tools(tmp_path):
    (tmp_path / "a.css").write_text(".btn { color: red; }\n.x { color: red; }\n")
    run = new("x", tmp_path)
    assert "a.css:1:" in tools.t_grep(run, "btn", "a.css")  # a file path works (11-06: it found nothing)
    assert "2 times" in tools.t_edit(run, "a.css", "color: red;", "color: grey;")
    assert tools.t_edit(run, "a.css", ".btn { color: red; }", ".btn { color: grey; }") == "edited a.css"
    assert "grey" in (tmp_path / "a.css").read_text()
    assert tools.t_run(run, "pip install requests").startswith("NEEDS_YES")
    assert tools.t_run(run, "sudo rm -rf /").startswith("refused")
    assert "exit: 0" in tools.t_run(run, "echo hi")
    with pytest.raises(ValueError):
        tools._path(run, "../../etc/passwd")
    assert "much shorter" in tools.t_write(run, "a.css", "x")  # never drops code by rewriting


class R:
    def __init__(self, calls):
        self.tool_calls, self.text, self.prompt_tokens, self.completion_tokens = calls, "", 100, 20


def test_loop_edits_then_the_code_checks_it(monkeypatch, tmp_path):
    (tmp_path / "style.css").write_text(".choice { margin: 4px; }\n")
    (tmp_path / "index.html").write_text('<button class="choice">Rock</button><link rel="stylesheet" href="style.css">')
    replies = iter([
        R([{"name": "edit", "arguments": json.dumps({"path": "style.css", "old": ".choice { margin: 4px; }",
                                                       "new": ".choice { margin: 4px; background: grey; }"})}]),
        R([{"name": "done", "arguments": json.dumps({"summary": "The buttons are grey."})}]),
    ])
    from jarvis.core import llm
    monkeypatch.setattr(llm, "chat", lambda *a, **k: next(replies))
    monkeypatch.setattr("coder.llm.models.ask", lambda *a, **k: '{"plan": ["edit style.css"], "check": "grey"}')
    monkeypatch.setattr(tools, "t_run_project", lambda run, seconds=8: "the page opens; no errors")
    monkeypatch.setattr(tools, "t_screenshot", lambda run: "screenshot saved: 01.png")
    monkeypatch.setattr(tools, "t_look", lambda run, q, shot="": "1. grey: done\nALL DONE")

    class Ctx:
        class job:  # noqa: N801
            id = 1

        def progress(self, t):
            pass

        def check(self):
            pass
    run = new("x", tmp_path)
    run.kind = "add"
    loop.task_job(run, "make the buttons grey")(Ctx())
    assert "background: grey" in (tmp_path / "style.css").read_text()
    from coder.core import session
    assert "make the buttons grey -> The buttons are grey." in session.recap(tmp_path)  # follow-ups know "it"
    assert "Recent tasks in this project" in loop.context(run)
    assert [e["kind"] for e in session.last_events(tmp_path)][:2] == ["task_start", "plan"]
    from coder.core import safety
    assert safety.undo(run.dir).startswith("Undone")  # every change can be put back


def test_a_small_project_is_given_whole(tmp_path):
    (tmp_path / "app.js").write_text("console.log(1)\n")
    got = loop.small_project(new("x", tmp_path))
    assert "app.js" in got and "console.log" in got["app.js"]


def test_session_unfinished_and_continue(tmp_path, monkeypatch):
    from coder.core import session
    from coder.interfaces import api
    session.task_start(tmp_path, "t1", "add a dark mode")  # then KURAMA restarted: still 'running'
    assert session.unfinished(tmp_path)["goal"] == "add a dark mode"
    monkeypatch.setattr(api, "project_root", lambda: tmp_path)
    got = {}
    monkeypatch.setattr(api, "task", lambda goal, root=None, notes=None: got.update(goal=goal, notes=notes) or "on it")
    assert api.continue_project() == "on it" and got["goal"] == "add a dark mode"
    session.task_end(tmp_path, "t1", "done", "dark mode added", ["style.css"], ["1. edit"], 4000)
    assert session.unfinished(tmp_path) is None and session.tokens(tmp_path) == 4000
    assert "dark mode added" in api.what_happened()


def test_a_short_followup_names_the_last_task(tmp_path):
    from coder.core import session
    session.task_start(tmp_path, "a", "make the result text green")
    session.task_end(tmp_path, "a", "done", "The result is green.", ["style.css"], [], 100)
    assert "make the result text green" in loop.resolve_followup(tmp_path, "make it bigger too")
    assert loop.resolve_followup(tmp_path, "add a login page with a form") == "add a login page with a form"
