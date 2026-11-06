"""OCR (11-06): the vision model only reads, a text model translates line by line; 'meaning of this' right after
a read is the read text, 'the selected text' is the selection."""
from __future__ import annotations

from jarvis.core import llm, ocr, safety


class _R:
    def __init__(self, text):
        self.text = text


def test_needs_translation():
    assert ocr.needs_translation("நினைவு நல்லது வேண்டும்")
    assert ocr.needs_translation("నమస్కారం లోపలకు రండి")
    assert not ocr.needs_translation("Hello, please come in and sit down.")


def test_translate_line_by_line(monkeypatch):
    monkeypatch.setattr(llm, "chat", lambda *a, **k: _R("Language: Tamil\nநினைவு நல்லது வேண்டும்\n→ Think good thoughts."))
    lang, body = ocr.translate("நினைவு நல்லது வேண்டும்")
    assert lang == "Tamil" and body.endswith("→ Think good thoughts.")


def test_meaning_of_this_after_a_read(monkeypatch):
    from jarvis.core import assist, browsertab
    from jarvis.tools.general.text_assist import text_assist
    ocr.remember("நினைவு நல்லது வேண்டும்", "நினைவு நல்லது வேண்டும்\n→ Think good thoughts.", "Tamil")
    monkeypatch.setattr(browsertab, "_SEL", {**browsertab._SEL, "text": "", "ts": 0.0})
    monkeypatch.setattr(safety, "context", lambda: {"user_text": "What is the meaning of this in English?"})
    assert text_assist("meaning", lang="en").startswith("Tamil: ")
    seen = {}
    monkeypatch.setattr(assist, "run", lambda a, r, lang, rep, p, text: seen.setdefault("text", text) or "ok")
    monkeypatch.setattr(safety, "context", lambda: {"user_text": "what is the meaning of the selected text"})
    text_assist("meaning", lang="en")
    assert seen["text"] == ""  # the selection, as before
