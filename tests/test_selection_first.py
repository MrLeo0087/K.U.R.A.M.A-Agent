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
    monkeypatch.setattr(semantic, "ready", lambda: True)
    monkeypatch.setattr(semantic, "scores", lambda t: st["ranked"])
    monkeypatch.setattr(semantic, "best_of", lambda t, name, table: st["best"])
    for d in (assist._pending, assist._more, assist._use, assist._retry, assist._ask_back):
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
    assert fastpath.selection_intent("explain this") is None


def test_the_model_not_ready_never_waits(sel, monkeypatch):
    monkeypatch.setattr(semantic, "ready", lambda: False)
    warmed = []
    monkeypatch.setattr(semantic, "warm_soon", lambda: warmed.append(1))
    assert fastpath.selection_intent("explain this") is None and warmed
