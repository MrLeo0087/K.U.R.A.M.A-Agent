"""Plan 11-09 phase 9 helpers: find a document by what is inside, a YouTube video in 2 minutes, GitHub in one line,
explainer videos from a topic / script / voiceover, the phone from the laptop, short slash commands with suggestions."""
import json
import subprocess
import time
from pathlib import Path

import pytest

from jarvis.core import config, contentindex, explainer, fastpath, gitquick, phonelink, semantic, slash, ytsummary


# --- find by content -----------------------------------------------------------------------------------------------
def test_documents_are_found_by_what_is_inside(tmp_path, monkeypatch):
    docs = tmp_path / "Downloads"
    docs.mkdir()
    (docs / "paper.md").write_text("Self-attention relates positions of a sequence. Multi-head attention ...")
    (docs / "shop.txt").write_text("milk eggs bread")
    nb = {"cells": [{"source": ["# Training the CNN\n", "model.fit(x, y)"]}]}
    (docs / "train.ipynb").write_text(json.dumps(nb))
    monkeypatch.setattr(contentindex, "DB", tmp_path / "idx.db")
    monkeypatch.setattr(contentindex, "roots", lambda: [docs])
    assert contentindex.refresh()["total"] == 3
    hits = contentindex.search("the notes about attention")
    assert hits and hits[0]["path"].endswith("paper.md")
    assert contentindex.search("notebook where i trained the cnn")[0]["path"].endswith("train.ipynb")
    words, kind, since = contentindex.parse("the pdf about attention i downloaded last week")
    assert kind == "pdf" and since > time.time() - 9 * 86400 and '"attention"' in words
    (docs / "shop.txt").unlink()
    assert contentindex.refresh()["removed"] == 1


# --- YouTube ---------------------------------------------------------------------------------------------------------
def test_youtube_captions_are_read_once_each():
    vtt = ("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nhello there\n\n00:00:02.000 --> 00:00:04.000\nhello there\n"
           "general\n\n00:01:05.000 --> 00:01:07.000\nnext part")
    lines = ytsummary._vtt_lines(vtt)
    assert [t for _, t in lines].count("hello there") == 1 and lines[-1] == (65, "next part")
    assert ytsummary.video_id("https://www.youtube.com/watch?v=aircAruvnKk&t=3") == "aircAruvnKk"


# --- GitHub ----------------------------------------------------------------------------------------------------------
def test_push_asks_once_and_never_pushes_a_secret(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root)
    (root / "a.py").write_text("print(1)\n")
    monkeypatch.setattr(gitquick, "_message", lambda r, f: "Add a.py")
    asked = []
    out = gitquick.push(str(root), ask=lambda q: asked.append(q) or False)
    assert asked and "Add a.py" in asked[0] and out.startswith("OK, nothing")
    (root / ".env").write_text("KEY=1\n")
    assert gitquick.push(str(root), ask=lambda q: True).startswith("Stopped: .env")


# --- explainer video -------------------------------------------------------------------------------------------------
def test_scenes_keep_the_narration_and_voice_timing_follows_the_words():
    raw = '{"scenes": [{"title": "Attention", "points": ["a", "b"], "say": "First sentence."}, {"title": "x", "say": ""}]}'
    assert explainer._json(raw) == [{"title": "Attention", "points": ["a", "b"], "say": "First sentence."}]
    scenes = [{"say": "one two"}, {"say": "three four five six"}]
    segs = [{"start": 0.0, "end": 2.0, "text": "one two"}, {"start": 2.0, "end": 6.0, "text": "three four five six"}]
    d = explainer._durations_from_voice(scenes, segs, 6.0)
    assert abs(sum(d) - 6.0) < 0.6 and d[1] > d[0]


def test_a_slide_renders_both_shapes():
    for fmt in ("youtube", "reel"):
        img = explainer.slide(explainer.size_for(fmt), "How attention works", ["Queries", "Keys", "Values"], 2, 1, 3)
        assert img.size == explainer.size_for(fmt)


