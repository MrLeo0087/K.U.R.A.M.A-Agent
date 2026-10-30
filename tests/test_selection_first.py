"""Phase C: with text/code highlighted, the MEANING of the request decides whether it is about the highlight (any
wording); the model is faked here (its real scores were calibrated in PROGRESS.md)."""
import pytest

from jarvis.core import assist, config, fastpath, rewrite, semantic

CODE = "def f(sessions):\n    return [s for s in sessions if s['on']]"


@pytest.fixture
def sel(monkeypatch):
    st = {"sel": CODE, "best": ("explain", 0.95), "ranked": [("knowledge", 0.90), (semantic.CHAT, 0.7)]}
    monkeypatch.setattr(config, "CONTEXT", True)
    monkeypatch.setattr(config, "FASTPATH", True)
    monkeypatch.setattr(rewrite, "peek", lambda: st["sel"])
    from jarvis.core import context
    monkeypatch.setattr(context, "snapshot", lambda: {"file": None, "selection": "", "tab": None})  # no real desktop
    monkeypatch.setattr(semantic, "ready", lambda: True)
    monkeypatch.setattr(semantic, "scores", lambda t: st["ranked"])
    monkeypatch.setattr(semantic, "best_of", lambda t, name, table: st["best"])
    for d in (assist._pending, assist._more, assist._use, assist._retry, assist._ask_back, assist._file_ref):
        d.clear()
    return st


def test_any_wording_about_the_highlight_goes_to_it(sel):
    it = fastpath.selection_intent("what this code about ?")  # no 'selected', no 'does': the old patterns missed it
    assert it.tool == "text_assist" and it.args["action"] == "code"
    sel["sel"] = "Plants turn sunlight into sugar and oxygen every day."
    assert fastpath.selection_intent("what this about").args["action"] == "explain"
    sel["sel"] = "serendipity"
    assert fastpath.selection_intent("what is this").args["action"] == "meaning"


def test_details_come_from_the_words(sel):
    sel["best"] = ("translate", 0.97)
    it = fastpath.selection_intent("put this in hindi and replace it")
    assert it.args == {"action": "translate", "lang": "hi", "replace": True, "text": ""}
    sel["best"] = ("run", 0.93)
    assert fastpath.selection_intent("run this code").tool == "code_nav"
    sel["best"] = ("improve", 0.9)
    assert fastpath.selection_intent("make it better").args == {"action": "improve", "request": "make it better"}


def test_other_meanings_keep_their_own_area(sel):
    sel["best"], sel["ranked"] = ("explain", 0.75), [("general", 0.88)]  # 'what is the time'
    assert fastpath.selection_intent("what is the time") is None
    sel["best"], sel["ranked"] = ("explain", 0.85), [("media", 0.95)]  # clearly another area
    assert fastpath.selection_intent("open youtube") is None
    sel["best"], sel["ranked"] = ("summary", 0.80), [(semantic.CHAT, 1.0)]  # small talk
    assert fastpath.selection_intent("tell me a joke") is None


def test_nothing_highlighted_a_named_file_or_a_waiting_question_skip_it(sel):
    sel["sel"] = ""
    assert fastpath.selection_intent("explain this") is None
    sel["sel"] = CODE
    assert fastpath.selection_intent("explain /home/leo/x/notes.py") is None
    assert fastpath.selection_intent("explain test.py") is None
    assist._more.update(kind="code", sel=CODE, until=9e18)  # "Want the full explanation?" waits: 'yes' is for it
    assert fastpath.selection_intent("yes") is None
    assert fastpath.selection_intent("explain this") is not None  # ...a new request is not an answer to it
    assist._pending.update(old="x", new="y", expires=9e18)  # a code change waits for yes/no: nothing else counts
    assert fastpath.selection_intent("explain this") is None


def test_the_model_not_ready_never_waits(sel, monkeypatch):
    monkeypatch.setattr(semantic, "ready", lambda: False)
    warmed = []
    monkeypatch.setattr(semantic, "warm_soon", lambda: warmed.append(1))
    assert fastpath.selection_intent("explain this") is None and warmed


def test_nothing_highlighted_asks_about_the_open_file_then_does_it(sel, monkeypatch, tmp_path):
    """Owner: 'complete this code' with nothing selected should at least ask if test.py is meant."""
    from jarvis.core import context, editor
    f = tmp_path / "test.py"
    f.write_text("def add(a, b):\n    return a + b\n")
    sel["sel"], sel["best"] = "", ("explain", 0.95)
    monkeypatch.setattr(context, "snapshot", lambda: {"file": f, "selection": "", "tab": None})
    it = fastpath.selection_intent("what is this code about")
    assert it.args["action"] == "file_ask" and it.args["path"] == str(f)
    out = assist.run(**it.args)
    assert "Do you mean the whole test.py" in out and assist.file_ref_waiting()
    assert fastpath.selection_intent("yes") is None  # the question waits: 'yes' is its answer, not a new request
    yes = fastpath.plan_answer_intent("yes")
    assert yes.args == {"action": "file_yes"}
    monkeypatch.setattr(assist, "_llm", lambda *a, **k: "It adds two numbers.")
    assert assist.run("file_yes").startswith("It adds two numbers.") and not assist.file_ref_waiting()
    assert assist.more_waiting()  # the short explanation offers the long one: a new request still goes through
    sel["best"] = ("complete", 0.95)
    assist.run(**fastpath.selection_intent("complete this code").args)
    assert assist.run("file_no").startswith("Okay. Select the code")
    monkeypatch.setattr(context, "snapshot", lambda: {"file": None, "selection": "", "tab": None})
    assert fastpath.selection_intent("explain this") is None  # nothing open, nothing selected: not this flow
