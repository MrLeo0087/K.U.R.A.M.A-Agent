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


def _helpproj(tmp_path):
    from pathlib import Path  # noqa: F401
    (tmp_path / "util.py").write_text(
        "def add(a, b, *, scale=1):\n    '''Add two numbers.\n\n    Args:\n        a (int): first.\n        b (int): second.\n"
        "        scale: multiply by this.\n    '''\n    return (a + b) * scale\n")
    main = tmp_path / "main.py"
    main.write_text("import json\nfrom util import add\n")
    return main


def test_libhelp_checks_the_call_0_tokens(tmp_path, monkeypatch):
    from jarvis.core import assist, libhelp
    monkeypatch.setattr(assist, "_llm", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no LLM")))
    main = _helpproj(tmp_path)
    out = libhelp.help_for("print('a', sepp='')", "", tmp_path, main)
    assert "builtins.print" in out and "Did you mean `sep`?" in out
    out = libhelp.help_for("json.dumps(x, indnt=2)", "", tmp_path, main)
    assert "json.dumps" in out and "Did you mean `indent`?" in out
    assert "✅" in libhelp.help_for("json.dumps(x, indent=2)", "is this correct", tmp_path, main)
    out = libhelp.help_for("add(1)", "", tmp_path, main)  # project function: read from source, nothing imported
    assert "Missing a required argument: 'b'" in out and "Required: a, b" in out and "`b`: second." in out
    assert "✅" in libhelp.help_for("total = add(1, 2, scale=3)", "", tmp_path, main)


def test_libhelp_suggest_and_unresolved_use_one_small_call(tmp_path, monkeypatch):
    from jarvis.core import assist, libhelp
    calls = []
    monkeypatch.setattr(assist, "_llm", lambda system, user, **k: calls.append((user, k)) or "Use indent=2.")
    main = _helpproj(tmp_path)
    out = libhelp.help_for("json.dumps(x)", "suggest a better way", tmp_path, main)
    assert out.endswith("Use indent=2.") and "Real signature of json.dumps" in calls[0][0] and not calls[0][1]["smart"]
    assert libhelp.help_for("df.groupby('a').sum()", "", tmp_path, main) == "Use indent=2." and len(calls) == 2


def test_param_docs_numpy_style():
    from jarvis.core import libhelp
    doc = "Read a file.\n\nParameters\n----------\nsep : str, default ','\n    The separator.\nheader : int\n    Row number.\n"
    assert libhelp.param_docs(doc) == {"sep": "str, default ',' — The separator.", "header": "int — Row number."}


def test_libhelp_routes():
    for s in ("help me with this library", "what arguments does this function take", "is this correct syntax",
              "did I use this function correctly", "/args"):
        i = fastpath.match(s)
        assert i and i.tool == "code_nav" and i.args["action"] == "help", s
    assert fastpath.match("/args json.dumps").args["name"] == "json.dumps"
    assert fastpath.match("how can I use this function").args["action"] == "use"
