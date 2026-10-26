import pytest

from jarvis.core import assist, fastpath, rewrite


@pytest.fixture
def desk(monkeypatch):
    st = {"pasted": None, "sel": "teh cat sat"}
    monkeypatch.setattr(rewrite, "grab", lambda: rewrite.Grab(st["sel"], 7, False, False, "Doc"))
    monkeypatch.setattr(rewrite, "grab_cursor", lambda: rewrite.Grab("", 7, False, False, "main.py - KURAMA - VS Code"))
    monkeypatch.setattr(rewrite, "put", lambda g, new: st.__setitem__("pasted", new))
    monkeypatch.setattr(rewrite, "_xclip", lambda a, text=None: "")
    calls = []

    def llm(system, user, smart, max_tokens, purpose):
        calls.append((purpose, smart))
        return {"assist_code_fix": "    def add(a, b):\n    return a + b"}.get(purpose, f"[{purpose}]")
    monkeypatch.setattr(assist, "_llm", llm)
    monkeypatch.setattr(assist, "open_file_in_editor", lambda: None)
    return st, calls


def test_read_actions_leave_the_selection(desk):
    st, calls = desk
    st["sel"] = "The committee deferred its decision indefinitely."
    assert assist.run("explain", "what does this mean") == "[assist_explain]" and st["pasted"] is None
    st["sel"] = "ubiquitous"
    assert assist.run("explain", "what does this mean") == "[assist_meaning]"  # one word -> dictionary meaning
    assert assist.run("translate", "translate this into nepali", "ne").startswith("[assist_translate]")
    assert st["pasted"] is None
    assert assist.run("meaning", text="serendipity") == "[assist_meaning]"


def test_write_actions(desk):
    st, calls = desk
    st["sel"] = "    def add(a,b):\n        return a+b"
    assert "Replaced the highlighted code" in assist.run("improve", "optimize this code")
    assert st["pasted"].startswith("    def add")  # indentation kept
    assert ("assist_code_fix", True) in calls  # code uses the smart model
    assert "Wrote" in assist.run("write", "write a calculator function here")
    st["sel"] = "i is happy"
    assist.run("translate", "translate this to english and replace it", "en", replace=True)
    assert st["pasted"] == "[assist_translate]"


def test_routing():
    def a(t):
        i = fastpath.match(t)
        return i and (i.tool, i.args.get("action"))
    assert a("what does this mean") == ("text_assist", "explain")
    assert a("what is the meaning of this word in nepali") == ("text_assist", "meaning")
    assert a("translate this paragraph into hindi") == ("text_assist", "translate")
    assert a("what does this function do") == ("text_assist", "code")
    assert a("optimize this code") == ("text_assist", "improve")
    assert a("write a calculator class in python here") == ("text_assist", "write")
    assert a("explain main.py") == ("text_assist", "explain_file")
    assert fastpath.match("explain quantum physics") is None and fastpath.match("what is the meaning of life") is None
    assert a("explain this error") == ("fix_error", "explain")
