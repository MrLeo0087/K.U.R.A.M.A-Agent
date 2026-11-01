"""11-01 evening: tool-less claims after the retry, mood music, 'open file manager in X'."""
import pytest
from langchain_core.messages import AIMessage, SystemMessage

from jarvis.core import agent, fastpath, music, router


@pytest.mark.parametrize("text,name", [("open file manager in downloads", "downloads"),
                                       ("open file manager from kurama folder", "kurama"),
                                       ("open files from the tara folder", "tara")])
def test_file_manager_at_a_folder(text, name):
    it = fastpath._match(text)
    assert it.tool == "open_folder" and it.args["name"] == name


def test_mood_music_falls_back_to_a_mix(monkeypatch):
    import json
    out = json.dumps({"entries": [{"id": "a1", "title": "Relaxing music 3 hours", "duration": 3 * 3600}]})
    monkeypatch.setattr(music.store, "kv_get", lambda k, d=None: None)
    monkeypatch.setattr(music.store, "kv_set", lambda k, v: None)
    monkeypatch.setattr(music.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": out})())
    assert [s["id"] for s in music.search("relaxing music")] == ["a1"]


@pytest.mark.parametrize("claim", ["Sent", "Opened", "Playing Stabba."])
def test_a_claim_twice_with_no_tool_is_never_delivered(monkeypatch, claim):
    from jarvis.core import llm
    monkeypatch.setattr(llm, "chat", lambda messages, stream=False, **kw: llm.Reply(claim, "", [], message=AIMessage(content=claim)))
    monkeypatch.setattr(router, "route", lambda t, log_it=True: router.Route(["telegram"], "semantic"))
    out = agent.Agent().run("send hello to telegram")
    assert out.startswith("I didn't do it")


@pytest.mark.parametrize("text,name", [("Create new folder in here. Name new folder.", "new folder"),
                                       ("make a folder here called notes", "notes"),
                                       ("new folder here bro", "New folder")])
def test_new_folder_goes_in_the_folder_in_use(monkeypatch, tmp_path, text, name):
    from jarvis.core import focus, semantic
    monkeypatch.setattr(semantic, "ready", lambda: True)
    monkeypatch.setattr(semantic, "best_of", lambda t, n, table: ("new_folder", 0.95))
    monkeypatch.setattr(semantic, "scores", lambda t: [(semantic.CHAT, 0.5)])
    monkeypatch.setattr(fastpath, "meaning_ok", lambda t, it: True)
    monkeypatch.setattr(focus, "refer", lambda t: tmp_path)  # the folder open in Files
    it = fastpath.meaning_intent(text)
    assert (it.tool, it.args["path"]) == ("make_folder", str(tmp_path / name))


@pytest.mark.parametrize("text,where,name", [("create folder in downloads named x", "downloads", "x"),
                                             ("create a new folder in download folder name new_project2", "downloads",
                                              "new_project2"),
                                             ("make a folder called test2 in my documents", "documents", "test2")])
def test_new_folder_in_a_named_real_place(monkeypatch, tmp_path, text, where, name):
    from jarvis.core import focus, paths, semantic
    monkeypatch.setattr(semantic, "ready", lambda: True)
    monkeypatch.setattr(semantic, "best_of", lambda t, n, table: ("new_folder", 0.95))
    monkeypatch.setattr(semantic, "scores", lambda t: [(semantic.CHAT, 0.5)])
    monkeypatch.setattr(focus, "refer", lambda t: tmp_path / "files_app")
    real = {"downloads": tmp_path / "Downloads", "download": tmp_path / "Downloads", "documents": tmp_path / "Documents"}
    monkeypatch.setattr(paths, "smart_path", lambda t, want="any": real.get(t.lower()))
    it = fastpath.meaning_intent(text)
    assert it is not None and it.args["path"] == str(real[where] / name)


def test_new_folder_in_a_place_that_isnt_real_goes_to_the_ai(monkeypatch, tmp_path):
    from jarvis.core import focus, paths, semantic
    monkeypatch.setattr(semantic, "ready", lambda: True)
    monkeypatch.setattr(semantic, "best_of", lambda t, n, table: ("new_folder", 0.95))
    monkeypatch.setattr(semantic, "scores", lambda t: [(semantic.CHAT, 0.5)])
    monkeypatch.setattr(focus, "refer", lambda t: tmp_path)
    monkeypatch.setattr(paths, "smart_path", lambda t, want="any": None)
    assert fastpath.meaning_intent("create folder in narnia land named x") is None
