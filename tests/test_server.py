"""Web test UI server: SSE chat, web confirmations, status, STT upload, localhost binding (no network, fake agent)."""
import io
import json
import shutil
import threading
import time
import wave

import pytest
from fastapi.testclient import TestClient

from jarvis import server
from jarvis.core import agent as agent_mod
from jarvis.core import config, safety, store, stt, tts
from jarvis.core.router import Route
from jarvis.ui import settings


class FakeAgent:
    """Mimics Agent.stream/.last: optional confirmation, a tool entry, two deltas."""

    def __init__(self, ask: str | None = None):
        self.ask = ask
        self.calls: list[tuple] = []
        self.last: dict = {}

    def stream(self, text, mode="text", lang=None):
        self.calls.append((text, mode, lang))
        self.last = {"tools": [], "route": Route(["general"], "rules", False, 1), "tier": "fast"}
        if self.ask:
            ok = safety.get_confirm(mode)(self.ask)
            self.last["tools"].append({"name": "delete_file", "ok": ok})
            yield "Done, deleted." if ok else "Okay, I left it alone."
            return
        store.log_tool("get_time", {}, True, 7)
        store.log_llm("openai/gpt-oss-20b", "chat", 10, 5, 0.1, True)
        self.last["tools"].append({"name": "get_time", "ok": True})
        yield "It is "
        yield "**noon**."


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(safety, "_HOOKS", dict(safety._HOOKS))  # keep the web hook out of other tests
    monkeypatch.setattr(server, "_hooked", False)
    monkeypatch.setattr(settings, "WARM_ON_START", False)
    return TestClient(server.app)


def use(monkeypatch, fake):
    monkeypatch.setattr(agent_mod, "get_agent", lambda: fake)
    return fake


def events(resp) -> list[dict]:
    return [json.loads(line[5:]) for line in resp.text.splitlines() if line.startswith("data:")]


def chat(client, text="what time is it?", **kw) -> list[dict]:
    r = client.post("/api/chat", json={"text": text, **kw})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    return events(r)


def test_chat_sse_sequence(client, monkeypatch):
    fake = use(monkeypatch, FakeAgent())
    evs = chat(client, mode="voice", lang="ne")
    assert [e["type"] for e in evs] == ["tool", "delta", "delta", "done"]
    assert evs[0] == {"type": "tool", "name": "get_time", "ok": True, "ms": 7}
    done = evs[-1]
    assert done["text"] == "It is **noon**."
    assert done["route"]["method"] == "rules" and done["route"]["groups"] == ["general"]
    assert done["tier"] == "fast" and done["tokens"] == 15 and done["ms"] >= 0
    assert fake.calls == [("what time is it?", "voice", "ne")]


def test_chat_rejects_empty_and_bad_mode(client, monkeypatch):
    fake = use(monkeypatch, FakeAgent())
    assert client.post("/api/chat", json={"text": "  "}).status_code == 400
    chat(client, "hi", mode="shell", lang="xx")
    assert fake.calls == [("hi", "text", None)]


def test_chat_error_becomes_event(client, monkeypatch):
    class Boom(FakeAgent):
        def stream(self, *a, **k):
            raise RuntimeError("kaput")
            yield ""
    use(monkeypatch, Boom())
    evs = chat(client)
    assert [e["type"] for e in evs] == ["error", "done"] and "kaput" in evs[0]["text"]


def test_confirm_yes_round_trip(client, monkeypatch):
    use(monkeypatch, FakeAgent(ask="Should I delete a file (path=/tmp/x)?"))
    answered = []

    def browser():
        for _ in range(200):
            if server._pending:
                cid = next(iter(server._pending))
                answered.append(client.post("/api/confirm", json={"id": cid, "yes": True}).json())
                return
            time.sleep(0.01)
    t = threading.Thread(target=browser)
    t.start()
    evs = chat(client, "delete the file /tmp/x")
    t.join(5)
    assert evs[0]["type"] == "confirm" and evs[0]["prompt"].startswith("Should I delete")
    assert answered == [{"ok": True, "yes": True}]
    assert {"type": "tool", "name": "delete_file", "ok": True, "ms": None} in evs
    assert evs[-1]["type"] == "done" and evs[-1]["text"] == "Done, deleted."
    assert server._pending == {}
    assert client.post("/api/confirm", json={"id": evs[0]["id"], "yes": True}).status_code == 404