def test_the_explainer_tool_reads_a_voice_file_or_a_long_script(tmp_path, monkeypatch):
    from jarvis.core import jobs
    from jarvis.tools.general.explainer_video import explainer_video
    got = {}

    class M:
        def submit(self, title, kind, fn, req):
            got["fn"] = fn
            return type("J", (), {"id": 1})()
    monkeypatch.setattr(jobs, "get_manager", lambda: M())
    monkeypatch.setattr(explainer, "make", lambda topic, script, vo, fmt, progress: got.update(t=topic, s=script, v=vo, f=fmt) or Path("x.mp4"))
    voice = tmp_path / "me.mp3"
    voice.write_bytes(b"x")
    assert "your voice" in explainer_video(str(voice), format="reel")
    got["fn"](type("C", (), {"progress": lambda self, x: None})())
    assert got["v"] == str(voice) and got["f"] == "reel"


# --- phone -----------------------------------------------------------------------------------------------------------
def test_the_phone_link_says_what_is_missing(monkeypatch):
    monkeypatch.setattr(phonelink, "devices", lambda: [])
    monkeypatch.setattr(phonelink.shutil, "which", lambda x: None)
    assert "KDE Connect" in phonelink.ring() or "GSConnect" in phonelink.ring()
    monkeypatch.setattr(phonelink, "_scrcpy", lambda: "")
    assert "sudo snap install scrcpy" in phonelink.screen()


# --- slash commands --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,tool", [("/find attention pdf", "find_by_content"), ("/ytsum", "youtube_summary"),
                                       ("/push", "github_quick"), ("/newproject demo", "github_quick"),
                                       ("/reel how ai works", "explainer_video"), ("/phone ring", "phone_link"),
                                       ("/gpt what is a tensor", "ask_ai"), ("/glossary", "study")])
def test_every_new_helper_has_a_short_command(text, tool):
    it = fastpath.slash_intent(text)
    assert it is not None and it.tool == tool, text


def test_an_unknown_command_suggests_the_near_ones():
    assert fastpath.slash_intent("/phon").tool == "phone_link"  # a close spelling just runs it
    assert slash.suggest("vid")[:1] == ["/video"] and "/ytsum" in slash.suggest("youtub")
    assert "/list" in fastpath.slash_intent("/qwzx").args["en"]  # nothing near: the list
    names = [n for n, _ in slash.telegram_menu()]
    assert len(names) <= 100 and {"find", "phone", "push", "ask", "reel", "ytsum"} <= set(names)


def test_plain_words_reach_the_new_helpers(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    monkeypatch.setattr(config, "SEMANTIC_ROUTER", True)
    if not semantic.ensure_ready(30):
        pytest.skip("meaning model not available")
    from jarvis import agents
    monkeypatch.setattr(agents, "current", lambda: "general")
    semantic._tables.clear()
    try:
        for text, tool in (("push my work", "github_quick"), ("show my phone", "phone_link"),
                           ("open my phone", "phone_link"), ("close my phone", "phone_link"),
                           ("summarize this youtube video", "youtube_summary"),
                           ("make a reel about how ai works", "explainer_video"),
                           ("find the pdf about attention i downloaded last week", "find_by_content")):
            it = fastpath.match(text)
            assert it is not None and it.tool == tool, text
    finally:
        semantic._tables.clear()


def test_the_phone_port_is_found_again_after_it_changed(monkeypatch):
    """Wireless debugging gets a new port each time it is turned on: 'show my phone' finds it by itself."""
    monkeypatch.setattr(phonelink, "_open", lambda host, port, t=0.4: port == 41234)
    monkeypatch.setattr(phonelink.subprocess, "run", lambda argv, **k: type("R", (), {
        "stdout": "connected to 1.2.3.4:41234" if argv[-1].endswith(":41234") else "failed"})())
    assert phonelink.find_port("1.2.3.4:32935") == "1.2.3.4:41234"


def test_nothing_of_the_phone_link_stays_running(monkeypatch):
    """Owner 11-10: not a byte of RAM when not used: the window takes adb with it; 'close my phone' stops all."""
    ran = []
    monkeypatch.setattr(phonelink.subprocess, "run", lambda argv, **k: ran.append(argv) or type("R", (), {"returncode": 0})())
    monkeypatch.setattr(phonelink.shutil, "which", lambda x: f"/usr/bin/{x}")
    monkeypatch.setattr(phonelink, "_adb", lambda: "/usr/bin/adb")
    monkeypatch.setattr(phonelink.Path, "exists", lambda self: True)
    out = phonelink.close()
    assert "nothing of it runs now" in out
    assert any(a[-1] == "kill-server" for a in ran) and any("quit" in a for a in ran)
    src = (Path(phonelink.__file__)).read_text()
    assert 'kill-server >/dev/null 2>&1; exit $code' in src  # the screen window takes adb's server with it
