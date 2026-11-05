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
    ("open vs code from zzqx folder from qqzz", "open_vscode"),   # names folders that do not exist
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


WINS = [{"id": "0x03c00006", "wmclass": "code.Code", "title": "main.py - Visual Studio Code"},
        {"id": "0x04a00003", "wmclass": "brave-browser.Brave-browser", "title": "(1) YouTube - Brave"}]


@pytest.mark.parametrize("text,label,want", [
    ("Minimize the window.", "window_minimize", {"action": "minimize", "name": ""}),
    ("minimize youtube", "window_minimize", {"action": "minimize", "name": "youtube"}),
    ("maximize vs code", "window_maximize", {"action": "maximize", "name": "vs code"}),
    ("restore the window", "window_restore", {"action": "restore", "name": ""}),
])
def test_one_window_by_meaning_never_all_of_them(meaning, monkeypatch, text, label, want):
    """11-05: 'Minimize the window.' showed the desktop (every window); 'Minimized Browser' cost 1.5k tokens."""
    from jarvis.tools.general import _apps
    monkeypatch.setattr(_apps, "list_windows", lambda: WINS)
    meaning.update(label=label, score=0.97)
    it = fastpath.meaning_intent(text)
    assert it is not None and (it.tool, it.args) == ("window", want)


def test_a_window_action_on_an_app_that_is_not_open_goes_to_the_ai(meaning, monkeypatch):
    from jarvis.tools.general import _apps
    monkeypatch.setattr(_apps, "list_windows", lambda: WINS)
    meaning.update(label="window_minimize", score=0.97)
    assert fastpath.meaning_intent("minimize spotify") is None


def test_open_app_names_are_slots(monkeypatch):
    from jarvis.tools.general import _apps
    monkeypatch.setattr(_apps, "list_windows", lambda: WINS)
    assert fastpath._mask_open_apps("minimize vs code") == "minimize X"
    assert fastpath._mask_open_apps("make youtube full screen") == "make X full screen"
    assert fastpath._mask_open_apps("minimize the window") is None


def test_a_folder_named_in_words_is_found_for_vs_code(tmp_path, monkeypatch):
    """11-05: 'From the project1, then new project, there is the folder name Kurama, open this folder in VS Code.'
    was split into 4 AI steps (3.8k tokens) and saved a link. The words are a path; several same-named folders ->
    the one worked in last."""
    import os
    import time
    from jarvis.core import config, paths
    new = tmp_path / "Project1" / "New_project" / "KURAMA"
    old = tmp_path / "Project1" / "Test_project" / "KURAMA"
    (new / ".git").mkdir(parents=True)
    old.mkdir(parents=True)
    (new / ".git" / "index").write_text("x")
    past = time.time() - 86400
    os.utime(old, (past, past))
    monkeypatch.setattr(config, "SEARCH_ROOTS", [str(tmp_path)])
    monkeypatch.setattr(config, "PATH_ALIASES", {})
    monkeypatch.setattr(paths, "all_disks", lambda: [])
    monkeypatch.setattr(focus, "cwd", lambda: None)
    monkeypatch.setattr(focus, "refer", lambda t: None)
    said = "From the project1, then new project, there is the folder name Kurama, open this folder in VS Code."
    assert fastpath.folder_in_words(said) == new
    assert fastpath.folder_in_words("open the kurama folder from project1 in vs code") == new  # the recent one
    assert fastpath.folder_in_words("open the kurama folder in test project in vs code") == old
    assert fastpath.folder_in_words("open the zzqx folder in vs code") is None


def test_a_path_said_in_parts_is_one_task_not_four(monkeypatch):
    """11-05 11:21: 'from project1 then new_project and kurama folder .. open this folder in vs code' was planned as
    4 AI steps (3.4k tokens, 3 failed): the parts that only name folders on the path are not tasks."""
    from jarvis.core import planner
    where = "/media/leo/Project1/New_project/KURAMA"
    assert planner._names_a_place_in("new_project then kurama folder .", where)
    assert planner._names_a_place_in("from project1", where)
    assert not planner._names_a_place_in("play a song", where)


def test_your_own_commands_list_and_forget(meaning, monkeypatch, tmp_path):
    from jarvis.core import config, mywords
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    mywords.save("open kurama project", "open /tmp in vs code")
    meaning.update(label="my_commands", score=0.95)
    assert (fastpath.meaning_intent("show my commands").args) == {"action": "list"}
    meaning.update(label="my_command_forget", score=0.95)
    it = fastpath.meaning_intent("forget my command open kurama project")
    assert it.args == {"action": "forget", "name": "open kurama project"}
    assert fastpath.meaning_intent("forget my command never saved") is None  # only a command that exists
    assert fastpath._mask_my_commands("delete my command open kurama project") == "delete my command X"
    assert fastpath.folder_in_words("open /tmp in vs code") == Path("/tmp")  # a written-out path counts
