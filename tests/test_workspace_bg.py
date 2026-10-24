import time

from jarvis.core import config, jobs, registry, safety, stt, tts, workspace


def _reg(fn, name="slow_tool"):
    r = registry.Registry(packages=())
    r._discovered = True
    r.tool(fn, name=name, group="general")
    return r


def test_long_result_goes_to_workspace_with_note(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    reg = _reg(lambda query: "\n".join(f"/home/x/{i}/main.py" for i in range(30)), "find_things")
    shelf = []
    res = safety.execute("find_things", {"query": "main.py"}, reg=reg,
                         ctx={"user_text": "find main.py", "published": shelf, "jobs": []})
    assert res.ok and "workspace window" in res.output and len(shelf) == 1
    saved = (tmp_path / shelf[0]).read_text()
    assert saved.count("/main.py") == 30  # the full list, not the truncated copy
    tele_shelf = []
    tele = safety.execute("find_things", {"query": "x"}, reg=reg, ctx={"published": tele_shelf, "channel": "telegram"})
    assert "workspace" not in tele.output and "offer to send the whole list" in tele.output and tele_shelf == []
    whole = safety.execute("find_things", {"query": "x"}, reg=reg,
                           ctx={"published": [], "channel": "telegram", "full": True})
    assert whole.output.count("/main.py") == 30 and "send_last_result" in whole.output  # "the whole list"


def test_wants_all_and_send_last_result(tmp_path, monkeypatch):
    assert workspace.wants_all("please give me the whole list") and workspace.wants_all("send all of them")
    assert not workspace.wants_all("find main.py in my laptop")
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "1")
    from jarvis.core import notify
    from jarvis.tools.general import send_last_result as slr
    texts = []
    monkeypatch.setattr(notify, "telegram_send", lambda t, chat_id=None: texts.append(t) or True)
    assert slr.send_last_result().startswith("error")
    workspace.publish("find files: main.py", "a/main.py\nb/main.py")
    assert slr.send_last_result("list").endswith("as a message.") and "b/main.py" in texts[0]


def test_slow_tool_continues_as_background_job(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(config, "TOOL_BACKGROUND_AFTER_S", 0.2)

    def slow(x: str = "") -> str:
        time.sleep(0.8)
        return "scan finished: 3 big folders"
    reg = _reg(slow)
    started = []
    t0 = time.monotonic()
    res = safety.execute("slow_tool", {"x": "home"}, reg=reg, ctx={"user_text": "scan my disk", "jobs": started})
    assert time.monotonic() - t0 < 0.6 and "background as job #" in res.output and len(started) == 1
    job = jobs.get_manager().get(started[0])
    for _ in range(40):
        if job.status in ("done", "failed"):
            break
        time.sleep(0.1)
    assert job.status == "done" and "scan finished" in open(job.output_path).read()


def test_quick_tool_and_no_turn_context_stay_inline(monkeypatch):
    monkeypatch.setattr(config, "TOOL_BACKGROUND_AFTER_S", 0.2)
    reg = _reg(lambda x="": "ok")
    assert safety.execute("slow_tool", {}, reg=reg, ctx={"jobs": []}).output == "ok"
    assert workspace.offer("slow_tool", "a\n" * 20) == ""  # outside a dashboard turn: nothing published


def test_whisper_hallucinations_and_unspoken_text():
    assert stt.is_hallucination("Thank you for watching!")
    assert stt.is_hallucination("KURAMA, KURAMA, VS Code, Brave, YouTube, Kathmandu, Pokhara.")
    assert not stt.is_hallucination("open VS Code and YouTube")
    assert tts.clean_for_speech("• /home/leo/newproject/src/main.py") == ""
    assert tts.clean_for_speech("Saved job 1234567 ✅ to ~/a/b.md") == "Saved job to"
    assert tts.clean_for_speech("18% of 2500 = 450") == "18% of 2500 = 450"


def test_noise_gate_and_greeting_once(monkeypatch):
    assert stt.is_noise("uh huh", 0.8, -0.2)  # Whisper says: probably no speech
    assert stt.is_noise("the the", 0.1, -1.6)  # very unsure short phrase
    assert not stt.is_noise("open youtube and play some music", 0.1, -0.5)
    from fastapi.testclient import TestClient

    from jarvis.api.app import create_app
    from jarvis.api.routes import info
    from tests.test_api import BASE, settings
    monkeypatch.setattr(info, "_greeted", {"done": False})
    c = TestClient(create_app(settings()), base_url=BASE)
    first = c.get("/api/v1/greeting").json()["text"]
    assert " sir, " in first and len(first.split()) <= 10 and ":" not in first  # short, no clock
    assert c.get("/api/v1/greeting").json()["text"] == ""  # once per start


def test_wake_phrases():
    from jarvis.core import wake
    for t in ("wake up kurama", "wake off kurama", "wake up now kurama", "wake kurama", "kurama wake up", "hey kurama"):
        assert wake.match_wake(t).command == "", t
    assert wake.match_wake("wake up kurama open youtube").command == "open youtube"
    assert wake.match_wake("I need to wake up early") is None


def test_wake_service_publishes_wake(monkeypatch):
    import asyncio

    from jarvis.api.routes import wake as wr
    from jarvis.core import wake

    class Fake:
        def listen(self, stop):
            return wake.WakeEvent("hey kurama", "open youtube", "en")
    monkeypatch.setattr(wake, "WakeListener", Fake)
    svc = wr.WakeService()

    async def run():
        q = asyncio.Queue()
        svc.subs.append((asyncio.get_running_loop(), q))
        svc.start()
        return await asyncio.wait_for(q.get(), 3)
    ev = asyncio.run(run())
    assert ev == {"type": "wake", "heard": "hey kurama", "command": "open youtube", "lang": "en"}
