"""Owner 11-01: KURAMA reading the highlight or pasting a rewrite must leave the user's own clipboard as it was."""
from jarvis.core import rewrite, uiagent


def test_grab_and_put_give_the_clipboard_back(monkeypatch):
    clip = {"clipboard": "my own copied text"}

    def xclip(args, text=None):
        if text is None:
            return clip["clipboard"]
        clip["clipboard"] = text
        return ""

    def key(combo, times=1):
        if combo in ("ctrl+c", "ctrl+shift+c"):
            clip["clipboard"] = "the highlighted sentence"
    monkeypatch.setattr(rewrite, "_xclip", xclip)
    monkeypatch.setattr(uiagent, "key", key)
    monkeypatch.setattr(uiagent, "active_class", lambda: "brave-browser")
    monkeypatch.setattr(rewrite, "target_window", lambda: (7, True))
    monkeypatch.setattr(rewrite, "_from_editor", lambda wid, front: None)
    monkeypatch.setattr(rewrite, "_from_browser", lambda wid, front: None)
    monkeypatch.setattr(rewrite, "_window_name", lambda wid, limit=60: "Gemini - Brave")
    rewrite._SAVED_CLIP["text"] = None
    g = rewrite.grab()
    assert g.text == "the highlighted sentence" and clip["clipboard"] == "my own copied text"
    pasted = []
    monkeypatch.setattr(uiagent, "key", lambda combo, times=1: pasted.append(clip["clipboard"]))
    assert rewrite.put(g, "the better sentence")
    assert pasted == ["the better sentence"] and clip["clipboard"] == "my own copied text"
