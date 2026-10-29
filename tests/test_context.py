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
