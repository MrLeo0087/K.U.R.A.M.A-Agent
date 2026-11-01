"""Keys and passwords never reach a prompt or a reply: a private file open in VS Code (.env) or a highlight that holds
a key is invisible to KURAMA's context, and a bare 'yes' is never 'use the highlight' (11-01: it printed the Groq key)."""
from pathlib import Path

import pytest

from jarvis.core import config, context, fastpath, rewrite
from jarvis.tools.interactive import _secrets

KEY = "GROQ_API_KEY=gsk_" + "Ab3dE6gH9jK2mN5pQ8sT1vW4yZ7bC0eF3hJ6kL9n"


@pytest.mark.parametrize("name,private", [(".env", True), (".env.local", True), ("prod.env", True), ("id_rsa", True),
                                          ("server.pem", True), ("credentials.json", True), ("notes.md", False),
                                          ("environment.py", False), ("main.py", False)])
def test_private_files(name, private):
    assert _secrets.private_file(f"/home/leo/project/{name}") is private


@pytest.mark.parametrize("text,private", [(KEY, True), ("export TOKEN='x9Kd02LmQpZ7rT5vB8nW'", True),
                                          ("def add(a, b):\n    return a + b", False), ("hello world", False)])
def test_private_text(text, private):
    assert _secrets.private(text) is private


def _editor(monkeypatch, file, selection):
    from jarvis.core import editor
    monkeypatch.setattr(config, "CONTEXT", True)
    monkeypatch.setattr(context, "_cache", (0.0, {}))
    monkeypatch.setattr(editor, "target", lambda *a, **k: {"file": file, "selection": selection})


def test_an_open_env_file_is_never_context(monkeypatch, tmp_path):
    _editor(monkeypatch, str(tmp_path / ".env"), "TELEGRAM_CHAT_ID=42")
    s = context.snapshot()
    assert s["file"] is None and s["selection"] == "" and s.get("private")
    assert ".env" not in context.line() and "42" not in context.line()


def test_a_key_highlighted_in_a_normal_file_is_never_context(monkeypatch, tmp_path):
    _editor(monkeypatch, str(tmp_path / "settings.py"), KEY)
    assert context.snapshot()["selection"] == "" and "gsk_" not in context.line()


def test_peek_and_grab_refuse_a_private_highlight(monkeypatch):
    monkeypatch.setattr(rewrite, "_peek", lambda: KEY)
    monkeypatch.setattr(rewrite, "_editor_file", lambda: "")
    assert rewrite.peek() == ""
    monkeypatch.setattr(rewrite, "_grab", lambda: rewrite.Grab(KEY, 1, True, False, "settings.py - VS Code"))
    assert rewrite.grab() == rewrite.PRIVATE_SAID
    monkeypatch.setattr(rewrite, "_grab", lambda: rewrite.Grab("x = 1", 1, True, False, ".env - VS Code",
                                                              editor={"file": "/p/.env"}))
    assert rewrite.grab() == rewrite.PRIVATE_SAID
    monkeypatch.setattr(rewrite, "_grab", lambda: rewrite.Grab("x = 1", 1, True, False, "main.py - VS Code",
                                                              editor={"file": "/p/main.py"}))
    assert rewrite.grab().text == "x = 1"


@pytest.mark.parametrize("reply", ["yes", "yeah do it", "ok go ahead", "no thanks"])
def test_a_bare_yes_is_never_a_selection_or_meaning_action(monkeypatch, reply):
    from jarvis.core import semantic
    monkeypatch.setattr(config, "CONTEXT", True)
    monkeypatch.setattr(rewrite, "peek", lambda: "some highlighted text")
    monkeypatch.setattr(semantic, "ready", lambda: True)
    monkeypatch.setattr(semantic, "scores", lambda t: [("clipboard", 0.9)])
    monkeypatch.setattr(semantic, "best_of", lambda t, n, table: (next(iter(table)), 0.95))
    assert fastpath.selection_intent(reply) is None
    assert fastpath.match(reply) is None
