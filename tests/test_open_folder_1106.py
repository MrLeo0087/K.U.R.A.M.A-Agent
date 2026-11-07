"""11-06 regressions: 'open that new_folder folder in vs code' opened Downloads; 'open 4th folder in vs code' after
a listing did nothing; the listing went only to the workspace."""
from __future__ import annotations

import pytest

from jarvis.core import config, fastpath, focus, semantic


@pytest.fixture
def downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    monkeypatch.setattr(config, "SEMANTIC_ROUTER", True)
    semantic._tables.clear()
    if not semantic.ensure_ready(30):
        pytest.skip("meaning model not available")
    d = tmp_path / "Downloads"
    for n in ("Colab", "hello", "kurama_graph_test", "new_folder"):
        (d / n).mkdir(parents=True)
    (d / "notes.txt").write_text("x")
    focus.set_path(str(d))
    yield d
    semantic._tables.clear()


def test_a_named_folder_wins_over_this_folder(downloads):
    it = fastpath.match("open that new_folder folder in vs code")  # (found in the folder in use)
    assert it is not None and it.args["path"] == str(downloads / "new_folder")


def test_numbered_folders_and_open_by_number(downloads):
    from jarvis.tools.interactive.list_folder import list_folder
    out = list_folder(str(downloads))
    assert "4. 📁 new_folder" in out and "5. notes.txt" in out
    for said in ("open 4th folder in vs code", "open 4 in vs code", "open the fourth folder in vs code"):
        it = fastpath.match(said)
        assert it is not None and it.args["path"] == str(downloads / "new_folder"), said
    shown = fastpath._render_listdir(fastpath.Intent("listdir", "list_folder", "filesearch", {}), out)
    assert "4. 📁 new_folder" in shown and "workspace" not in shown  # the list itself, in the chat


def test_go_to_vs_code_focuses_the_app_not_a_folder(monkeypatch):
    """'Go to the VS Code' -> open_path(path='vscode'): the VS Code window, never the vscode_ext folder (11-07)."""
    from jarvis.core import uiagent
    from jarvis.tools.general import open_path as op
    seen = []
    monkeypatch.setattr(uiagent, "focus", lambda app: seen.append(app) or True)
    monkeypatch.setattr(op, "_find", lambda p: (_ for _ in ()).throw(AssertionError("searched a folder")))
    fn = getattr(op.open_path, "func", op.open_path)
    assert fn(path="vscode", app="vscode") == "Switched to VS Code."
    assert seen == ["vs code"]
