from pathlib import Path

from jarvis.core import config, fastpath, llm, tts, videomaker
from jarvis.tools.general import generate_image as gi


def test_script_plan_and_render_mocked(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    sc = videomaker.script_scenes("Nepal has eight of the ten highest peaks in the world. Everest is the tallest. Tea.")
    assert sc and all(s["say"] and s["picture"] for s in sc)
    monkeypatch.setattr(llm, "chat", lambda *a, **k: type("R", (), {"text": '{"title": "x", "scenes": [{"say": "Hi.", '
                                                                          '"picture": "a hill"}, {"say": "Bye.", "picture": "a lake"}]}'})())
    assert [s["picture"] for s in videomaker.plan("hills")] == ["a hill", "a lake"]
    from PIL import Image
    Image.new("RGB", (64, 48), (200, 100, 50)).save(tmp_path / "p.png")
    monkeypatch.setattr(gi, "fetch_image", lambda *a, **k: (tmp_path / "p.png").read_bytes())

    async def fake(text, voice, rate=None):
        yield b""
    monkeypatch.setattr(tts, "edge_synth", fake)
    cmds = []
    def ff(args):
        cmds.append(args)
        Path(args[-1]).write_bytes(b"mp4")
    monkeypatch.setattr(videomaker, "_ffmpeg", ff)
    out = videomaker.render([{"say": "Hi.", "picture": "a hill"}, {"say": "", "picture": "a lake"}], "My Video", (320, 180))
    assert out.parent.name == "videos" and out.read_bytes() == b"mp4" and len(cmds) == 3 and cmds[-1][:2] == ["-f", "concat"]
    assert "anullsrc" in " ".join(cmds[1])  # a scene without words gets silence


def test_routes():
    m = fastpath.match
    # 11-10: a topic / script video is an explainer (slides + voice + captions); a folder is still a slideshow
    it = m("make a short video about the Himalayas")
    assert (it.tool, it.args) == ("explainer_video", {"topic": "the Himalayas", "format": "youtube"})
    assert m("make a reel about Nepali tea").args["format"] == "reel"
    assert m("make a slideshow from ~/Pictures/trip").args["folder"] == "~/Pictures/trip"
    assert m("/reel momo").args == {"format": "reel", "topic": "momo"}
    assert m("make a video call") is None and m("download this video").tool == "video_download"
