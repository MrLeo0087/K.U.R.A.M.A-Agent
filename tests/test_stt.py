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
    assert r.model == "whisper-large-v3" and r.lang == "ne"


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


def _tr(text, lang, raw=None, lp=-0.2, model="m"):
    from jarvis.core import stt
    return stt.Transcript(text, lang, model, raw if raw is not None else lang, 1.0, 100, lp)


def test_dual_pass_language_arbitration():
    from jarvis.core import stt
    ne_forced = _tr("अहिले जापान मा मोसम कस्तो छ?", "ne", "ne", model="whisper-large-v3")
    # Nepali speech mislabeled English (word salad) or Slovak -> the Nepali-forced pass wins
    assert stt.choose(_tr("Oly, Japan, Ma, Mousim, Gusto, Zoh.", "en", "english", -0.9), ne_forced) is ne_forced
    assert stt.choose(_tr("Môže bota okého vid Zabán", "en", "slovak"), ne_forced).lang == "ne"
    # clean English stays on the auto pass
    en = _tr("What is the weather in Japan right now?", "en", "english", -0.17)
    assert stt.choose(en, _tr("What is the weather in Japan right now?", "ne")) is en
    # real Hindi stays Hindi
    hi = _tr("अभी जापान में मौसम कैसा है?", "hi", "hindi", -0.05)
    assert stt.choose(hi, _tr("अभी जापान में मौसम कैसा है?", "ne")) is hi
    assert stt.text_lang("नमस्ते, मेरा नाम जार्विस है। आज मौसम अच्छा है।") == "hi"
    assert stt.text_lang("मलाई नेपालमा अहिले कति बज्यो?") == "ne"


def test_dual_pass_runs_both_in_parallel(monkeypatch):
    from jarvis.core import config, stt
    monkeypatch.setattr(config, "STT_DUAL", True)
    calls = []

    def fake_one(wav, language, models):
        calls.append(language)
        return _tr("Oly, Japan, Ma", "en", "english", -0.9) if language is None else \
            _tr("अहिले जापानमा मौसम कस्तो छ?", "ne")
    monkeypatch.setattr(stt, "_one", fake_one)
    out = stt.transcribe(b"x")
    assert sorted(calls, key=str) == [None, "ne"] and out.lang == "ne"
