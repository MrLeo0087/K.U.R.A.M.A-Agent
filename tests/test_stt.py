from types import SimpleNamespace

import pytest

from jarvis.core import audio, config, llm, store, stt


class FakeTranscriptions:
    def __init__(self, fail_models=(), language="nepali", text=" नमस्ते "):
        self.fail_models, self.language, self.text, self.calls = set(fail_models), language, text, []

    def create(self, **kw):
        self.calls.append(kw)
        if kw["model"] in self.fail_models:
            raise RuntimeError("503 service unavailable")
        return SimpleNamespace(text=self.text, language=self.language, duration=1.0)


def client(tr):
    return SimpleNamespace(audio=SimpleNamespace(transcriptions=tr))


WAV = audio.pcm_to_wav(b"\x00\x00" * 16000)


def test_fallback_and_language(tmp_store):
    tr = FakeTranscriptions(fail_models={config.STT_MODEL})
    llm.set_client(client(tr))
    out = stt.transcribe(WAV)
    assert [c["model"] for c in tr.calls] == [config.STT_MODEL, config.STT_FALLBACK]
    assert tr.calls[0]["response_format"] == "verbose_json" and "language" not in tr.calls[0]
    assert (out.text, out.lang, out.model) == ("नमस्ते", "ne", config.STT_FALLBACK)
    rows = store._exec("SELECT model, purpose, ok FROM llm_calls ORDER BY id")
    assert [tuple(r) for r in rows] == [(config.STT_MODEL, "stt", 0), (config.STT_FALLBACK, "stt", 1)]


def test_all_fail_and_hallucination():
    llm.set_client(client(FakeTranscriptions(fail_models={config.STT_MODEL, config.STT_FALLBACK})))
    with pytest.raises(stt.STTError):
        stt.transcribe(WAV)
    llm.set_client(client(FakeTranscriptions(language="english", text="Thank you.")))
    out = stt.transcribe(WAV)
    assert out.text == "" and out.lang == "en"


def test_language_map():
    assert [stt.map_language(x) for x in ("English", "hindi", "nepali", "marathi", "french", None)] == \
        ["en", "hi", "ne", "ne", "en", "en"]
    assert abs(stt.wav_duration(WAV) - 1.0) < 1e-6


def test_nepali_hint_prefers_large_v3(monkeypatch):
    from unittest.mock import MagicMock
    from jarvis.core import config, llm, stt
    client = MagicMock()
    client.audio.transcriptions.create.return_value = {"text": "नमस्ते", "language": "nepali", "duration": 1.0}
    monkeypatch.setattr(llm, "get_client", lambda: client)
    r = stt.transcribe(b"x", language="ne")
    assert r.model == config.STT_FALLBACK and r.lang == "ne"


def test_mishearing_fixes_and_prompt(monkeypatch):
    from unittest.mock import MagicMock
    from jarvis.core import config, llm, stt
    assert stt.fix_text("Can you full screen the BS code?") == "Can you full screen the VS Code?"
    assert stt.fix_text("split Brave and Bear Skull") == "split Brave and VS Code"
    assert stt.fix_text("Hey Karama, open versus code") == "Hey Kurama, open VS Code"
    assert stt.fix_text("my vs account") == "my vs account"  # untouched
    client = MagicMock()
    client.audio.transcriptions.create.return_value = {"text": "open bs code", "language": "english"}
    monkeypatch.setattr(llm, "get_client", lambda: client)
    r = stt.transcribe(b"x")
    assert r.text == "open VS Code"
    assert client.audio.transcriptions.create.call_args.kwargs["prompt"] == config.STT_PROMPT
