from jarvis.core import dictation, fastpath


def test_commands_and_typing(monkeypatch):
    from jarvis.core import uiagent
    typed, keys = [], []
    monkeypatch.setattr(uiagent, "type_text", lambda t: typed.append(t))
    monkeypatch.setattr(uiagent, "key", lambda k: keys.append(k))
    assert dictation.handle_text("Hello world.")
    assert dictation.handle_text("new line") and dictation.handle_text("New paragraph.")
    assert not dictation.handle_text("Stop dictation.")
    assert typed == ["Hello world. "] and keys == ["Return", "Return Return"]


def test_intents_and_turn_gate():
    assert fastpath.match("dictate in nepali").args == {"action": "start", "lang": "ne"}
    assert fastpath.match("type what i say").tool == "dictate"
    assert fastpath.match("type hello world").tool == "app_control"
    assert fastpath.match("stop dictation").args == {"action": "stop"}
    assert not dictation.active()


def test_inline_commands(monkeypatch):
    from jarvis.core import uiagent
    ev = []
    monkeypatch.setattr(uiagent, "type_text", lambda t: ev.append(("t", t)))
    monkeypatch.setattr(uiagent, "key", lambda k: ev.append(("k", k)))
    assert dictation.handle_text("Hello Leo. New line. How are you?")
    assert not dictation.handle_text("That is all, stop dictation.")
    assert ev == [("t", "Hello Leo. "), ("k", "Return"), ("t", "How are you? "), ("t", "That is all "),]


def test_spoken_editing_commands(monkeypatch):
    from jarvis.core import uiagent
    keys = []
    monkeypatch.setattr(uiagent, "key", lambda k: keys.append(k))
    monkeypatch.setattr(uiagent, "type_text", lambda t: keys.append("TYPE " + t))
    for said in ("Change line.", "Please enter.", "Next line please", "Change the paragraph.", "Give space.",
                 "Press tab.", "Tab key", "Undo."):
        assert dictation.handle_text(said)
    assert keys == ["Return", "Return", "Return", "Return Return", "space", "Tab", "Tab", "ctrl+z"]
    keys.clear()
    dictation.handle_text("Thanks a lot. Change line. See you")
    assert keys == ["TYPE Thanks a lot. ", "Return", "TYPE See you "]
    assert dictation.command_for("Enter the room now") is None and dictation.command_for("Hello there") is None
