from pathlib import Path

from jarvis.core import codenav, fastpath


def _project(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "mathx.py").write_text(
        "import os\n\n\n@staticmethod\ndef calc_total(a, b):\n    '''Add.'''\n    return a + b\n\n\ndef other():\n    pass\n")
    (tmp_path / "old.py").write_text("def calc_total(x):\n    return x\n")
    (tmp_path / "venv").mkdir()
    (tmp_path / "venv" / "lib.py").write_text("def calc_total():\n    pass\n")  # never searched
    (tmp_path / "web.js").write_text("const add = (a, b) => {\n  return a + b;\n};\nfunction greet(n) {\n  return 'hi ' + n;\n}\n")
    main = tmp_path / "main.py"
    main.write_text("from pkg.mathx import calc_total\nimport json\n\nprint(calc_total(1, 2))\n")
    return main


def test_name_from_selection():
    assert codenav.name_from("total = calc.add(a, b)") == "calc.add"
    assert codenav.name_from("self.save()") == "save"
    assert codenav.name_from("def run(x):") == "run"
    assert codenav.name_from("  ") == ""


def test_finds_imported_definition_whole_block_and_opens_it(tmp_path, monkeypatch):
    main = _project(tmp_path)
    opened = []
    monkeypatch.setattr(codenav, "open_in_editor", lambda p, n: opened.append((p, n)) or True)
    r = codenav.find("calc_total(1, 2)", tmp_path, main)
    assert r["file"].name == "mathx.py" and r["line"] == 5  # the import wins over old.py
    assert r["code"].startswith("@staticmethod") and r["code"].rstrip().endswith("return a + b")
    assert [o["file"].name for o in r["others"]] == ["old.py"]  # venv/ skipped
    msg = codenav.go("calc_total", tmp_path, main)
    assert "pkg/mathx.py, line 5" in msg and "opened it in VS Code" in msg and "old.py:1" in msg
    assert opened == [(tmp_path / "pkg" / "mathx.py", 5)]


def test_js_blocks_and_library_and_missing(tmp_path, monkeypatch):
    main = _project(tmp_path)
    monkeypatch.setattr(codenav, "open_in_editor", lambda p, n: True)
    r = codenav.find("greet('x')", tmp_path, main)
    assert r["file"].name == "web.js" and r["code"].endswith("}")
    lib = codenav.find("json.dumps", tmp_path, main)  # imported library: its real source file
    assert lib["where"] == "library json" and lib["file"].name == "__init__.py" and "def dumps" in lib["code"]
    assert "couldn't find" in codenav.find("nothing_here", tmp_path, main)["error"]
    assert "Highlight" in codenav.find("", tmp_path, main)["error"]


def test_routes():
    for s in ("find this function", "go to definition", "take me to this function", "where is this function defined",
              "show me the real code of this function", "redirect me to this function", "/def"):
        i = fastpath.match(s)
        assert i and i.tool == "code_nav" and i.args["name"] == "", s
    assert fastpath.match("find the function calc_total").args["name"] == "calc_total"
    assert fastpath.match("/def save_note").args["name"] == "save_note"
    assert fastpath.match("explain this function").tool == "text_assist"
    assert fastpath.match("find the file report.pdf").tool == "find_files"
