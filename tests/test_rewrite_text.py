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
    monkeypatch.setattr(rewrite, "_window_name", lambda w, limit=60: "ChatGPT - Brave")
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
        assert fastpath.match(t).tool == "text_assist", t
    assert fastpath.match("fix this error").tool == "fix_error"


def test_typed_request_uses_the_highlight_made_outside_kurama(monkeypatch):
    from jarvis.core import rewrite
    monkeypatch.setattr(rewrite, "_LAST", {"text": "", "wid": None, "title": "", "cls": "", "ts": 0.0,
                                           "kurama_newer": False, "watching": False})
    keys = []
    monkeypatch.setattr(rewrite, "target_window", lambda: (7, False))  # typed in KURAMA's chat
    monkeypatch.setattr(rewrite, "_activate", lambda wid: keys.append(("activate", wid)))
    monkeypatch.setattr("jarvis.core.uiagent.key", lambda k: keys.append(k))
    primary = {"v": "OAuth"}
    monkeypatch.setattr(rewrite, "selection", lambda: primary["v"])
    rewrite.remember_selection("OAuth", 42, "Login docs - Brave", "brave-browser Brave-browser", False)
    g = rewrite.grab()
    assert isinstance(g, rewrite.Grab) and g.text == "OAuth" and g.wid == 42 and g.title == "Login docs - Brave"
    assert keys == []  # no window switching, no Ctrl+C
    # then the user selects their own chat line inside KURAMA: PRIMARY is KURAMA's now, the outside word stays
    primary["v"] = "Hello KURAMA, how are you?"
    rewrite.remember_selection("", 9, "KURAMA", "kurama_wallpaper Kurama_wallpaper", True)
    assert rewrite.grab().text == "OAuth"
    # a new highlight out there replaces it
    rewrite.remember_selection("token", 43, "test.py - KURAMA - Visual Studio Code", "code Code", False)
    primary["v"] = "token"
    assert rewrite.grab().text == "token"
    # too old: back to the old way (switch to the window, copy there)
    rewrite._LAST["ts"] -= 3600
    monkeypatch.setattr(rewrite, "_xclip", lambda args, text=None: "")
    monkeypatch.setattr("jarvis.core.uiagent.active_class", lambda: "code")
    monkeypatch.setattr(rewrite, "_window_name", lambda wid, limit=60: "x")
    monkeypatch.setattr(rewrite.time, "sleep", lambda s: None)
    assert isinstance(rewrite.grab(), str) and ("activate", 7) in keys


def test_watcher_ignores_highlights_inside_kurama_and_secrets(monkeypatch):
    from jarvis.core import rewrite
    from jarvis.workers import clipboard_watch as cw
    got = []
    monkeypatch.setattr(rewrite, "remember_selection", lambda *a: got.append(a))
    monkeypatch.setattr(cw, "_xclip_sel", lambda sel, timeout=2.0: "Xk9#mPq2vL")  # looks like a password
    w = cw.ClipboardWatch()
    w._sel_win = (5, "KeePassXC", "keepassxc KeePassXC")
    w._read_selection()
    assert got == []
    w._sel_win = (6, "KURAMA", "kurama_wallpaper Kurama_wallpaper")
    w._read_selection()
    assert got[-1][-1] is True and got[-1][0] == ""  # inside KURAMA: only flagged, text not read
    monkeypatch.setattr(cw, "_xclip_sel", lambda sel, timeout=2.0: "serendipity")
    w._sel_win = (7, "Article - Brave", "brave-browser Brave-browser")
    w._read_selection()
    assert got[-1] == ("serendipity", 7, "Article - Brave", "brave-browser Brave-browser", False)
