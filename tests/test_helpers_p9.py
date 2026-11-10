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
# --- slash commands --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,tool", [("/find attention pdf", "find_by_content"), ("/ytsum", "youtube_summary"),
                                       ("/push", "github_quick"), ("/newproject demo", "github_quick"),
                                       ("/reel how ai works", "explainer_video"), ("/phone ring", "phone_link"),
                                       ("/phone pair", "phone_link"),
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
        for text, tool in (("push my work", "github_quick"), ("share this to my phone", "phone_link"),
                           ("share this in mobile", "phone_link"), ("close my phone", "phone_link"),
                           ("summarize this youtube video", "youtube_summary"),
                           ("make a reel about how ai works", "explainer_video"),
                           ("find the pdf about attention i downloaded last week", "find_by_content")):
            it = fastpath.match(text)
            assert it is not None and it.tool == tool, text
    finally:
        semantic._tables.clear()


def test_a_file_goes_over_wifi_and_by_telegram_only_when_the_phone_is_away(tmp_path, monkeypatch):
    """Owner 11-10: 'share this in mobile' = KDE Connect (large files); the screen feature is gone."""
    from jarvis.tools.general import send_file_telegram as sft
    f = tmp_path / "big.mp4"
    f.write_bytes(b"0" * 1000)
    sent = []
    monkeypatch.setattr(phonelink, "reachable", lambda: True)
    monkeypatch.setattr(phonelink, "_send", lambda action, what: sent.append(action) or "📱 Sent big.mp4 over Wi-Fi")
    assert phonelink.share_file(str(f)).startswith("📱 Sent") and sent[0][0] == "--share-file"
    monkeypatch.setattr(phonelink, "reachable", lambda: False)
    monkeypatch.setattr(sft, "send_file_telegram", lambda p: "Sent by Telegram")
    assert "Telegram" in phonelink.share_file(str(f))
    assert not hasattr(phonelink, "screen")


def test_pairing_stops_the_duplicate_kde_program_and_says_the_firewall_step(monkeypatch):
    killed = []
    monkeypatch.setattr(phonelink.GSC.__class__, "exists", lambda self: True)
    monkeypatch.setattr(phonelink, "gsc_on", lambda wait_s=8.0: None)
    monkeypatch.setattr(phonelink, "devices", lambda: [])
    monkeypatch.setattr(phonelink.subprocess, "run", lambda argv, **k: killed.append(argv) or type("R", (), {
        "stdout": "3375\n" if argv[0] == "pgrep" else "", "returncode": 0})())
    out = phonelink.pair()
    assert "sudo ufw allow 1714:1764/udp" in out and "sudo apt remove kdeconnect" in out
    assert ["kill", "3375"] in killed



def test_share_means_kde_first_and_telegram_when_said(monkeypatch):
    """Owner 11-10: 'share this file' = KDE Connect (Telegram if it fails); 'telegram' said = Telegram."""
    from jarvis.core import focus
    from jarvis.core.intents import files
    monkeypatch.setattr(focus, "refer", lambda said="this": Path("/tmp/x.pdf"))
    monkeypatch.setattr(files, "_sendfile_intent", lambda t: fastpath.Intent("sendfile", "send_file_telegram", "telegram",
                                                                            {"path": "/tmp/x.pdf"}, "x.pdf"))
    assert files.sendfile_intent("share this file").tool == "phone_link"
    assert files.sendfile_intent("share this to my phone").tool == "phone_link"
    assert files.sendfile_intent("share this on telegram").tool == "send_file_telegram"
    assert files.sendfile_intent("send this folder to telegram").tool == "send_file_telegram"



def test_telegram_only_when_said(monkeypatch):
    """11-10 traces: 'send this image in my phone' / 'send this photo to my phone' went to Telegram."""
    from jarvis.core.intents import files
    monkeypatch.setattr(files, "_media_this", lambda kind: "/tmp/pic.png")
    for text in ("Send this image in my phone.", "share this image"):
        it = files.sendfile_intent(text)
        assert it is not None and it.tool == "phone_link" and it.args["value"] == "/tmp/pic.png", text
    assert files.sendfile_intent("send this photo to telegram").tool == "send_last_result"
    from jarvis.core import planner
    assert planner.split_clauses("No, no, do not use Telegram. Send in my phone.") == ["Send in my phone."]


def test_a_long_two_sentence_countdown_request_is_read_whole(monkeypatch):
    """11-10: 'my exam is exact 30 days later. Can you remind me every day 4 times ...' went to the AI (it listed
    the reminders): several sentences, but one request the fast path reads whole."""
    from jarvis.core import agent as ag
    from jarvis.core import planner
    monkeypatch.setattr(config, "FASTPATH", True)
    t = ("Actually, my exam is exact 30 days later. Can you remind me every day 4 times that your exam is scheduled "
         "in 30 days, 29 days, this type of.")
    it = fastpath.match(t)
    assert it.tool == "goals" and it.args["action"] == "add" and it.args["name"] == "exam"
    assert planner.is_multi(t) and "goals" in config.WHOLE_MESSAGE_TOOLS
    called = []
    monkeypatch.setattr(fastpath, "try_answer", lambda *a, **k: called.append(a[0]) or None)
    a = ag.Agent.__new__(ag.Agent)
    a.use_planner, a.confirm = True, None
    a._fast(t, "en", "voice")
    assert called == [t]
