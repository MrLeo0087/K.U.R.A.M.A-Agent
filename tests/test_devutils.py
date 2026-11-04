"""P8b devutils tools: one test per tool (tmp files, mocked LLM), routing disambiguation, secret masking."""
import ast
import json

import pytest

from jarvis.core import config, jobs, llm, meta, registry, router, safety, store
from jarvis.tools.interactive import generate_requirements as gr
from jarvis.tools.interactive import notebook_to_script as nts

G = "gsk_" + "Q7xLm9TzR2vWb8NcK4pYh6JdF3sA1eU"
P = "Hun7er" + "-Pa55w0rd-9x!"


@pytest.fixture(autouse=True)
def safe_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FILE_SAFE_ROOTS", (tmp_path,))


def test_registered_group_and_safety():
    tools = {t.name: t for t in registry.schemas_for(["devutils"])}
    assert set(tools) == {"notebook_to_script", "generate_requirements", "decode_text"}
    assert all(registry.safety_of(t) == "safe" for t in tools.values())


def test_routing_disambiguation_en_hi_ne(monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no classifier")))
    route = lambda t: router.route(t, log_it=False).groups  # noqa: E731
    for text in ("generate requirements.txt for this project", "create a requirements file", "requirements.txt banao",
                 "requirements बनाउ",
                 "convert my notebook to a script", "convert analysis.ipynb to python", "what changed in my config",
                 "config diff", "snapshot my config", "config मा के फेरियो", "नोटबुकलाई स्क्रिप्टमा बदल"):
        assert route(text) == ["devutils"], text
    for text in ("check my requirements for outdated packages", "are my requirements pinned?", "check my dependencies"):
        assert route(text) == ["codequality"], text
    assert route("generate requirements and run tests") == ["devutils", "dev"]
    assert route("run tests") == ["dev"] and route("what is this project about") == ["knowledge"]
    assert "devutils(" in meta.schema()["function"]["description"]
    assert meta.estimate_tokens() < 200


SRC = '''import os


class Box:
    def area(self, w, h=2):  # keep me
        return w * h

    def done(self) -> int:
        """Done."""
        return 1


def run(path, n=3):
    x = os.getcwd()   # odd   spacing kept
    return x
'''




def test_notebook_to_script(tmp_path, monkeypatch):
    nb = {"nbformat": 4, "cells": [
        {"cell_type": "markdown", "source": ["# Title\n", "Some *notes*"]},
        {"cell_type": "code", "source": ["%matplotlib inline\n", "import os\n", "!pip install x\n", "files = !ls\n",
                                         "for i in range(2):\n", "    !echo hi\n", "s = '''a\n", "b'''\n", "print(s)"],
         "outputs": [{"output_type": "stream", "text": ["SECRET_OUTPUT\n"]}], "execution_count": 1},
        {"cell_type": "code", "source": "%%bash\necho no", "outputs": []},
        {"cell_type": "code", "source": "", "outputs": []}]}
    p = tmp_path / "a.ipynb"
    p.write_text(json.dumps(nb))
    out = nts.notebook_to_script(str(p))
    text = (tmp_path / "a.py").read_text()
    assert "wrote" in out and "2 code cells" in out and "warning" not in out
    assert "SECRET_OUTPUT" not in text and "# Title" in text and "# IPython: %matplotlib inline" in text
    assert "    pass  # IPython: !echo hi" in text and "# IPython: files = !ls" in text and "# echo no" in text
    ast.parse(text)
    monkeypatch.setattr(safety, "ask", lambda q: False)
    assert "declined" in nts.notebook_to_script(str(p), wrap_main=True)
    monkeypatch.setattr(safety, "ask", lambda q: True)
    nts.notebook_to_script(str(p), wrap_main=True)
    text = (tmp_path / "a.py").read_text()
    assert text.index("import os") < text.index("def main() -> None:") and "    print(s)" in text
    assert "s = '''a\nb'''" in text.replace("    s = '''a", "s = '''a")  # string body not re-indented
    assert text.rstrip().endswith('if __name__ == "__main__":\n    main()')
    ast.parse(text)


def test_generate_requirements(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    (proj / "pkg").mkdir(parents=True)
    (proj / "pkg" / "__init__.py").write_text("")
    (proj / "utils.py").write_text("def h():\n    pass\n")
    (proj / "main.py").write_text("import os, sys\nimport yaml\nimport cv2\nfrom sklearn.model_selection import x\n"
                                  "from . import y\nimport utils\nfrom pkg import z\n"
                                  "try:\n    import ujson_missing_pkg\nexcept ImportError:\n    pass\n")
    (proj / "venv" / "lib").mkdir(parents=True)  # no site-packages -> falls back to the active env
    (proj / "venv" / "x.py").write_text("import requests_inside_venv\n")
    (proj / "requirements.txt").write_text("PyYAML\nrequests\n")
    out = gr.generate_requirements(str(proj))
    text = (proj / "requirements.generated.txt").read_text()
    assert "wrote requirements.generated.txt" in out
    assert "PyYAML==" in text and "opencv-python  # not installed" in text and "scikit-learn" in text
    assert "optional" in text.split("ujson_missing_pkg", 1)[1].splitlines()[0]
    for bad in ("os", "sys", "utils", "pkg", "requests_inside_venv"):
        assert f"\n{bad}" not in text, bad
    assert "missing opencv-python" in out and "listed but not imported requests" in out
    assert (proj / "requirements.txt").read_text() == "PyYAML\nrequests\n"
    monkeypatch.setattr(safety, "ask", lambda q: False)  # never overwrite requirements.txt without a yes
    gr.generate_requirements(str(proj), output="requirements.txt")
    assert (proj / "requirements.txt").read_text() == "PyYAML\nrequests\n"
