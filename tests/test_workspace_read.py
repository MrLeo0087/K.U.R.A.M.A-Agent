"""Short live answers (scores, prices) go straight to the chat; KURAMA can read its own workspace back;
Roman Nepali/Hindi sports questions reach the 0-token score lookup; Telegram /screen is answered at once."""
import threading
import time

from jarvis.core import config, fastpath, live, safety, workspace

SCORE = ("Arsenal (ESPN, live data as of 4:34 PM):\n"
         "Last result: Fleetwood Town 1-1 Arsenal (FT-Pens, today 1:45 AM, Carabao Cup)\n"
         "Goals: Aaron Loupalo-Bi 21', Viktor Gyökeres 50'\n"
         "Next: Liverpool vs Arsenal, Sun 01 Nov 10:15 PM, Premier League")


def _fake(monkeypatch, out):
    monkeypatch.setattr(safety, "execute", lambda name, args, **k: type("R", (), {"ok": True, "output": out(name, args),
                                                                                "error": ""})())


def test_brief():
    b = workspace.brief(SCORE)
    assert b.startswith("Arsenal: Last result: Fleetwood Town 1-1 Arsenal (FT-Pens, today 1:45 AM, Carabao Cup). Goals:")
    assert "\n" not in b and "ESPN" not in b
    assert workspace.brief("x\n" * 400) is None
    assert workspace.brief("Gold is Rs 242,800 per 10 g.\n(Sources: fenegosida.org)").endswith("\n(Sources: fenegosida.org)")


def test_team_from_roman_nepali():
    assert live.team_query("aja arsenal ko football match tyo .. result k vayo ?") == "arsenal"
    assert live.team_query("Arsenal football match result 28 October 2026") == "Arsenal"
    for q in ("aja arsenal ko football match tyo .. result k vayo ?", "aaj india ka match ka result kya hua"):
        assert fastpath.live_intent(q).args["kind"] == "sports"
    assert fastpath.live_intent("mero file k vayo") is None


def test_live_score_stays_in_chat(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FASTPATH", True)
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    _fake(monkeypatch, lambda n, a: SCORE)
    res = fastpath.try_answer("what is result of recent arsenal match ?")
    assert res.intent.name == "live" and "Fleetwood Town 1-1 Arsenal" in res.answer and "workspace" not in res.answer
    assert not (tmp_path / "answers").exists()


def test_reads_its_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FASTPATH", True)
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    workspace.publish("live search: arsenal", SCORE, folder="answers")
    assert workspace.read(1) == ("live search: arsenal", SCORE)
    from jarvis.tools.general.read_workspace import read_workspace
    out = read_workspace()
    assert out.startswith("Workspace item: live search: arsenal\n")
    _fake(monkeypatch, lambda n, a: read_workspace(**a))
    res = fastpath.try_answer("from workspace . give me sumamry .. what is result")
    assert res.intent.name == "wsread" and "Fleetwood Town 1-1 Arsenal" in res.answer
    workspace.publish("essay", "word " * 2000, folder="answers")  # long: the LLM summarizes it
    assert fastpath.try_answer("summarize the workspace") is None
    assert fastpath.match("launch my coding workspace") is None or fastpath.match("launch my coding workspace").tool != "read_workspace"


def test_telegram_screen_jumps_the_queue(monkeypatch):
    from jarvis.workers import telegram_bot as tb
    assert tb.is_fast("/screen") and tb.is_fast("/stop@kurama_bot") and not tb.is_fast("write an essay")
    bot = tb.TelegramBot()
    now = int(time.time())
    upd = [{"update_id": 1, "message": {"chat": {"id": config.TELEGRAM_CHAT_ID}, "date": now, "text": "/screen"}},
           {"update_id": 2, "message": {"chat": {"id": config.TELEGRAM_CHAT_ID}, "date": now, "text": "hello"}}]
    monkeypatch.setattr(bot, "poll", lambda timeout=None: [upd.pop(0)] if upd else [])
    handled = []
    monkeypatch.setattr(bot, "handle", lambda u, watch=True: handled.append(u["message"]["text"]))
    slow = threading.Thread(target=time.sleep, args=(0.6,))
    slow.start()
    bot._watch_while(slow, time.monotonic() + 5)
    assert handled == ["/screen"] and [u["message"]["text"] for u in bot._backlog] == ["hello"]
