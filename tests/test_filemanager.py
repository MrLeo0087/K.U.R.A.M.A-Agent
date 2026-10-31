"""The Files app as context: 'this folder / these files' when Files is the latest app (no real desktop)."""
from pathlib import Path

from jarvis.core import context, filemanager, focus


def fake(monkeypatch, top, folder, selected=()):
    monkeypatch.setattr(filemanager, "state", lambda: {"top": top, "folder": folder, "selected": list(selected)})


def test_selected_item_wins_then_the_open_folder(monkeypatch, tmp_path):
    proj = tmp_path / "myproj"
    proj.mkdir()
    fake(monkeypatch, "files", str(tmp_path), [str(proj)])
    assert focus.refer("this folder") == proj
    assert "Selected there" in filemanager.line() and str(proj) in filemanager.line()
    fake(monkeypatch, "files", str(tmp_path))
    assert focus.refer("here") == tmp_path
    assert "'this folder/here' means it" in context.line()


def test_not_the_latest_app_means_not_used(monkeypatch, tmp_path):
    fake(monkeypatch, "vscode", str(tmp_path), [str(tmp_path)])
    assert filemanager.current() is None and filemanager.line() == ""


def test_helper_script_runs_and_never_raises():
    import json
    import subprocess
    from jarvis.core import config
    p = subprocess.run(["/usr/bin/python3", str(config.ROOT / "scripts" / "kurama_fm.py")], capture_output=True,
                       text=True, timeout=10)
    d = json.loads(p.stdout.strip().splitlines()[-1])
    assert set(d) >= {"top", "folder", "selected"}


def test_send_this_folder_shortcut_uses_the_files_selection(monkeypatch, tmp_path):
    from jarvis.core import fastpath
    sel = tmp_path / "newone"
    sel.mkdir()
    focus.set_path(str(tmp_path))  # KURAMA remembered the parent (the old shortcut sent this)
    fake(monkeypatch, "files", str(tmp_path), [str(sel)])
    it = fastpath._focus_intent()
    assert it is not None and it.args["path"] == str(sel)
