"""A saved command still works with 'in VS Code / in files' around it (11-06: it opened ~/projects/myproject)."""
from __future__ import annotations

import json

from jarvis.core import config, mywords


def test_saved_command_with_an_app_named(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    proj = tmp_path / "KURAMA"
    proj.mkdir()
    (tmp_path / "my_words.json").write_text(json.dumps({"open kurama project": f"open {proj} in vs code"}))
    assert mywords.expand("Open Kurama Project") == f"open {proj} in vs code"
    assert mywords.expand("Open Kurama Project in VS Code.") == f"open {proj} in vs code"
    assert mywords.expand("open kurama project in files") == f"open {proj} in files"
    assert mywords.expand("open another project in vs code") == "open another project in vs code"
    assert mywords.path_for("Kurama Project") == proj
    assert mywords.path_for("my project") is None
