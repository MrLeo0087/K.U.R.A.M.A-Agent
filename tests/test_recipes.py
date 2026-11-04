"""Learned shortcuts + kept answers (recipes.py): from 👍 / 👎 and clean repeats, with every safety guard."""
import json
import time

import pytest

from jarvis.core import config, fastpath, learn, mywords, recipes, semantic, trace
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


def plain(args):
    """A learned shortcut's arguments without its internal '_recipe' marker."""
    return {k: v for k, v in args.items() if k != "_recipe"}


def approve(tid, text, tools, path="ai", answer="ok"):
    """The owner's 👍 on a reply that is in the traces."""
    save_trace(tid, text, path=path, tools=tools, answer=answer)
    return recipes.feedback(tid, 1)


def said_next(prev_text, prev_tools, prev_id, words, words_tools=(), words_id="ffff00000999", prev_path="ai"):
    """A reply, then the owner's next message: learning judges the reply by those words."""
    save_trace(prev_id, prev_text, path=prev_path, tools=prev_tools)
    learn._judge(turn(prev_text, prev_tools, prev_id, path=prev_path))
    learn._judge(turn(words, list(words_tools), words_id))


# ---- nothing without the owner ----
def test_silence_never_turns_anything_on(model):
    said_next("play song us mod se shurroo kare", SONG1, "aaaa00000001", "what is the weather in pokhara")
    said_next("play song tum hi ho", SONG2, "aaaa00000002", "open youtube")
    assert recipes.find("play song kesariya") is None and [r for r in recipes.rows() if r.get("on")] == []


def test_thumbs_up_makes_a_slot_shortcut(model):
    assert approve("aaaa00000003", "play song us mod se shurroo kare", SONG1)["said"].startswith("Thanks! I'll")
    it = recipes.match("Play song Kesariya")
    assert it.tool == "music" and plain(it.args) == {"action": "play", "query": "Kesariya Hindi song"}  # 'play' stays fixed
    recipes.ran(it.args["_recipe"], True)  # what fastpath.try_answer reports after the tool worked
    assert recipes.stats()["saved_today"] == 1500
    assert recipes.match("play the next video on youtube") is None  # another wording: not this template


@pytest.mark.parametrize("words", ["perfect, that's exactly what I wanted", "good job kurama", "well done, that is right",
                                   "ramro garyau", "perfect, now open youtube", "excellent"])
def test_praise_in_the_next_message_is_a_thumbs_up(model, words):
    said_next("set the brightness to 40 percent", [tool("brightness", {"action": "set", "level": 40}, "brightness 40%")],
              "bbbb00000001", words)
    assert plain(recipes.match("set the brightness to 70 percent").args) == {"action": "set", "level": 70}
    assert trace.feedback_rows()[0]["vote"] == 1


@pytest.mark.parametrize("words", ["thanks", "thank you", "ok", "okay", "next"])
def test_politeness_is_not_praise(model, words):
    said_next("set the brightness to 40 percent", [tool("brightness", {"action": "set", "level": 40})],
              "bbbb00000002", words)
    assert recipes.rows() == [] and trace.feedback_rows() == []


def test_thumbs_up_fixed_args_need_the_same_words(model):
    approve("cccc00000001", "what is the status of my battery charge", [tool("battery_status", {}, "Battery 93%")])
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
def test_never_learned_even_with_a_thumbs_up(model, text, tools):
    approve("dddd00000001", text, tools)
    assert [r for r in recipes.rows() if r["kind"] == "tool"] == []


def test_a_bare_slot_is_never_a_template(model):
    approve("eeee00000001", "kesariya song by arijit", [tool("music", {"action": "play", "query": "kesariya song by arijit"})])
    assert recipes.rows()[0]["slots"] == {}  # the whole request = the argument: only the same request matches


def test_kept_answer_only_after_thumbs_up_and_never_for_live_questions(model):
    save_trace("ffff00000001", "why is the sky blue in one line", answer="Air scatters blue sunlight the most.")
    assert recipes.find("why is the sky blue in one line") is None
    recipes.feedback("ffff00000001", 1)
    it = recipes.match("Why is the sky blue, in one line?")
    assert it.name == "cached" and it.args["en"] == "Air scatters blue sunlight the most."
    assert recipes.find("why is the sky blue today in one line") is None
    approve("ffff00000002", "what is the latest news in nepal", [], answer="Some news.")
    assert len(recipes.rows("answer")) == 1


# ---- 👎 / complaints ----
def test_thumbs_down_forgets_and_vetoes_the_shortcut(model):
    approve("aabbcc000001", "what is the status of my battery charge", [tool("battery_status", {}, "Battery 93%")])
    save_trace("aabbcc000002", "what is the status of my battery charge", path="fastpath", intent="learned",
               answer="Battery 93%")
    out = recipes.feedback("aabbcc000002", -1)
    assert out["ok"] and out["said"] == "Noted as a bad reply."  # no correction forced on the owner
    assert recipes.find("what is the status of my battery charge") is None and recipes.rows() == []
    assert any(r["neg"] == "learned" for r in learn._load()[0])
    assert [r["vote"] for r in trace.feedback_rows()] == [-1, 1]


