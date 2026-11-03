"""The 7 learning gaps found on 11-03: channels mixed, a new task after a complaint taught as the fix, a failing
learned shortcut kept firing, late complaints lost, misheard speech counted as feedback, reply rules not reaching
every reply, multi-step replies never learned."""
import json
import time

import pytest

from jarvis.core import config, fastpath, learn, recipes, stt, style, taskgraph, trace
from tests.test_recipes import SONG1, approve, model, plain, save_trace, tool, turn  # noqa: F401 - the fixture

BATTERY = [tool("battery_status", {}, "Battery 93%")]


def judge(text, tools, tid, channel="", mode="text", path="ai"):
    learn._judge({**turn(text, tools, tid, path=path), "channel": channel, "mode": mode})


# ---- 1. each channel judges its own replies ----
def test_a_telegram_complaint_is_not_about_the_laptop_reply(model):
    approve("1aaa00000001", "what is the status of my battery charge", BATTERY)
    save_trace("1aaa00000002", "what is the status of my battery charge", path="fastpath", tools=BATTERY)
    judge("what is the status of my battery charge", BATTERY, "1aaa00000002", path="fastpath")  # laptop
    judge("galat", [], "1aaa00000003", channel="telegram")  # about something on Telegram
    assert recipes.find("what is the status of my battery charge") is not None
    judge("galat", [], "1aaa00000004")  # on the laptop: about the laptop's reply
    assert recipes.find("what is the status of my battery charge") is None


# ---- 2. a new task after a complaint is not the fix ----
@pytest.mark.parametrize("words,fix", [
    ("that's wrong, anyway open youtube", [tool("open_url", {"target": "youtube"}, "opened https://www.youtube.com")]),
    ("no that's not it, what is the weather in pokhara", [tool("weather", {"place": "pokhara"}, "Pokhara: 21°C")])])
def test_a_new_task_after_a_complaint_teaches_nothing(model, words, fix):
    web = [tool("web_search", {"query": "us mod se shurroo kare"}, "Results: ...")]
    save_trace("2aaa00000001", "bajau us mod se shurroo kare", tools=web)
    judge("bajau us mod se shurroo kare", web, "2aaa00000001")
    judge(words, fix, "2aaa00000002")
    assert [r for r in recipes.rows() if r.get("src") == "taught"] == []
    assert trace.feedback_rows()[0]["vote"] == -1  # still a 👎 for the reply


def test_the_real_fix_still_teaches(model):
    web = [tool("web_search", {"query": "us mod se shurroo kare"}, "Results: ...")]
    fix = [tool("music", {"action": "play", "query": "us mod se shurroo kare"}, "Playing Us Mod Se")]
    save_trace("2aaa00000003", "bajau us mod se shurroo kare", tools=web)
    judge("bajau us mod se shurroo kare", web, "2aaa00000003")
    judge("no, play it in the music player", fix, "2aaa00000004")
    assert recipes.match("bajau tum hi ho").tool == "music"


# ---- 3. a learned shortcut that fails is switched off ----
def test_a_failing_learned_shortcut_goes_to_the_ai_and_then_off(model, monkeypatch):
    from jarvis.core import safety
    from jarvis.core.registry import ToolResult
    monkeypatch.setattr(config, "FASTPATH", True)
    approve("3aaa00000001", "start the tune us mod se shurroo kare",
            [tool("music", {"action": "play", "query": "us mod se shurroo kare"}, "Playing Us Mod Se")])
    results = iter([ToolResult(True, "Playing Kesariya"), ToolResult(False, "error: mpv broke", "x"),
                    ToolResult(False, "error: mpv broke", "x")])
    monkeypatch.setattr(safety, "execute", lambda *a, **k: next(results))
    assert fastpath.try_answer("start the tune kesariya").answer.startswith("Playing Kesariya")
    assert fastpath.try_answer("start the tune kesariya") is None  # failed: the AI does it this time
    assert fastpath.try_answer("start the tune kesariya") is None
    r = recipes.rows()[0]
    assert not r["on"] and "failed 2 times" in r["off"] and recipes.find("start the tune kesariya") is None
    assert r["used"] == 1 and r["fails"] == 2


# ---- 4. a late complaint finds the reply it talks about ----
def test_a_late_complaint_finds_its_reply(model):
    old = time.time() - 3600
    for tid, text, ans in (("4aaa00000001", "open browser", "Sure, opening Firefox."),
                           ("4aaa00000002", "what is the weather in pokhara", "Pokhara: 21°C."),
                           ("4aaa00000003", "play some lofi music", "Playing lofi.")):
        save_trace(tid, text, path="fastpath", answer=ans, intent="open" if "browser" in text else "x")
        trace._db().execute("UPDATE traces SET ts = ? WHERE id = ?", (old, tid))
    learn._prev = {"": {**turn("play some lofi music", [], "4aaa00000003"), "ts": old}}
    judge("earlier you opened firefox when I said open browser, that was wrong", [], "4aaa00000004")
    rows = trace.feedback_rows()
    assert [(r["trace_id"], r["vote"]) for r in rows] == [("4aaa00000001", -1)]


def test_a_late_complaint_that_matches_nothing_clearly_does_nothing(model):
    save_trace("4bbb00000001", "what is the weather in pokhara", path="fastpath", answer="Pokhara: 21°C.")
    judge("no, I meant the other one", [], "4bbb00000002")  # no reply before it on this channel, nothing named
    assert trace.feedback_rows() == []


# ---- 5. misheard speech is never feedback ----
@pytest.mark.parametrize("lp,lang,counts", [(-0.89, "french", False), (-0.30, "korean", False),
                                            (-0.30, "english", True), (-0.55, "nepali", True)])
