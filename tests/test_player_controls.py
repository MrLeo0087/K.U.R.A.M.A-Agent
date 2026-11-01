"""Basic music commands are 0 tokens: while KURAMA's player is on, a short request that MEANS a control controls it
('pause', 'continue', 'continue play'); 'volume maximum' is a number; and a next request ('play song' after 'pause
music') is never learned as a correction that vetoes the shortcut (11-01: 'pause music' cost ~1,000 tokens each)."""
import numpy as np
import pytest

from jarvis.core import config, fastpath, learn, music, semantic


@pytest.fixture
def player(monkeypatch):
    pick = {"label": "pause", "score": 0.97}
    monkeypatch.setattr(music, "running", lambda: True)
    monkeypatch.setattr(semantic, "ready", lambda: True)
    monkeypatch.setattr(semantic, "best_of", lambda t, name, table: (pick["label"], pick["score"]))
    return pick


@pytest.mark.parametrize("label,text,want", [
    ("pause", "pause", ("media_control", {"action": "pause"})),
    ("pause", "pause music bro", ("media_control", {"action": "pause"})),
    ("resume", "continue", ("media_control", {"action": "play"})),
    ("resume", "continue play", ("media_control", {"action": "play"})),
    ("next", "next one", ("media_control", {"action": "next"})),
    ("stop", "stop it", ("music", {"action": "stop", "query": ""})),
    ("volume_max", "volume max", ("music", {"action": "volume_set", "query": "100"})),
    ("volume_up", "louder", ("music", {"action": "volume_up", "query": ""}))])
def test_short_player_controls_by_meaning(player, label, text, want):
    player["label"] = label
    it = fastpath.match(text)
    assert it is not None and (it.tool, it.args) == want


def test_not_a_player_control(player, monkeypatch):
    player["label"], player["score"] = "other", 0.99  # 'continue the code', 'next tab', 'stop the timer'
    assert fastpath.player_intent("continue the code") is None
    player["label"], player["score"] = "resume", 0.70  # not close enough
    assert fastpath.player_intent("continue") is None
    player["score"] = 0.97
    assert fastpath.player_intent("continue writing the long essay about nepal now") is None  # not short
    monkeypatch.setattr(music, "running", lambda: False)  # no music of KURAMA's: 'continue' is something else
    assert fastpath.player_intent("continue") is None


@pytest.mark.parametrize("text,level", [("Set the volume maximum.", 100), ("full volume", 100), ("volume to max", 100),
                                        ("set volume to the highest", 100), ("brightness to lowest", 0),
                                        ("minimum brightness", 0), ("set volume 40%", 40)])
def test_max_and_min_are_numbers(text, level):
    it = fastpath._match(text)  # the real path: the text is normalised first ('Set the volume maximum.')
    assert it is not None and it.args == {"action": "set", "level": level}


def _vecs(monkeypatch, corr, plain):
    monkeypatch.setattr(learn, "_corr_vecs", np.array([[1.0, 0.0]]))
    monkeypatch.setattr(learn, "_not_vecs", np.array([[0.0, 1.0]]))
    monkeypatch.setattr(learn, "_embed", lambda t: np.array([corr, plain]))


def test_a_plain_next_request_is_not_a_correction(monkeypatch):
    _vecs(monkeypatch, 0.82, 1.0)  # "play song" after "pause music"
    assert learn.correction_score("play song") == 0.0
    _vecs(monkeypatch, 0.86, 0.863)  # "no I meant play the song": a tie still counts
    assert learn.correction_score("no I meant play the song") == pytest.approx(0.86)
    _vecs(monkeypatch, 1.0, 0.6)  # "that's wrong"
    assert learn.correction_score("that's wrong") == 1.0


def test_pause_then_play_teaches_nothing(monkeypatch):
    added = []
    monkeypatch.setattr(config, "LEARN", True)
    monkeypatch.setattr(config, "SEMANTIC_ROUTER", True)
    monkeypatch.setattr(learn, "add", lambda *a, **k: added.append(a))
    monkeypatch.setattr(learn, "correction_score", lambda t: 0.0)  # contrast says: a plain request
    monkeypatch.setattr(learn, "_prev", None)
    tools = [{"name": "media_control", "ok": True, "result": "Okay, paused."}]
    learn._judge({"text": "pause music", "ts": 100.0, "path": "fastpath", "intent": "media", "tools": tools})
    learn._judge({"text": "play song", "ts": 150.0, "path": "fastpath", "intent": "music",
                  "tools": [{"name": "music", "ok": True, "result": "Playing x."}]})
    assert added == []
