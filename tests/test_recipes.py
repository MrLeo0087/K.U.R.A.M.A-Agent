"""Learned shortcuts + kept answers (recipes.py): from 👍 / 👎 and clean repeats, with every safety guard."""
import json
import time

import pytest

from jarvis.core import config, fastpath, learn, recipes, semantic, trace
from jarvis.tools.general.learned_shortcuts import learned_shortcuts


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr(config, "SEMANTIC_ROUTER", True)
    monkeypatch.setattr(config, "LEARN", True)
    semantic._tables.clear()
    if not semantic.ensure_ready(30):
        pytest.skip("meaning model not available")
    monkeypatch.setattr(learn, "_rows", None)
    monkeypatch.setattr(learn, "_vecs", None)
    monkeypatch.setattr(learn, "_prev", None)
    recipes.reset_cache()
    yield
    semantic._tables.clear()


def tool(name, args, result="done", ok=True, **kw):
    return {"name": name, "args": args, "ok": ok, "outcome": "allowed", "result": result, **kw}


def turn(text, tools, tid, path="ai", tokens=1500):
    return {"text": text, "tools": tools, "path": path, "id": tid, "tokens": tokens, "ts": time.time()}


def save_trace(tid, text, path="ai", tools=(), answer="ok", intent="", tokens=1500):
    row = {"id": tid, "ts": time.time(), "day": "", "channel": "", "mode": "text", "text": text, "path": path,
           "intent": intent, "route_method": "", "route_groups": "", "tools_sent": "", "tools": json.dumps(list(tools)),
           "plan": "", "tier": "", "llm_calls": 1, "tokens_in": tokens, "tokens_out": 0, "tokens": tokens, "llm": "[]",
           "retried": 0, "asked": 0, "denied": 0, "jobs": "", "answer": answer, "ms": 900, "error": ""}
    trace._db().execute(f"INSERT INTO traces VALUES ({','.join('?' * len(row))})", list(row.values()))


SONG1 = [tool("music", {"action": "play", "query": "Us mod se shurroo kare Hindi song"}, "Playing Us Mod Se..."),
         tool("media", {"action": "play", "query": "Us mod se shurroo kare Hindi song"}, "Playing Us Mod Se...")]
SONG2 = [tool("music", {"action": "play", "query": "tum hi ho Hindi song"}, "Playing Tum Hi Ho")]


def test_two_clean_runs_make_a_slot_shortcut(model):
    recipes.observe(turn("play song us mod se shurroo kare", SONG1, "aaaaaa000001"))
    assert recipes.find("play song kesariya") is None  # a candidate only
    recipes.survived("aaaaaa000001")
    assert recipes.find("play song kesariya") is None  # 1 of 2
    recipes.observe(turn("play song tum hi ho", SONG2, "aaaaaa000002"))
    recipes.survived("aaaaaa000002")
    it = recipes.match("Play song Kesariya")
    assert it.tool == "music" and it.args == {"action": "play", "query": "Kesariya Hindi song"}
    assert len(recipes.rows()) == 1 and recipes.stats()["saved_today"] == 1500
    assert recipes.match("play the next video on youtube") is None  # another wording: not this template


@pytest.mark.parametrize("said,args", [("set the brightness to 70 percent", {"level": 70}),
                                       ("set the brightness to 5 percent", {"level": 5})])
def test_number_slot(model, said, args):
    t = [tool("brightness", {"action": "set", "level": 40}, "brightness 40%")]
    recipes.observe(turn("set the brightness to 40 percent", t, "bbbbbb000001"))
    recipes.survived("bbbbbb000001")
    recipes.survived("bbbbbb000001")  # the same request twice is still ONE proof
    assert recipes.find(said) is None
    recipes.observe(turn("set the brightness to 55 percent", [tool("brightness", {"action": "set", "level": 55})],
                         "bbbbbb000002"))
    recipes.survived("bbbbbb000002")
    assert recipes.match(said).args == {"action": "set", **args}


def test_thumbs_up_turns_it_on_at_once_and_fixed_args_need_the_same_words(model):
    t = [tool("battery_status", {}, "Battery 93%, discharging")]
    save_trace("cccccc000001", "what is the status of my battery charge", tools=t)
    assert recipes.feedback("cccccc000001", 1)["said"].startswith("Thanks! I'll answer")
    assert recipes.match("What is the status of my battery charge?").tool == "battery_status"
    assert recipes.find("what is the status of my phone battery charge") is None  # a new word: maybe another thing


@pytest.mark.parametrize("text,tools", [
    ("open this folder in vs code", [tool("open_path", {"path": "/home/leo/x", "app": "vscode"}, "opened x")]),
    ("set a timer for five minutes please", [tool("set_timer", {"minutes": 5}, "Timer set")]),
    ("delete the old report file now", [tool("delete_to_trash", {"path": "/a"}, "moved", safety="confirm")]),
    ("open youtube and lower the volume", [tool("open_url", {"target": "youtube"}), tool("audio", {"action": "down"})]),
    ("play some lofi music for me", [tool("music", {"action": "play", "query": "lofi"}, "error: no internet")]),
    ("send hello to my telegram please", [tool("send_message_telegram", {"text": "hello"}, "sent")]),
    ("play some calm music for studying", [tool("music", {"action": "play"},
                                                 "Still working after 3 s, so this keeps running in the background")]),
])
def test_never_learned(model, text, tools):
    recipes.observe(turn(text, tools, "dddddd000001"))
    assert recipes.rows() == []


