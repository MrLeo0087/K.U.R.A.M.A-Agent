"""Plan 11-09 phase 8 (coding agent, few tokens): in coding mode a change or a bug told in plain words goes to the
agent at 0 tokens (it went through the AI first, ~5k tokens to pick the tool); a described bug without a crash is
a task, not "which file?"; a whole new app never lands in an unrelated open folder without asking; a malformed
tool call is retried on the same model instead of resending the prompt to every fallback model."""
import pytest

from jarvis import agents
from jarvis.core import config, fastpath, llm, semantic


@pytest.fixture
def coding(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    monkeypatch.setattr(config, "SEMANTIC_ROUTER", True)
    if not semantic.ensure_ready(30):
        pytest.skip("meaning model not available")
    monkeypatch.setattr(agents, "current", lambda: "coding")
    semantic._tables.clear()
    yield
    semantic._tables.clear()


@pytest.mark.parametrize("text", ["when i click on any product it stop scroll and stuck .. solve this",
                                  "the sign are not show only number are show and also when i want 9+8 it fails",
                                  "make the Reserve a Table button text white so it is readable",
                                  "add a dark mode toggle to the header"])
def test_coding_mode_takes_changes_and_bug_reports_at_zero_tokens(coding, text):
    it = fastpath.match(text)
    assert it is not None and it.tool == "coding" and it.args["action"] == "project", text


@pytest.mark.parametrize("text,tool", [("volume up", "volume"), ("play some music", "music"),
                                       ("open youtube", "open_url")])
def test_core_commands_still_win_in_coding_mode(coding, text, tool):
    assert fastpath.match(text).tool == tool


def test_questions_and_junk_are_not_builds(coding):
    for text in ("WTF", "what is a closure in python"):
        it = fastpath.match(text)
        assert it is None or it.tool != "coding", text


def test_a_new_app_in_an_open_project_asks_where(tmp_path, monkeypatch):
    from coder.builder import understand
    from coder.interfaces import link
    for name in ("extension.js", "package.json", "README.md", "coder.js"):  # vscode_ext: a real, unrelated project
        (tmp_path / name).write_text("x")
    monkeypatch.setattr(link, "vscode_root", lambda: tmp_path)
    root, kind, ask = understand.folder("create whole e commerce website")
    assert ask and "new folder" in ask
    assert understand.folder("add a login page to this project")[2] == ""


def test_a_malformed_tool_call_is_retried_on_the_same_model(monkeypatch):
    calls = []

    class Err(Exception):
        status_code = 400

    class Bound:
        def __init__(self, model):
            self.model = model

        def invoke(self, msgs, config=None):
            calls.append(self.model)
            if len(calls) == 1:
                raise Err("Error code: 400 - Tool call validation failed: attempted to call tool 'run'")
            return "msg"
    monkeypatch.setattr(llm, "_bound", lambda model, *a, **k: Bound(model))
    monkeypatch.setattr(llm, "_acquire", lambda model, rate: None)
    monkeypatch.setattr(llm, "_settle", lambda *a: None)
    monkeypatch.setattr(llm, "_status", lambda e: 400)
    monkeypatch.setattr(llm, "_reply", lambda msg, model: model)
    monkeypatch.setattr(llm, "_plan", lambda models: [(0, m, 0) for m in models])
    out = llm._complete(["a", "b"], [], [object()], "t", 10, None, {}, ("i", 1, 1))
    assert out == "a" and calls == ["a", "a"]  # the same model again, not the next one