@pytest.mark.parametrize("words", ["no, I meant something else", "that's wrong", "galat"])
def test_a_complaint_in_the_next_message_is_a_thumbs_down(model, words):
    approve("abcd00000001", "what is the status of my battery charge", [tool("battery_status", {}, "Battery 93%")])
    said_next("what is the status of my battery charge", [tool("battery_status", {}, "Battery 93%")], "abcd00000002",
              words, prev_path="fastpath")  # served by the learned shortcut, then the complaint
    assert recipes.find("what is the status of my battery charge") is None
    assert trace.feedback_rows()[0]["vote"] == -1 and trace.feedback_rows()[0]["note"] == words


@pytest.mark.parametrize("words", ["no, play it in the music player", "you should use the music player for this",
                                   "wrong, play it in kurama's player not the browser"])
def test_a_correction_that_says_what_to_do_teaches_it(model, words):
    web = [tool("web_search", {"query": "us mod se shurroo kare"}, "Results: ...")]
    fix = [tool("music", {"action": "play", "query": "us mod se shurroo kare"}, "Playing Us Mod Se")]
    said_next("bajau us mod se shurroo kare", web, "abcd00000003", words, fix, "abcd00000004")
    it = recipes.match("bajau tum hi ho")  # the FIRST wording, any song: the tool the correction used
    assert it is not None and it.tool == "music" and plain(it.args) == {"action": "play", "query": "tum hi ho"}
    assert recipes.rows()[0]["src"] == "taught"


def test_a_complaint_after_a_failed_tool_is_not_a_veto(model):
    save_trace("abcd00000005", "pause the video please", path="fastpath", intent="media",
               tools=[tool("media_control", {"action": "pause"}, "error: no player found")])
    learn._judge(turn("pause the video please", [tool("media_control", {"action": "pause"}, "error: no player")],
                      "abcd00000005", path="fastpath"))
    learn._judge(turn("that's wrong", [], "abcd00000006"))
    assert not any(r["neg"] for r in learn._load()[0])  # the right shortcut that failed: a bug, not a wrong choice


# ---- the owner's own words, kept forever ----
@pytest.mark.parametrize("said,phrase,command", [
    ("when I say good night, lock the screen", "good night", "lock the screen"),
    ("Okay remember, whenever I say study time you should play lofi music", "study time", "play lofi music"),
    ("if I say 'movie mode', turn off the lights and mute the sound", "movie mode",
     "turn off the lights and mute the sound")])
def test_my_words_for_whole_commands(model, monkeypatch, said, phrase, command):
    monkeypatch.setattr(config, "FASTPATH", True)
    it = fastpath.match(said)
    assert it.tool == "app_name" and it.args == {"name": phrase, "command": command}
    mywords.save(it.args["name"], it.args["command"])
    assert mywords.expand(phrase.title() + ", Kurama!") == command and mywords.expand(f"{phrase} and more") != command
    assert phrase in mywords.all_words()


def test_one_meaning_per_word_and_forget(model, monkeypatch):
    from jarvis.tools.general import _apps
    monkeypatch.setattr(_apps, "index", lambda refresh=False: [
        {"id": "code", "path": "", "name": "Visual Studio Code", "generic": "", "keywords": [], "wmclass": "", "exe": "code"}])
    assert _apps.teach("code", "vs code").startswith("Got it")
    mywords.save("code", "open my project folder")
    assert "code" not in _apps.taught()  # the newest meaning wins
    _apps.teach("code", "vs code")
    assert "code" not in mywords.all_words()
    assert mywords.forget("nothing here").startswith("'nothing here' wasn't")


def test_unknown_trace_and_the_owner_tool(model):
    assert recipes.feedback("123456789abc", 1) == {"ok": False, "said": "I can't find that reply any more."}
    assert learned_shortcuts().startswith("Nothing learned yet")
    approve("abab00000001", "play song us mod se shurroo kare", SONG1)
    assert "· on ·" in learned_shortcuts("list")
    assert "Saved about 0 tokens today" in learned_shortcuts("stats")
    assert learned_shortcuts("forget", 1).startswith("Forgot") and recipes.rows() == []


def test_fastpath_uses_learned_shortcuts_last(model, monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    approve("efef00000001", "start the tune us mod se shurroo kare",
            [tool("music", {"action": "play", "query": "us mod se shurroo kare"}, "Playing Us Mod Se")])
    it = fastpath.match("start the tune kesariya")  # no built-in pattern knows this wording: the learned one
    assert it is not None and it.tool == "music" and plain(it.args) == {"action": "play", "query": "kesariya"}
    assert fastpath.match("what time is it").tool == "get_time"  # the built-in shortcuts still come first


def test_praise_after_a_lookup_that_finished_in_the_background(model):
    """Live 11-03: the AI's general 'web' call went to job #67 (only its note in the trace); the owner praised the
    answer that job announced -> the specialised tool behind it is learned, once the job is done."""
    from jarvis.core import store
    jid = store.job_insert("web: search", "tool", "")
    note = f"Still working after 3 s, so this keeps running in the background as job #{jid}. Tell the user..."
    tools = [tool("web", {"action": "wiki", "query": "Pokhara"}, note)]
    approve("baba00000001", "tell me the wikipedia summary of pokhara", tools)
    assert recipes.rows() == []  # the job hasn't finished: no proof it worked
    store.job_update(jid, status="done")
    approve("baba00000002", "tell me the wikipedia summary of pokhara", tools)
    r = recipes.rows()[0]
    assert r["tool"] != "web" and r["on"] and r["slots"]
