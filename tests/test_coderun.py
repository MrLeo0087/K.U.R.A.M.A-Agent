from jarvis.core import coderun, fastpath


def _file(tmp_path):
    f = tmp_path / "calc.py"
    f.write_text("import math\n\n\ndef add(a, b):\n    return a + b\n\n\nprint('top level runs only in whole mode')\n")
    return f


def test_runs_selection_with_the_files_definitions(tmp_path):
    f = _file(tmp_path)
    out = coderun.run("print(add(2, 3), math.pi > 3)", tmp_path, f)
    assert "Output:" in out and "5 True" in out and "top level" not in out


def test_error_points_at_the_selection_and_fix_it_is_offered(tmp_path):
    f = _file(tmp_path)
    out = coderun.run("x = 1\nprint(add(x))", tmp_path, f)
    assert out.startswith("❌ It failed: TypeError") and "line 2 of your selection" in out and "fix it" in out
    assert coderun.pending_fix()
    i = fastpath.match("fix it")
    assert i.tool == "text_assist" and i.args["action"] == "improve" and "TypeError" in i.args["request"]
    coderun.run("print(1)", tmp_path, f)  # a good run forgets the error
    assert coderun.pending_fix() is None


def test_limits_input_definitions_and_whole_file(tmp_path, monkeypatch):
    f = _file(tmp_path)
    monkeypatch.setattr(coderun, "TIMEOUT_S", 2)
    assert "still running after 2 s" in coderun.run("while True:\n    pass", tmp_path, f)
    assert "input()" in coderun.run("name = input('name? ')", tmp_path, f)
    assert "only defines add" in coderun.run("def add(a, b):\n    return a + b", tmp_path, f)
    assert "printed nothing" in coderun.run("y = 2", tmp_path, f)
    assert "top level runs only in whole mode" in coderun.run(f.read_text(), tmp_path, f, whole=True)
    js = tmp_path / "a.js"
    js.write_text("")
    assert "42" in coderun.run("console.log(6 * 7)", tmp_path, js)


def test_routes():
    for s in ("run this code", "run the selected code", "execute this", "/run", "run this function"):
        i = fastpath.match(s)
        assert i and i.tool == "code_nav" and i.args["action"] == "run", s
    assert fastpath.match("run it") is None and fastpath.match("run the tests") is None
