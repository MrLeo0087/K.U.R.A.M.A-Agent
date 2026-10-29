import pytest

from jarvis.core import assist, config, context
from jarvis.tools.core import text


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setattr(config, "CONTEXT", True)


def test_selected_code_in_vs_code_is_the_context_and_edit_code_uses_it(monkeypatch, tmp_path):
    f = tmp_path / "test.py"
    f.write_text("import pandas as pd\ncolumns = ['A', 'B', 'C', 'D']\n")
    monkeypatch.setattr(assist, "open_file_in_editor", lambda: f)
    monkeypatch.setattr(context, "_primary", lambda: "columns = ['A', 'B', 'C', 'D']")
    monkeypatch.setattr(context, "_cache", (0.0, {}))
    line = context.line()
    assert "test.py" in line and "columns = ['A', 'B', 'C', 'D']" in line and "edit_code" in line
    assert text._edit_request({"request": "make them small a,b,c,d"}) == "make them small a,b,c,d (code)"


def test_text_highlighted_elsewhere_is_not_taken_as_the_selection(monkeypatch, tmp_path):
    f = tmp_path / "test.py"
    f.write_text("print(1)\n")
    monkeypatch.setattr(assist, "open_file_in_editor", lambda: f)
    monkeypatch.setattr(context, "_primary", lambda: "some chat text in KURAMA")
    monkeypatch.setattr(context, "_cache", (0.0, {}))
    assert context.snapshot()["selection"] == ""
    assert text._edit_request({"request": "add a loop"}) == "add a loop in this file"


def test_generated_code_goes_into_the_open_file_only_code(monkeypatch, tmp_path):
    from jarvis.core import fastpath, safety
    from jarvis.tools.general import code_to_file as ctf
    out = tmp_path / "outputs"
    out.mkdir()
    (out / "20261030-batch.md").write_text("# Batch\n\nSome long text.\n\n```python\nimport pandas as pd\nprint(1)\n```\nMore text.\n")
    monkeypatch.setattr(config, "OUTPUTS_DIR", out)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    f = tmp_path / "test.py"
    f.write_text("old = 1\n")
    monkeypatch.setattr(assist, "open_file_in_editor", lambda: f)
    monkeypatch.setattr(context, "_primary", lambda: "")
    monkeypatch.setattr(context, "_cache", (0.0, {}))
    monkeypatch.setattr(safety, "ask", lambda prompt: True)
    i = fastpath.match("write this code in oopen file test.py .. only code")
    assert i.tool == "code_to_file" and i.args == {"path": ""}
    assert "Wrote 2 lines" in ctf.code_to_file()
    assert f.read_text() == "import pandas as pd\nprint(1)\n"  # only the code, no essay text
    assert list((tmp_path / "backups").iterdir())  # the old version is kept


def test_a_single_module_request_is_written_as_one_code_file(monkeypatch, tmp_path):
    from jarvis.core import writer

    class Ctx:
        job = type("J", (), {"title": "batch cleaner", "id": 1})()
        out = None

        def progress(self, t): pass
        def purpose(self, p): return p
        def set_output(self, p): self.out = p
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(writer.llm, "chat", lambda *a, **k: "Here:\n```python\ndef f():\n    return 1\n```\nDone.")
    ctx = Ctx()
    p = writer.run(ctx, "Write a complete Python module named batch_cleaner.py using pandas", kind="code")
    assert p.endswith(".py") and open(p).read() == "def f():\n    return 1\n"
