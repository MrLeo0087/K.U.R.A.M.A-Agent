"""0-token actions picked by meaning (config.MEANING_SHORTCUTS); a request that names anything the examples don't
(a job number, another folder) goes to the AI. The real model is scored in tests/eval (cases from the traces)."""
from pathlib import Path

import pytest

from jarvis.core import fastpath, focus, semantic


@pytest.fixture
def meaning(monkeypatch):
    pick = {}
    monkeypatch.setattr(semantic, "ready", lambda: True)
    monkeypatch.setattr(semantic, "best_of", lambda t, name, table: (pick["label"], pick["score"]))
    monkeypatch.setattr(semantic, "scores", lambda t: [(semantic.CHAT, 0.5)])
    monkeypatch.setattr(focus, "refer", lambda t: Path("/media/leo/Project1/Tara"))
    return pick


@pytest.mark.parametrize("text,label,want", [
    ("start the jobs", "jobs_start", ("jobs", {"action": "start"})),
    ("ok now start the jobs bro", "jobs_start", ("jobs", {"action": "start"})),
    ("show my job list pls", "jobs_list", ("jobs", {"action": "list"})),
    ("copy the path of this folder", "copy_path", ("write_clipboard", {"text": "/media/leo/Project1/Tara"})),
    ("Copy the path.", "copy_path", ("write_clipboard", {"text": "/media/leo/Project1/Tara"})),
    ("copy this folder path pls", "copy_path", ("write_clipboard", {"text": "/media/leo/Project1/Tara"})),
    ("open this folder in vs code", "open_vscode", ("open_path", {"path": "/media/leo/Project1/Tara", "app": "vscode"})),
    ("Open VS Code from this folder.", "open_vscode", ("open_path", {"path": "/media/leo/Project1/Tara", "app": "vscode"})),
    ("open selected folder in vscode", "open_vscode", ("open_path", {"path": "/media/leo/Project1/Tara", "app": "vscode"})),
])
def test_close_in_meaning_and_nothing_extra_runs_without_the_ai(meaning, text, label, want):
    meaning.update(label=label, score=0.9)
    it = fastpath.meaning_intent(text)
    assert it is not None and (it.tool, it.args) == want


@pytest.mark.parametrize("text,label", [
    ("start job 2", "jobs_start"),                                  # which job: only the AI can pass it on
    ("start the jobs and send result to telegram", "jobs_start"),
    ("open vs code from kurama folder from tara", "open_vscode"),   # names another folder
    ("copy the path of kurama folder", "copy_path"),
])
def test_an_extra_detail_goes_to_the_ai(meaning, text, label):
    meaning.update(label=label, score=0.9)
    assert fastpath.meaning_intent(text) is None


def test_not_close_enough_or_nothing_to_point_at(meaning, monkeypatch):
    meaning.update(label="copy_path", score=0.7)
    assert fastpath.meaning_intent("copy the path") is None
    meaning.update(score=0.95)
    monkeypatch.setattr(focus, "refer", lambda t: None)
    assert fastpath.meaning_intent("copy the path") is None


def test_calling_kurama_first_is_not_a_detail(meaning):
    meaning.update(label="jobs_start", score=0.9)
    assert fastpath.meaning_intent("Kurama, start the jobs").args == {"action": "start"}
    assert fastpath.meaning_intent("hey kurama start the jobs").args == {"action": "start"}


@pytest.mark.parametrize("text,want", [("copy the path of this folder", "dir"), ("copy this folder path pls", "dir"),
                                       ("copy this file's path", "file")])
def test_this_folder_after_a_file_is_the_files_folder(meaning, monkeypatch, tmp_path, text, want):
    f = tmp_path / "link_store.txt"
    f.write_text("")
    monkeypatch.setattr(focus, "refer", lambda t: f)
    meaning.update(label="copy_path", score=0.9)
    assert fastpath.meaning_intent(text).args["text"] == str(tmp_path if want == "dir" else f)
