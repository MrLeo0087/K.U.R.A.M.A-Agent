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


@pytest.mark.parametrize("text,name", [
    ("save this website names whatsapp", "whatsapp"),          # 07:49 live: the AI summarized the page instead
    ("save this link to socolive", "socolive"),
    ("i mean sabe it's url in link store name google drive", "google drive"),
    ("bro save this page link as watest", "watest"),            # the name is never typo-'fixed' ('latest')
])
def test_save_link_takes_the_left_over_words_as_the_name(meaning, monkeypatch, text, name):
    monkeypatch.setattr(fastpath, "meaning_ok", lambda t, it: True)
    meaning.update(label="save_link", score=0.9)
    assert fastpath.meaning_intent(text).args == {"action": "save", "name": name}


@pytest.mark.parametrize("text", ["save this file as report", "save this image as cat now pls", "save this code as test.py"])
def test_save_with_another_object_is_not_a_link(meaning, monkeypatch, text):
    monkeypatch.setattr(fastpath, "meaning_ok", lambda t, it: True)
    meaning.update(label="save_link", score=0.9)
    assert fastpath.meaning_intent(text) is None


def test_save_link_without_a_name_asks_for_one(meaning, monkeypatch):
    monkeypatch.setattr(fastpath, "meaning_ok", lambda t, it: True)
    meaning.update(label="save_link", score=0.9)
    assert fastpath.meaning_intent("save this link pls").args == {"action": "save"}


@pytest.mark.parametrize("text", ["show me link stroe", "give me list of link store", "what links i saved bro"])
def test_list_links_by_meaning(meaning, monkeypatch, text):
    monkeypatch.setattr(fastpath, "meaning_ok", lambda t, it: True)
    meaning.update(label="list_links", score=0.9)
    assert fastpath.meaning_intent(text).args == {"action": "list"}


@pytest.mark.parametrize("text", ["show me link stroe", "open my link store", "check this link"])
def test_a_leading_unknown_word_is_the_action_not_a_name(meaning, monkeypatch, text):
    """08:02 live: 'show me link stroe' was saved as a link named 'show'."""
    monkeypatch.setattr(fastpath, "meaning_ok", lambda t, it: True)
    meaning.update(label="save_link", score=0.9)
    it = fastpath.meaning_intent(text)
    assert it is None or "name" not in it.args or it.args["name"] not in ("show", "open", "check")


@pytest.mark.parametrize("text,label,action", [("free RAM bro", "clean_ram", "ram"),
                                                ("clear cache of kurama", "clean_kurama", "kurama"),
                                                ("clean kurama storage", "clean_kurama", "kurama"),
                                                ("free some disk space pls", "clean_storage", "storage")])
def test_cleanups_by_meaning(meaning, monkeypatch, text, label, action):
    monkeypatch.setattr(fastpath, "meaning_ok", lambda t, it: True)
    meaning.update(label=label, score=0.9)
    assert fastpath.meaning_intent(text).args == {"action": action}