def test_confirm_timeout_denies(client, monkeypatch):
    monkeypatch.setattr(settings, "CONFIRM_TIMEOUT_S", 0.2)
    use(monkeypatch, FakeAgent(ask="Should I run a shell command?"))
    evs = chat(client, "run rm -rf /tmp/x")
    types = [e["type"] for e in evs]
    assert types[:2] == ["confirm", "confirm_timeout"] and types[-1] == "done"
    assert evs[-1]["text"] == "Okay, I left it alone."


def test_web_hook_without_turn_denies(client):
    assert server.web_confirm("Should I?") is False


def test_status_shape(client, monkeypatch, tmp_path):
    wf = tmp_path / "workers.json"
    wf.write_text(json.dumps({"pid": 1, "workers": {"battery": {"state": "running"}}}))
    monkeypatch.setattr(config, "WORKERS_STATUS_PATH", wf)
    store.job_insert("essay about Nepal", "writing", status="running")
    store.alert_add("Battery low", "12% left", level="warn", source="battery")
    store.profile_set("name", "Leo")
    s = client.get("/api/status").json()
    for k in ("rss_mb", "agent_loaded", "agent_ready", "busy", "jobs", "alerts", "workers", "tokens", "profile_facts"):
        assert k in s
    assert s["rss_mb"] > 0 and s["busy"] is False
    assert s["jobs"][0]["title"] == "essay about Nepal" and s["jobs"][0]["status"] == "running"
    assert s["alerts"][0]["title"] == "Battery low" and s["alerts"][0]["level"] == "warn"
    assert s["workers"]["workers"]["battery"]["state"] == "running"
    assert "today" in s["tokens"] and s["profile_facts"] == 1


def _wav(rate=16000, seconds=0.2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x01" * int(rate * seconds))
    return buf.getvalue()


def test_stt_endpoint(client, monkeypatch):
    seen = {}

    def fake_transcribe(wav, language=None):
        seen.update(wav=wav, language=language)
        return stt.Transcript(text="what time is it", lang="en", model="fake")
    monkeypatch.setattr(stt, "transcribe", fake_transcribe)
    data = _wav()
    r = client.post("/api/stt?lang=hi", content=data, headers={"Content-Type": "audio/wav"})
    assert r.status_code == 200 and r.json() == {"text": "what time is it", "lang": "en"}
    assert seen == {"wav": data, "language": "hi"}  # already 16 kHz mono: passed through untouched
    assert client.post("/api/stt", content=b"").status_code == 400


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_stt_converts_with_ffmpeg(client, monkeypatch):
    got = []
    monkeypatch.setattr(stt, "transcribe", lambda wav, language=None: got.append(wav) or
                        stt.Transcript(text="ok", lang="en", model="fake"))
    assert client.post("/api/stt", content=_wav(rate=8000)).status_code == 200
    with wave.open(io.BytesIO(got[0])) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
    assert client.post("/api/stt", content=b"not audio at all" * 10).status_code == 400


def test_speak_endpoint(client, monkeypatch):
    spoken = []
    monkeypatch.setattr(tts, "speak", lambda text, block=True, **kw: spoken.append((text, block, kw)))
    assert client.post("/api/speak", json={"text": "Hello", "lang": "ne"}).json() == {"ok": True}
    assert spoken == [("Hello", False, {"lang": "ne"})]
    assert client.post("/api/speak", json={"text": ""}).status_code == 400


def test_page_and_static(client):
    r = client.get("/")
    assert r.status_code == 200 and "/app.js" in r.text and "Jarvis" in r.text
    assert client.get("/app.js").status_code == 200 and client.get("/style.css").status_code == 200
    assert client.get("/secrets.env").status_code == 404


def test_binds_localhost_only(monkeypatch):
    assert settings.HOST == "127.0.0.1"
    assert server.parse_args([]).port == settings.PORT
    ran = {}
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: ran.update(kw))
    monkeypatch.setattr(settings, "WARM_ON_START", True)
    assert server.main(["--port", "8123", "--no-warm"]) == 0
    assert ran["host"] == "127.0.0.1" and ran["port"] == 8123