def test_spoken_praise_counts_only_when_heard_clearly(model, monkeypatch, lp, lang, counts):
    monkeypatch.setitem(stt._heard, "text", "perfect, that's exactly what i wanted")
    monkeypatch.setitem(stt._heard, "at", time.time())
    monkeypatch.setitem(stt._heard, "lp", lp)
    monkeypatch.setitem(stt._heard, "lang", lang)
    save_trace("5aaa00000001", "what is the status of my battery charge", tools=BATTERY)
    judge("what is the status of my battery charge", BATTERY, "5aaa00000001")
    judge("Perfect, that's exactly what I wanted", [], "5aaa00000002", mode="voice")
    assert bool(trace.feedback_rows()) is counts


def test_typed_words_are_always_clear():
    assert stt.heard_well("this was typed, not spoken")


# ---- 6. reply rules reach every reply ----
@pytest.mark.parametrize("said,rule", [("From now on, keep your answers short.", "keep your answers short"),
                                       ("Okay KURAMA, always reply to me in Nepali", "always reply to me in Nepali"),
                                       ("never use emojis in your replies please", "never use emojis in your replies please")])
def test_style_rules_by_meaning(model, monkeypatch, said, rule):
    monkeypatch.setattr(config, "FASTPATH", True)
    it = fastpath.match(said)
    assert it is not None and it.tool == "app_name" and it.args["action"] == "rule"
    assert style.add(it.args["command"]) == f"Got it. From now on: {rule}."
    assert rule in style.line()


@pytest.mark.parametrize("said", ["always open youtube at 9 am", "never mind", "remind me every day at 7"])
def test_not_style_rules(model, monkeypatch, said):
    monkeypatch.setattr(config, "FASTPATH", True)
    it = fastpath.match(said)
    assert it is None or it.args.get("action") != "rule"


def test_rules_replace_forget_and_stay_small():
    style.add("keep your answers short")
    style.add("keep your answers very short")  # a newer version of the same rule
    assert style.rules() == ["keep your answers very short"]
    for w in ("call me boss", "reply in nepali", "no emojis ever", "answer first then details", "speak slowly",
              "use simple words", "mention the time when relevant"):
        style.add(w)
    assert len(style.rules()) == config.STYLE_MAX and len(style.line()) <= config.STYLE_MAX_CHARS + 120
    assert "keep your answers very short" not in style.rules()  # the oldest went first
    assert style.forget("emojis").startswith("Forgot the rule") and style.forget("all").startswith("Forgot all")


def test_every_ai_reply_gets_the_rules():
    from jarvis.core.agent import Agent
    style.add("always call me boss")
    ag = Agent.__new__(Agent)
    ag.history, ag.summary, ag.persist, ag.channel = [], "", False, ""
    import threading
    ag._lock = threading.Lock()
    msgs = ag._messages("what is a black hole", "text", "en")
    assert "always call me boss" in str(msgs[-1].content) and str(msgs[-1].content).startswith("what is a black hole")


# ---- 7. multi-step replies ----
def test_thumbs_up_on_a_multi_step_reply_learns_each_step_and_the_plan(model):
    tools = [tool("open_url", {"target": "youtube"}, "opened https://www.youtube.com"),
             tool("open_url", {"target": "youtube"}, "opened https://www.youtube.com"),
             tool("battery_status", {}, "Battery 93%"),
             tool("music", {"action": "play", "query": "lofi beats"}, "Playing lofi")]
    plan = {"method": "llm", "tasks": [{"text": "open youtube on my laptop", "kind": "quick"},
                                       {"text": "play some lofi beats", "kind": "quick", "depends_on": []}]}
    save_trace("7aaa00000001", "open youtube on my laptop and then play some lofi beats", path="multi", tools=tools)
    trace._db().execute("UPDATE traces SET plan = ? WHERE id = ?", (json.dumps(plan), "7aaa00000001"))
    assert recipes.feedback("7aaa00000001", 1)["said"].startswith("Thanks! I'll")
    learned = {r["text"]: r["tool"] for r in recipes.rows() if r.get("on")}
    assert learned == {"play some lofi beats": "music", "open youtube on my laptop": "open_url"}  # the battery
    # call matched no task's words: not learned
    assert taskgraph.learned_plan("open youtube on my laptop and then play some lofi beats",
                                  ["open youtube on my laptop", "play some lofi beats"]) is not None


@pytest.mark.parametrize("said,what", [("forget the rule about calling me boss", "calling me boss"),
                                       ("Please remove my rule to reply in Nepali", "reply in Nepali"),
                                       ("clear all my rules", "all")])
def test_forget_a_rule_takes_no_tokens(monkeypatch, said, what):
    monkeypatch.setattr(config, "FASTPATH", True)
    it = fastpath.match(said)
    assert it.tool == "app_name" and it.args == {"action": "forget_rule", "command": what}


def test_rules_ride_on_the_request_itself():
    from jarvis.core.agent import Agent
    import threading
    style.add("always call me boss")
    ag = Agent.__new__(Agent)
    ag.history, ag.summary, ag.persist, ag.channel, ag._lock = [], "", False, "", threading.Lock()
    msgs = ag._messages("what is a comet", "text", "en")
    assert str(msgs[-1].content).rstrip().endswith("always call me boss.)") and "call me boss" not in str(msgs[0].content)
    style.forget("boss")
    last = str(ag._messages("what is a comet", "text", "en")[-1].content)
    assert "No longer follow: always call me boss" in last  # the chat's old replies still did it: say it stopped
