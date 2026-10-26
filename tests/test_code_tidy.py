import pytest

from jarvis.core import codetidy, config, fastpath


@pytest.fixture
def ed(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(codetidy, "_unsaved", lambda: False)
    f = tmp_path / "calc.py"
    monkeypatch.setattr(codetidy, "target", lambda path="": f)
    return f


def test_format_python_for_free(ed):
    ed.write_text("import os\ndef add(a,b):\n  return a+b\n")
    out = codetidy.run("format")
    assert out.startswith("Formatted calc.py") and ed.read_text() == "import os\n\n\ndef add(a, b):\n    return a + b\n"
    assert codetidy.run("format") == "calc.py is already well formatted."
    assert list((ed.parent / "data" / "code_backups").glob("calc.py.*.bak"))


def test_syntax_error_is_explained_not_formatted(ed):
    ed.write_text("def f():\n    try:\n  x = 1\n")
    out = codetidy.run("format")
    assert "syntax error" in out and "line" in out and ed.read_text() == "def f():\n    try:\n  x = 1\n"


def test_check_and_fix(ed):
    ed.write_text("import os\nimport sys\n\nprint(undefined_name)\n")
    out = codetidy.run("check")
    assert "problems in calc.py" in out and "line 1" in out and "fix the problems" in out
    out = codetidy.run("fix")
    assert "import os" not in ed.read_text() and "undefined" in out.lower()


def test_json_and_unsaved(ed, monkeypatch):
    j = ed.with_suffix(".json")
    j.write_text('{"a":1,"b":[1,2]}')
    monkeypatch.setattr(codetidy, "target", lambda path="": j)
    assert codetidy.run("format").startswith("Formatted calc.json") and j.read_text().startswith('{\n  "a": 1')
    monkeypatch.setattr(codetidy, "_unsaved", lambda: True)
    assert "unsaved changes" in codetidy.run("format")


def test_routing(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    a = lambda t: (fastpath.match(t).tool, fastpath.match(t).args)
    assert a("format my whole code") == ("code_tidy", {"action": "format", "path": ""})
    assert a("format main.py") == ("code_tidy", {"action": "format", "path": "main.py"})
    assert a("lint my code")[1]["action"] == "check" and a("any errors in this file")[1]["action"] == "check"
    assert a("fix the problems")[1]["action"] == "fix"
    assert a("fix this file")[0] == "text_assist"  # repairing a broken file needs the AI