def test_a_bare_slot_is_never_a_template(model):
    recipes.observe(turn("kesariya song by arijit", [tool("music", {"action": "play", "query": "kesariya song by arijit"})],
                         "eeeeee000001"))
    r = recipes.rows()[0]
    assert r["slots"] == {}  # the whole request = the argument: only the same request matches


def test_kept_answer_only_after_thumbs_up_and_never_for_live_questions(model):
    save_trace("ffffff000001", "why is the sky blue in one line", answer="Air scatters blue sunlight the most.")
    assert recipes.find("why is the sky blue in one line") is None
    recipes.feedback("ffffff000001", 1)
    it = recipes.match("Why is the sky blue, in one line?")
    assert it.name == "cached" and it.args["en"] == "Air scatters blue sunlight the most."
    assert recipes.find("why is the sky blue today in one line") is None
    save_trace("ffffff000002", "what is the latest news in nepal", answer="Some news.")
    recipes.feedback("ffffff000002", 1)
    assert [r for r in recipes.rows() if r["kind"] == "answer"] and len(recipes.rows("answer")) == 1


def test_thumbs_down_forgets_and_vetoes_the_shortcut(model):
    t = [tool("battery_status", {}, "Battery 93%")]
    save_trace("aabbcc000001", "what is the status of my battery charge", tools=t)
    recipes.feedback("aabbcc000001", 1)
    save_trace("aabbcc000002", "what is the status of my battery charge", path="fastpath", intent="learned",
               answer="Battery 93%")
    out = recipes.feedback("aabbcc000002", -1)
    assert out["ok"] and "won't answer it that way" in out["said"]
    assert recipes.find("what is the status of my battery charge") is None and recipes.rows() == []
    assert any(r["neg"] == "learned" for r in learn._load()[0])
    rows = trace.feedback_rows()
    assert [r["vote"] for r in rows] == [-1, 1]


def test_a_correction_drops_the_candidate(model):
    learn._judge(turn("play song us mod se shurroo kare", SONG1, "cdcdcd000001"))
    assert len(recipes.rows()) == 1
    learn._judge(turn("no, I meant something else", [], "cdcdcd000002", path="fastpath"))
    assert recipes.rows() == []


def test_unknown_trace_and_the_owner_tool(model):
    assert recipes.feedback("123456789abc", 1) == {"ok": False, "said": "I can't find that reply any more."}
    assert learned_shortcuts().startswith("Nothing learned yet")
    recipes.observe(turn("play song us mod se shurroo kare", SONG1, "abab00000001"))
    assert "waiting (0/2)" in learned_shortcuts("list")
    assert "Saved about 0 tokens today" in learned_shortcuts("stats")
    assert learned_shortcuts("forget", 1).startswith("Forgot") and recipes.rows() == []


def test_fastpath_uses_learned_shortcuts_last(model, monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    t1 = [tool("music", {"action": "play", "query": "us mod se shurroo kare"}, "Playing Us Mod Se")]
    t2 = [tool("music", {"action": "play", "query": "tum hi ho"}, "Playing Tum Hi Ho")]
    recipes.observe(turn("start the tune us mod se shurroo kare", t1, "efef00000001"))
    recipes.observe(turn("start the tune tum hi ho", t2, "efef00000002"))
    recipes.survived("efef00000001")
    recipes.survived("efef00000002")
    it = fastpath.match("start the tune kesariya")  # no built-in pattern knows this wording: the learned one
    assert it is not None and it.tool == "music" and it.args == {"action": "play", "query": "kesariya"}
    assert fastpath.match("what time is it").tool == "get_time"  # the built-in shortcuts still come first


# ---- a bad reply with no complaint: the owner just asks again another way ----
def test_re_asking_another_way_learns_nothing_from_the_first_reply(model):
    learn._judge(turn("open the web browser for me", [tool("open_app", {"name": "web browser"}, "opened Firefox")],
                      "rrrr00000001"))
    assert len(recipes.rows()) == 1
    learn._judge(turn("open the brave web browser for me", [tool("open_app", {"name": "brave"}, "opened Brave")],
                      "rrrr00000002"))
    assert all("rrrr00000001" not in r["traces"] for r in recipes.rows())  # Firefox one: gone, never confirmed


def test_next_song_is_not_a_re_ask(model):
    learn._judge(turn("play song us mod se shurroo kare", SONG1, "ssss00000001"))
    learn._judge(turn("play song tum hi ho", SONG2, "ssss00000002"))
    assert recipes.rows()[0]["ok"] == ["ssss00000001"]  # the first one counted as a clean run


@pytest.mark.parametrize("then", ["no, I meant something else", "open the battery settings app instead"])
def test_a_learned_shortcut_that_answered_wrongly_goes(model, then):
    t = [tool("battery_status", {}, "Battery 93%")]
    save_trace("abcd00000001", "what is the status of my battery charge", tools=t)
    recipes.feedback("abcd00000001", 1)
    assert recipes.find("what is the status of my battery charge") is not None
    learn._judge(turn("what is the status of my battery charge", [tool("battery_status", {}, "Battery 93%")],
                      "abcd00000002", path="fastpath"))  # served by the learned shortcut
    other = [tool("open_app", {"name": "battery settings"}, "opened Settings")]
    learn._judge(turn(then if then.startswith("no") else "show the status of my battery charge in settings", other,
                      "abcd00000003"))
    assert recipes.find("what is the status of my battery charge") is None
