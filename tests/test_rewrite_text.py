from jarvis.core import fastpath, rewrite


def test_replaces_selection_in_place(monkeypatch):
    clip, keys = {"clipboard": "old clip"}, []
    monkeypatch.setattr(rewrite, "selection", lambda: "i cant come tomorow")
    monkeypatch.setattr(rewrite, "_xclip", lambda args, text=None: clip.__setitem__(args[1], text) or "" if text
                        is not None else clip.get(args[1], ""))
    monkeypatch.setattr(rewrite, "transform", lambda t, i: "I cannot come tomorrow.")
    monkeypatch.setattr(rewrite, "target_window", lambda: (123, True))
    monkeypatch.setattr(rewrite.time, "sleep", lambda s: None)
    from jarvis.core import uiagent
    monkeypatch.setattr(uiagent, "active_class", lambda: "brave-browser")
    monkeypatch.setattr(uiagent, "key", lambda k: keys.append(k))
    assert rewrite.rewrite("fix grammar") == "Replaced the selected text (4 words)."
    assert keys == ["ctrl+v"] and clip["clipboard"] == "old clip"  # user's clipboard restored


def test_no_selection_and_intents(monkeypatch):
    monkeypatch.setattr(rewrite, "selection", lambda: "")
    assert "Select the text first" in rewrite.rewrite("make it formal")
    assert fastpath.match("translate this to nepali").args == {"instruction": "translate to nepali"}
    assert fastpath.match("make it bigger").tool == "app_control"


def test_typed_in_dashboard_goes_back_to_document(monkeypatch):
    acts, keys = [], []
    monkeypatch.setattr(rewrite, "selection", lambda: "teh cat")
    monkeypatch.setattr(rewrite, "_xclip", lambda args, text=None: "")
    monkeypatch.setattr(rewrite, "transform", lambda t, i: "the cat")
    monkeypatch.setattr(rewrite, "target_window", lambda: (77, False))
    monkeypatch.setattr(rewrite, "_activate", lambda w: acts.append(w))
    monkeypatch.setattr(rewrite.time, "sleep", lambda s: None)
    from jarvis.core import uiagent
    monkeypatch.setattr(uiagent, "active_class", lambda: "libreoffice-writer")
    monkeypatch.setattr(uiagent, "key", lambda k: keys.append(k))
    assert rewrite.rewrite("fix grammar").startswith("Replaced") and acts == [77] and keys == ["ctrl+v"]
    assert rewrite._is_kurama("KURAMA - Brave", ("brave-browser",))
    assert rewrite._is_kurama("anything", ("kurama_wallpaper.py",))
    assert not rewrite._is_kurama("KURAMA", ("org.gnome.Nautilus",))  # a folder named KURAMA in Files
