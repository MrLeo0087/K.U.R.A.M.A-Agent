from pathlib import Path

import pytest

from jarvis.core import focus, paths


@pytest.fixture
def kv(monkeypatch):
    d = {}
    monkeypatch.setattr(focus.store, "kv_get", lambda k, default=None: d.get(k, default))
    monkeypatch.setattr(focus.store, "kv_set", lambda k, v: d.__setitem__(k, v))
    return d


@pytest.fixture
def tree(tmp_path, monkeypatch):
    for p in ("Project1/Tara/TARA/Final_RAG/data", "Project1/Tara/Final_RAG/local_llm", "Project1/clz_project"):
        (tmp_path / p).mkdir(parents=True)
    monkeypatch.setattr(paths.config, "SEARCH_ROOTS", (str(tmp_path),))
    monkeypatch.setattr(paths, "all_disks", lambda: [tmp_path])
    return tmp_path


def test_current_previous_parent(kv, tree):
    final = tree / "Project1/Tara/TARA/Final_RAG"
    focus.set_path(tree / "Project1/clz_project")
    focus.set_path(final)
    assert focus.cwd() == final
    assert paths.smart_path("it", "dir") == final and paths.smart_path("here", "dir") == final
    assert paths.smart_path("previous folder", "dir") == tree / "Project1/clz_project"
    assert paths.smart_path("parent folder", "dir") == final.parent
    assert paths.smart_path("data", "dir") == final / "data"  # relative to the current folder first


def test_absolute_path_with_typos_and_spoken_numbers(kv, tree):
    raw = str(tree).replace("/tmp", "/TMP", 1) if str(tree).startswith("/tmp") else str(tree)
    got = paths.smart_path(f"{raw}/project one/tara/TARA/final rag", "dir")
    assert got == tree / "Project1/Tara/TARA/Final_RAG"


def test_send_refuses_whole_home():
    from jarvis.tools.general.send_file_telegram import too_broad
    assert too_broad(Path.home()) and too_broad(Path("/"))
    assert too_broad(Path.home() / "Downloads") is None


def test_followup_intents():
    from jarvis.core import fastpath
    assert fastpath.match("list files here").args == {"path": "this"}
    assert fastpath.match("go back to the previous folder").args == {"name": "previous folder"}
    assert fastpath.match("Look for Project1/clz_project folder").args == {"query": "clz_project", "path": "Project1",
                                                                          "kind": "folder"}
