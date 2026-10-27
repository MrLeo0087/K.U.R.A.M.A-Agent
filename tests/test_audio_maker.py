from jarvis.core import audiomaker, config, fastpath, tts


def test_mp3_from_text_file_and_voice(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    calls = []

    async def fake(text, voice, rate=None):
        calls.append((text, voice))
        yield b"ID3fake"
    monkeypatch.setattr(tts, "edge_synth", fake)
    p = audiomaker.make("# Title\nHello **world**. " + "More words here. " * 400, "hello")
    assert p.suffix == ".mp3" and p.read_bytes().startswith(b"ID3fake") and len(calls) > 1  # chunked by sentences
    assert "**" not in calls[0][0] and calls[0][1] == tts.voice_for("en")
    audiomaker.make("नमस्ते, म कुरामा हुँ।", "np")
    assert calls[-1][1] == tts.voice_for("ne")
    f = tmp_path / "notes.md"
    f.write_text("Read me")
    assert audiomaker.text_of(str(f)) == ("Read me", "notes")
    assert audiomaker.text_of("hello there")[0] == "hello there"


def test_routes():
    m = fastpath.match
    assert m("make an audio of this").args == {"source": "selection"}
    assert m("turn the last result into audio").args == {"source": "last"}
    assert m("make an audio of: hello my friend").args == {"source": "text", "text": "hello my friend"}
    assert m("/audio https://x.com/a").args["source"] == "https://x.com/a"
    assert m("convert this video to mp3").tool == "convert_file" and m("record audio") is None
