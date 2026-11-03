import re
import time

import numpy as np

from jarvis.core import config, fastpath, learn, semantic


class FakeEmbedder:
    """Bag-of-words vectors: same words = similar (stands in for the ONNX model)."""
    loaded = True

    def embed(self, texts, query=False):
        out = []
        for t in texts:
            v = np.zeros(256, np.float32)
            for w in re.findall(r"[a-z]+", t.lower()):
                v[hash(w) % 256] += 1
            out.append(v / (np.linalg.norm(v) or 1))
        return np.array(out)


def _fake(monkeypatch, tmp_path):
    from jarvis.core import registry
    if not registry.REGISTRY.get("saved_links"):
        registry.REGISTRY.discover()
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "SEMANTIC_ROUTER", True)
    monkeypatch.setattr(semantic, "_embedder", FakeEmbedder())
    monkeypatch.setattr(semantic, "_index", None)
    monkeypatch.setattr(semantic, "mode", lambda: "auto")
    monkeypatch.setattr(learn, "_rows", None)
    monkeypatch.setattr(learn, "_prev", None)


def test_a_correction_teaches_the_area_and_stops_the_wrong_shortcut(monkeypatch, tmp_path):
    _fake(monkeypatch, tmp_path)
    monkeypatch.setattr(learn, "correction_score", lambda text: 1.0 if text.startswith("i mean") else 0.0)
    t = "get me this video"
    it = fastpath._match(t)
    assert it is not None and it.name == "vdl"  # the pattern alone downloads the video
    now = time.time()
    learn._judge({"text": t, "ts": now, "path": "fastpath", "intent": "vdl",
                  "tools": [{"name": "video_download", "ok": True}]})
    learn._judge({"text": "i mean play it in the music player", "ts": now + 20, "path": "ai", "intent": "music",
                  "tools": [{"name": "music", "ok": True, "args": {"action": "play", "query": "this video"}}]})
    rows = learn._load()[0]
    assert rows[-1]["text"] == t and rows[-1]["neg"] == "vdl" and rows[-1]["group"]
    assert not fastpath.meaning_ok(t, it)  # never downloads for this wording again
    assert fastpath.match(t) is None  # -> the AI, with the learned area offered first
    assert semantic.scores(t)[0][0] == rows[-1]["group"]


def test_silence_teaches_nothing_by_default(monkeypatch, tmp_path):
    """Owner 11-03: 'if I do nothing, do nothing' - a working AI request is NOT learned without a word from them."""
    _fake(monkeypatch, tmp_path)
    monkeypatch.setattr(learn, "correction_score", lambda text: 0.0)
    monkeypatch.setattr(learn, "praise_score", lambda text: 0.0)
    now = time.time()
    learn._judge({"text": "which process eats my ram", "ts": now, "path": "ai", "intent": "",
                  "tools": [{"name": "find_files", "ok": True, "result": "3 files"}]})
    learn._judge({"text": "open youtube", "ts": now + 20, "path": "fastpath", "intent": "open", "tools": []})
    assert learn._load()[0] == []


def test_a_working_ai_request_is_learned_and_old_turns_are_not_corrections(monkeypatch, tmp_path):
    _fake(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "LEARN_SILENT", True)  # the old silent learning, opt-in only
    monkeypatch.setattr(learn, "correction_score", lambda text: 1.0)
    now = time.time()
    learn._judge({"text": "which process eats my ram", "ts": now, "path": "ai", "intent": "top_processes",
                  "tools": [{"name": "find_files", "ok": True}]})
    learn._judge({"text": "no", "ts": now + 600, "path": "ai", "intent": "", "tools": []})  # 10 min later
    rows = learn._load()[0]
    assert len(rows) == 1 and rows[0]["src"] == "worked" and rows[0]["neg"] == ""


def test_only_real_successes_of_self_contained_wordings_are_learned(monkeypatch, tmp_path):
    """The AI's own picks were learned from 'remove it', 'food', 'yes' and from refused / question-back results,
    and then beat every other area forever (they match themselves at 1.0)."""
    _fake(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "LEARN_SILENT", True)  # the old silent learning, opt-in only
    monkeypatch.setattr(learn, "praise_score", lambda text: 0.0)
    monkeypatch.setattr(learn, "correction_score", lambda text: 0.7 if text.startswith("hmm") else 0.0)
    now = time.time()
    turns = [  # (request, tool result) -> none of these may be learned
        ("remove it", "Removed."), ("food", "ok"), ("yes", "Done."), ("give me that", "Sent."),
        ("create a folder called test in downloads", "The user declined: the folder was not created."),
        ("my budget for this month is two thousand", "How much should the monthly budget be?"),
        ("delete the old report file please", "error: no such file"),
    ]
    for i, (text, result) in enumerate(turns):
        learn._judge({"text": text, "ts": now + i, "path": "ai", "intent": "",
                      "tools": [{"name": "find_files", "ok": True, "result": result}]})
    learn._judge({"text": "which process eats my ram", "ts": now + 50, "path": "ai", "intent": "",
                  "tools": [{"name": "find_files", "ok": True, "result": "3 files"}]})
    learn._judge({"text": "hmm not quite what I wanted", "ts": now + 60, "path": "ai", "intent": "", "tools": []})
    assert learn._load()[0] == []  # the last one was followed by something close to a correction
    assert learn.standalone("which process eats my ram") and not learn.standalone("replace it")


def test_small_talk_only_when_the_whole_request_is_small_talk(monkeypatch, tmp_path):
    from jarvis.core import templates
    _fake(monkeypatch, tmp_path)
    monkeypatch.setattr(templates, "_st", None)
    assert templates.small_talk("thank you")["en"] == "Happy to help!"
    assert templates.small_talk("hello, what are you doing, and tell me the time") is None  # parts: time is told
    assert templates.small_talk("open the downloads folder") is None
