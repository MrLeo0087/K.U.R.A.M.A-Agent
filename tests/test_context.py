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


def test_write_code_into_the_open_file_like_an_editor(monkeypatch, tmp_path):
    from jarvis.core import fastpath, llm, planner, safety
    from jarvis.tools.general import code_to_file as ctf
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    f = tmp_path / "test.py"
    f.write_text("")  # a blank file is fine
    monkeypatch.setattr(assist, "open_file_in_editor", lambda: f)
    monkeypatch.setattr(context, "_primary", lambda: "")
    monkeypatch.setattr(context, "_cache", (0.0, {}))
    seen = {}
    monkeypatch.setattr(llm, "chat", lambda msgs, **k: seen.update(prompt=msgs[-1]["content"], n=seen.get("n", 0) + 1) or
                        "Sure!\n```python\nimport pandas as pd\n\n\nasync def process_large_csv(p: str) -> None:\n    ..."
                        + "\n" * (seen["n"] - 1) + "#\n```\nDone.")
    asked = []
    monkeypatch.setattr(safety, "ask", lambda prompt: asked.append(prompt) or True)
    t = ("Write a module using pandas and asyncio that reads a CSV in chunks, strips whitespace, and writes parquet."
         "\n\ngenerate code and write in this test.py file")
    i = fastpath.match(t)
    assert i.tool == "code_to_file" and not planner.is_multi(t)
    from jarvis.core import jobs

    class Ctx:
        def progress(self, t): seen["said"] = t
        def check(self): pass
    monkeypatch.setattr(jobs, "get_manager", lambda: type("M", (), {"submit": lambda self, title, kind, fn: fn(Ctx())})())
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path / "out")
    assert "Working on test.py" in ctf.code_to_file(**i.args)  # a background job: the reply never hangs
    out = seen["said"]
    assert "Wrote 5 lines" in out and f.read_text().startswith("import pandas as pd") and "Sure" not in f.read_text()
    monkeypatch.setattr(context, "editor_open", lambda: True)
    assert asked == [] and "reads a CSV in chunks" in seen["prompt"]  # blank file: written without a question
    first = f.read_text()
    ctf.code_to_file(request="complete this file")  # a file with code: only the change, and it waits for a yes
    assert "Should I add it?" in seen["said"] and "lines" in seen["said"] and assist.pending_code_active()
    assert f.read_text() == first  # nothing changed yet
    assert assist.apply_pending_code().startswith("Added to test.py")
    assert f.read_text() != first and list((tmp_path / "backups").iterdir())  # applied, old version kept
    assert "async def process_large_csv" in seen["prompt"]  # the AI saw the file's current code


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


def test_only_where_words_mean_no_description():
    from jarvis.tools.general import code_to_file as ctf
    assert ctf._spec("write generate code on this path /media/leo/x/test.py") == ""
    assert ctf._spec("write this code in oopen file test.py .. only code") == ""
    assert ctf._spec("add a main block that calls it in this file")
