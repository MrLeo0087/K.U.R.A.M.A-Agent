import json

import pytest

from jarvis.core import fastpath, kaggle_gpu as kg


@pytest.fixture
def fake(tmp_path, monkeypatch):
    calls, notes = [], []
    monkeypatch.setattr(kg.config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(kg, "cli", lambda: tmp_path)  # exists
    monkeypatch.setattr(kg, "has_credentials", lambda: True)
    monkeypatch.setattr(kg, "username", lambda: "leo")
    monkeypatch.setattr(kg.time, "sleep", lambda s: None)
    status = {"v": 'leo/x has status "KernelWorkerStatus.RUNNING"'}

    def k(args, check=True, timeout=600):
        calls.append(args)
        if args[:2] == ["kernels", "status"]:
            return status["v"]
        if args[:2] == ["kernels", "output"]:
            (tmp_path / "data/outputs/kaggle").mkdir(parents=True, exist_ok=True)
            out = args[args.index("-p") + 1]
            open(f"{out}/model.pt", "w").write("w")
        return ""
    monkeypatch.setattr(kg, "kaggle", k)
    monkeypatch.setattr(kg.notify, "notify", lambda *a, **kw: notes.append(a))
    return calls, notes, status


def test_project_folder_run_watch_and_download(fake, tmp_path):
    calls, notes, status = fake
    proj = tmp_path / "proj"
    (proj / "data").mkdir(parents=True)
    (proj / "train.py").write_text("print(open('data/a.csv').read())")
    (proj / "data" / "a.csv").write_text("x\n1")
    (proj / "requirements.txt").write_text("numpy")
    msg = kg.run(proj)
    assert "Sent train.py to Kaggle's free GPU" in msg
    assert calls[0][:2] == ["datasets", "create"] and calls[1][:2] == ["kernels", "push"]
    work = next((tmp_path / "data/kaggle").iterdir())
    meta = json.loads((work / "kernel/kernel-metadata.json").read_text())
    assert meta["enable_gpu"] and meta["is_private"] and meta["dataset_sources"][0].endswith("-data")
    code = (work / "kernel/train.py").read_text()
    assert "copytree" in code and "requirements.txt" in code and code.endswith("print(open('data/a.csv').read())")
    kg.tick(now=10**10)
    assert kg._runs()[0]["state"] == "running" and not notes
    status["v"] = 'leo/x has status "complete"'
    kg.tick(now=10**10 + 100)
    assert kg._runs()[0]["state"] == "complete" and "finished" in notes[0][0] and "model.pt" in notes[0][1]


def test_notebook_prelude_and_intents(tmp_path):
    nb = tmp_path / "t.ipynb"
    nb.write_text(json.dumps({"cells": [{"cell_type": "code", "source": ["x=1"]}]}))
    kg._with_prelude(nb, kg._prelude(None, False), tmp_path / "o.ipynb")
    cells = json.loads((tmp_path / "o.ipynb").read_text())["cells"]
    assert "chdir" in "".join(cells[0]["source"]) and cells[1]["source"] == ["x=1"]
    assert fastpath.match("train this on gpu").args == {"action": "run", "path": "this"}
    assert fastpath.match("kaggle status").args == {"action": "status"}
