"""P8b devutils tools: one test per tool (tmp files, mocked LLM), routing disambiguation, secret masking."""
import ast
import json

import pytest

from jarvis.core import config, jobs, llm, meta, registry, router, safety, store
from jarvis.tools.interactive import add_docstrings as ad
from jarvis.tools.interactive import benchmark_table as bt
from jarvis.tools.interactive import config_diff as cd
from jarvis.tools.interactive import generate_requirements as gr
from jarvis.tools.interactive import notebook_to_script as nts

G = "gsk_" + "Q7xLm9TzR2vWb8NcK4pYh6JdF3sA1eU"
P = "Hun7er" + "-Pa55w0rd-9x!"


@pytest.fixture(autouse=True)
def safe_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FILE_SAFE_ROOTS", (tmp_path,))


def test_registered_group_and_safety():
    tools = {t.name: t for t in registry.schemas_for(["devutils"])}
    assert set(tools) == {"add_docstrings", "notebook_to_script", "generate_requirements", "config_diff",
                          "benchmark_table"}
    assert registry.safety_of(tools["add_docstrings"]) == "confirm"
    assert all(registry.safety_of(t) == "safe" for n, t in tools.items() if n != "add_docstrings")


def test_routing_disambiguation_en_hi_ne(monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no classifier")))
    route = lambda t: router.route(t, log_it=False).groups  # noqa: E731
    for text in ("generate requirements.txt for this project", "create a requirements file", "requirements.txt banao",
                 "requirements बनाउ", "add docstrings to budget.py", "add type hints to my functions",
                 "convert my notebook to a script", "convert analysis.ipynb to python", "what changed in my config",
                 "config diff", "snapshot my config", "build a benchmark table from results",
                 "results table for my training runs", "डकस्ट्रिङ थप", "config मा के फेरियो", "नोटबुकलाई स्क्रिप्टमा बदल"):
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


def _docs(*items):
    return lambda msgs, schema, **k: schema(items=[ad.Doc(name=n, docstring=d, signature_with_hints=s)
                                                   for n, d, s in items])


def test_add_docstrings_dry_run_confirm_and_bak(tmp_path, monkeypatch):
    f = tmp_path / "m.py"
    f.write_text(SRC)
    sent = []
    fake = _docs(("Box.area", "Area of a box.\n\nArgs:\n    w: width.", "def area(self, w: float, h: float = 2) -> float:"),
                 ("run", "Run it.", "def run(path, n=5, extra=1):"))  # changed params -> hints rejected
    monkeypatch.setattr(llm, "structured", lambda m, s, **k: sent.append(m[1]["content"]) or fake(m, s, **k))
    out = ad.add_docstrings(str(f), dry_run=True)
    assert "Dry run" in out and "2 docstrings" in out and "run hints (changed parameters)" in out
    assert f.read_text() == SRC and len(sent) == 1
    assert "def done" not in sent[0] and "# Box.area" in sent[0]  # only functions that need work are sent
    asked = []
    monkeypatch.setattr(safety, "ask", lambda p: asked.append(p) or False)
    assert ad.add_docstrings(str(f)).startswith("Not written") and f.read_text() == SRC
    monkeypatch.setattr(safety, "ask", lambda p: asked.append(p) or True)
    out = ad.add_docstrings(str(f))
    new = f.read_text()
    assert "updated" in out and (tmp_path / "m.py.bak").read_text() == SRC
    assert "def area(self, w: float, h: float = 2) -> float:  # keep me" in new
    assert '        """Area of a box.\n\n        Args:\n            w: width.\n        """\n        return w * h' in new
    assert 'def run(path, n=3):\n    """Run it."""\n    x = os.getcwd()   # odd   spacing kept' in new
    assert "+" in asked[-1] and "docstrings" in asked[-1]
    ast.parse(new)


def test_add_docstrings_unknown_name_and_background(tmp_path, monkeypatch):
    f = tmp_path / "big.py"
    f.write_text("\n\n".join(f"def f{i}(a):\n    return a" for i in range(12)) + "\n")
    calls = []

    def fake(msgs, schema, **k):
        calls.append(1)
        names = [ln[2:] for ln in msgs[1]["content"].splitlines() if ln.startswith("# ")]
        return schema(items=[ad.Doc(name=n, docstring=f"Do {n}.", signature_with_hints=f"def {n}(a: Any) -> int:")
                             for n in names])
    monkeypatch.setattr(llm, "structured", fake)
    jobs.reset_manager()
    try:
        out = ad.add_docstrings(str(f))
        assert out.startswith("started job #")
        job = jobs.get_manager().wait(int(out.split("#")[1].split(":")[0]), timeout=10)
        assert job.status == "done" and "big.py" in open(job.output_path).read()
    finally:
        jobs.reset_manager()
    n_calls = len(calls)
    monkeypatch.setattr(safety, "ask", lambda p: True)
    out = ad.add_docstrings(str(f))  # cached proposal: no new LLM calls
    assert len(calls) == n_calls and "0 tokens" in out and "12 docstrings" in out
    assert "unknown name Any" in out and "def f0(a):\n    \"\"\"Do f0.\"\"\"" in f.read_text()


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


def test_config_diff_snapshots_and_secret_masking(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".env").write_text(f"GROQ_API_KEY={G}\nREAL_ENV_ONLY=1\n")
    (proj / ".env.example").write_text("GROQ_API_KEY=your-key-here\nDEBUG=0\n")
    (proj / "config.yaml").write_text(f"model:\n  lr: 0.01\n  layers: [1, 2]\ndb_password: {P}\n")
    (proj / "settings.toml").write_text(f'[api]\nurl = "https://x.dev"\nkey = "{G}"\n')
    (proj / "credentials.json").write_text('{"client_secret": "zzz"}')
    first = cd.config_diff(str(proj))
    assert "saved config snapshot #1" in first and "3 files" in first
    assert "no config changes" in cd.config_diff(str(proj))
    (proj / "config.yaml").write_text(f"model:\n  lr: 0.02\n  layers: [1, 2]\n  dropout: 0.1\ndb_password: {P}x\n")
    (proj / "settings.toml").write_text('[api]\nurl = "https://x.dev"\n')
    out = cd.config_diff(str(proj))
    assert "#1 → #2" in out and "~model.lr: 0.01 → 0.02" in out and "+model.dropout=0.1" in out
    assert "~db_password (secret changed, masked)" in out and "-api.key" in out
    rows = store._exec("SELECT data FROM config_snapshots")
    blob = " ".join(r["data"] for r in rows) + out + cd.config_diff(str(proj), action="compare", a=1, b=2)
    for raw in (G, P, G[4:14], P[:8], "REAL_ENV_ONLY", "zzz"):
        assert raw not in blob, raw
    assert "****#" in blob and "#2" in cd.config_diff(str(proj), action="list")


def test_benchmark_table(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "sweep.csv").write_text("model,acc,loss\nbase,0.81,0.52\nbig,0.93,0.31\nsmall,0.75,0.60\n")
    (runs / "train.log").write_text("2026-10-23 12:00:01 start\nepoch 1 acc=0.70 loss=0.90\n"
                                    "epoch 2 acc=0.88 loss=0.40\n")
    (runs / "eval.json").write_text(json.dumps({"acc": 0.85, "loss": 0.29, "note": "x"}))
    (runs / "notes.txt").write_text("nothing numeric here\n")
    out = bt.benchmark_table(str(runs))
    assert len(out) <= 800 and "5 runs from 4 files; sorted by acc (higher is better)" in out
    lines = [ln for ln in out.splitlines() if ln.startswith("| ") and "run" not in ln and "..." not in ln]
    assert [ln.split("|")[1].strip() for ln in lines] == ["big", "train", "eval", "base", "small"]
    assert "**0.93**" in lines[0] and "**0.29**" in lines[2] and "| 2 |" in lines[1]  # epoch column
    saved = list((tmp_path / "outputs").glob("bench-*.md"))
    assert saved and "**0.93**" in saved[0].read_text()
    assert "sorted by loss (lower is better)" in bt.benchmark_table(str(runs / "*.csv"), metric="loss")
    assert "no result files" in bt.benchmark_table(str(tmp_path / "nope"))
