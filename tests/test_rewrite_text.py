import pytest

from jarvis.core import fastpath, rewrite


@pytest.fixture
def desk(monkeypatch):
    """A fake desktop: a clipboard, a selection in the target app, key presses, window switches."""
    st = {"clip": "", "app_sel": "teh cat sat", "keys": [], "acts": [], "pasted": None, "primary": "KURAMA chat text"}
    from jarvis.core import uiagent

    def xclip(args, text=None):
        if args[1] == "primary":
            return st["primary"]
        if text is not None:
            st["clip"] = text
            return ""
        return st["clip"]

    def key(k):
        st["keys"].append(k)
        if k in ("ctrl+c", "ctrl+shift+c") and st["app_sel"]:
            st["clip"] = st["app_sel"]
        if k in ("ctrl+v", "ctrl+shift+v"):
            st["pasted"] = st["clip"]
    monkeypatch.setattr(rewrite, "_xclip", xclip)
    monkeypatch.setattr(rewrite, "_activate", lambda w: st["acts"].append(w))
    monkeypatch.setattr(rewrite, "_window_name", lambda w: "ChatGPT - Brave")
    monkeypatch.setattr(rewrite.time, "sleep", lambda s: None)
    monkeypatch.setattr(rewrite, "transform", lambda t, i: "The cat sat." if t == "teh cat sat" else "WRONG")
    monkeypatch.setattr(uiagent, "active_class", lambda: "brave-browser")
    monkeypatch.setattr(uiagent, "key", key)
    return st


def test_typed_in_kurama_copies_from_the_document_not_primary(desk, monkeypatch):
    monkeypatch.setattr(rewrite, "target_window", lambda: (77, False))
    out = rewrite.rewrite("fix this sentence")
    assert desk["acts"] and desk["acts"][0] == 77  # went back to the document first
    assert desk["keys"] == ["ctrl+c", "ctrl+v"] and desk["pasted"] == "The cat sat."
    assert out.startswith("Replaced the highlighted text in 'ChatGPT - Brave'")


def test_said_while_in_the_app(desk, monkeypatch):
    monkeypatch.setattr(rewrite, "target_window", lambda: (5, True))
    rewrite.rewrite("fix grammar")
    assert desk["acts"] == [] and desk["pasted"] == "The cat sat."


def test_nothing_selected(desk, monkeypatch):
    desk["app_sel"] = ""
    monkeypatch.setattr(rewrite, "target_window", lambda: (77, False))
    assert "couldn't see any highlighted text" in rewrite.rewrite("fix this")
    assert desk["pasted"] is None  # KURAMA's own chat text (PRIMARY) is never used from another window


def test_kurama_window_detection_and_intents():
    assert rewrite._is_kurama("KURAMA - Brave", ("brave-browser",))
    assert rewrite._is_kurama("anything", ("kurama_wallpaper.py",))
    assert not rewrite._is_kurama("KURAMA", ("org.gnome.Nautilus",))
    for t in ("Can you fix this sentence?", "Can you fix the format this sentence more good?", "proofread my email"):
        assert fastpath.match(t).tool == "rewrite_text", t
    assert fastpath.match("fix this error").tool == "fix_error"
