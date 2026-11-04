"""KURAMA HTTP API (jarvis.api): SSE chat, web confirmations, auth, CORS/origin/host guard, status,
STT/TTS, static frontend, and the jarvis.server shim. No network: fake agent, STT and edge-tts."""
import io
import json
import shutil
import threading
import time
import wave

import pytest
from fastapi.testclient import TestClient

from jarvis.api.app import create_app
from jarvis.api.settings import ROOT, Settings
from jarvis.core import agent as agent_mod
from jarvis.core import config, safety, store, stt, tts
from jarvis.core.router import Route

BASE = "http://127.0.0.1:8000"
ORIGIN = "http://localhost:5500"


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


def settings(**kw) -> Settings:
    base = dict(warm_on_start=False, cors_origins=[ORIGIN], allowed_hosts=["127.0.0.1", "localhost", "::1"],
                frontend_dir=ROOT / "frontend", serve_frontend=True)
    base.update(kw)
    return Settings(**base)


@pytest.fixture
def make(monkeypatch):
    monkeypatch.setattr(safety, "_HOOKS", dict(safety._HOOKS))  # keep the web hook out of other tests

    def _make(**kw) -> TestClient:
        return TestClient(create_app(settings(**kw)), base_url=BASE)
    return _make


@pytest.fixture
def client(make):
    return make()


def use(monkeypatch, fake):
    monkeypatch.setattr(agent_mod, "get_agent", lambda: fake)
    return fake


def events(resp) -> list[dict]:
    return [json.loads(line[5:]) for line in resp.text.splitlines() if line.startswith("data:")]


def chat(client, text="what time is it?", headers=None, **kw) -> list[dict]:
    r = client.post("/api/v1/chat", json={"text": text, **kw}, headers=headers or {})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    return events(r)


def engine(client):
    return client.app.state.engine


# --- chat + confirm ---
def test_chat_sse_sequence(client, monkeypatch):
    fake = use(monkeypatch, FakeAgent())
    evs = chat(client, mode="voice", lang="ne")
    assert [e["type"] for e in evs] == ["tool", "delta", "delta", "done"]
    assert evs[0] == {"type": "tool", "name": "get_time", "ok": True, "ms": 7}
    done = evs[-1]
    assert done["text"] == "It is **noon**." and done["lang"] == "ne"
    assert done["route"]["method"] == "rules" and done["route"]["groups"] == ["general"]
    assert done["tier"] == "fast" and done["tokens"] == 15 and done["ms"] >= 0
    assert fake.calls == [("what time is it?", "voice", "ne")]


def test_chat_rejects_empty_coerces_mode_and_detects_lang(client, monkeypatch):
    fake = use(monkeypatch, FakeAgent())
    assert client.post("/api/v1/chat", json={"text": "  "}).status_code == 400
    evs = chat(client, "hi", mode="shell", lang="xx")
    assert fake.calls == [("hi", "text", None)] and evs[-1]["lang"] == "en"


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
    eng, answered = engine(client), []

    def browser():
        for _ in range(300):
            if eng.pending:
                cid = next(iter(eng.pending))
                answered.append(client.post("/api/v1/confirm", json={"id": cid, "yes": True}).json())
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
    assert eng.pending == {}
    assert client.post("/api/v1/confirm", json={"id": evs[0]["id"], "yes": True}).status_code == 404


def test_confirm_timeout_denies(make, monkeypatch):
    client = make(confirm_timeout_s=0.2)
    use(monkeypatch, FakeAgent(ask="Should I run a shell command?"))
    evs = chat(client, "run rm -rf /tmp/x")
    types = [e["type"] for e in evs]
    assert types[:2] == ["confirm", "confirm_timeout"] and types[-1] == "done"
    assert evs[-1]["text"] == "Okay, I left it alone."


def test_web_hook_without_turn_denies(client):
    assert engine(client).web_confirm("Should I?") is False


# --- auth / CORS / guard ---
def test_token_auth(make, monkeypatch):
    use(monkeypatch, FakeAgent())
    client = make(token="s3cret")
    assert client.get("/api/v1/health").status_code == 200  # healthchecks stay open
    assert client.get("/api/v1/health").json()["auth"] is True
    assert client.get("/api/v1/status").status_code == 401
    assert client.get("/api/v1/status", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/v1/status", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert client.get("/api/v1/status?token=s3cret").status_code == 200
    assert client.post("/api/v1/chat", json={"text": "hi"}).status_code == 401
    assert chat(client, headers={"Authorization": "Bearer s3cret"})[-1]["type"] == "done"


def test_sse_status_stream_with_query_token(make):
    client = make(token="s3cret")
    with client.stream("GET", "/api/v1/status/stream") as r:
        assert r.status_code == 401
    with client.stream("GET", "/api/v1/status/stream?token=s3cret") as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        line = next(ln for ln in r.iter_lines() if ln.startswith("data:"))
    snap = json.loads(line[5:])
    assert "cpu" in snap and "ram" in snap


def test_cors_allowed_origin_and_blocked_origin(make):
    client = make(token="t")
    pre = client.options("/api/v1/chat", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST",
                                                  "Access-Control-Request-Headers": "authorization,content-type"})
    assert pre.status_code == 200 and pre.headers["access-control-allow-origin"] == ORIGIN
    r = client.get("/api/v1/health", headers={"Origin": ORIGIN})
    assert r.headers["access-control-allow-origin"] == ORIGIN
    r = client.get("/api/v1/status", headers={"Origin": ORIGIN})  # 401 still readable by the page
    assert r.status_code == 401 and r.headers["access-control-allow-origin"] == ORIGIN
    evil = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403 and "access-control-allow-origin" not in evil.headers
    assert client.get("/api/v1/health", headers={"Origin": BASE}).status_code == 200  # same origin


def test_guard_blocks_simple_posts_and_foreign_hosts(client, monkeypatch):
    use(monkeypatch, FakeAgent())
    r = client.post("/api/v1/chat", content='{"text":"hi"}', headers={"Content-Type": "text/plain"})
    assert r.status_code == 415
    assert client.post("/api/v1/stt", content=b"x" * 100, headers={"Content-Type": "text/plain"}).status_code == 415
    assert client.get("/api/v1/health", headers={"Host": "evil.example:8000"}).status_code == 400


# --- status / info ---
def test_status_shape(client, monkeypatch, tmp_path):
    wf = tmp_path / "workers.json"
    wf.write_text(json.dumps({"pid": 1, "workers": {"battery": {"state": "running"}}}))
    monkeypatch.setattr(config, "WORKERS_STATUS_PATH", wf)
    store.job_insert("essay about Nepal", "writing", status="running")
    store.alert_add("Battery low", "12% left", level="warn", source="battery")
    s = client.get("/api/v1/status?percpu=true").json()
    for k in ("cpu", "ram", "swap", "disk", "processes", "jarvis", "uptime", "workers", "jobs", "alerts", "tokens"):
        assert k in s
    assert 0 <= s["cpu"]["percent"] <= 100 and len(s["cpu"]["per_core"]) == s["cpu"]["count"]
    assert {"freq_ghz", "temp_c"} <= set(s["cpu"])
    assert s["cpu"]["freq_ghz"] is None or s["cpu"]["freq_ghz"] > 0
    assert s["cpu"]["temp_c"] is None or isinstance(s["cpu"]["temp_c"], float)
    assert s["net"]["rx_bps"] >= 0 and s["net"]["tx_bps"] >= 0
    assert s["ram"]["total_gb"] > 0 and set(s["ram"]) >= {"used_gb", "percent"}
    assert len(s["processes"]["by_rss"]) <= 5 and {"pid", "name", "rss_mb", "cpu"} <= set(s["processes"]["by_rss"][0])
    assert s["jarvis"]["rss_mb"] > 0 and s["jarvis"]["busy"] is False
    assert s["jobs"]["running"] == 1 and s["jobs"]["items"][0]["title"] == "essay about Nepal"
    assert s["alerts"]["unread"] == 1 and s["alerts"]["recent"][0]["level"] == "warn"
    assert s["workers"]["workers"]["battery"]["state"] == "running"
    assert "today" in s["tokens"]


def test_status_net_rate_is_a_delta(client, monkeypatch):
    from collections import namedtuple

    from jarvis.api import status as status_mod
    nic = namedtuple("nic", "bytes_recv bytes_sent")
    counters = iter([{"lo": nic(10**9, 10**9), "wlan0": nic(1000, 500)},
                     {"lo": nic(2 * 10**9, 2 * 10**9), "wlan0": nic(3000, 1500)}])
    clock = iter([100.0, 102.0])
    monkeypatch.setattr(status_mod.psutil, "net_io_counters", lambda pernic=False: next(counters))
    monkeypatch.setattr(status_mod.time, "monotonic", lambda: next(clock))
    col = status_mod.StatusCollector.__new__(status_mod.StatusCollector)
    col._net_prev = None
    assert col._net() == {"rx_bps": 0, "tx_bps": 0}
    assert col._net() == {"rx_bps": 1000, "tx_bps": 500}  # loopback ignored, per second


def test_jobs_alerts_profile(client):
    store.job_insert("scan", "scan", status="queued")
    store.alert_add("Hi", "there")
    store.profile_set("name", "Leo")
    assert client.get("/api/v1/jobs").json()["jobs"][0]["title"] == "scan"
    a = client.get("/api/v1/alerts").json()
    assert a["unread"] == 1 and a["alerts"][0]["title"] == "Hi"
    assert client.post("/api/v1/alerts/read", json={}).json() == {"ok": True}
    assert client.get("/api/v1/alerts").json()["unread"] == 0
    assert client.get("/api/v1/profile").json()["facts"][0] == {"key": "name", "value": "Leo", "source": "",
                                                                "updated": pytest.approx(time.time(), abs=60)}


def test_tools_listing(client):
    d = client.get("/api/v1/tools").json()
    assert d["count"] > 10
    names = {t["name"]: t["safety"] for g in d["groups"] for t in g["tools"]}
    assert all(v in ("safe", "confirm", "blocked") for v in names.values())


# --- audio ---
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
    r = client.post("/api/v1/stt?lang=hi", content=data, headers={"Content-Type": "audio/wav"})
    assert r.status_code == 200 and r.json() == {"text": "what time is it", "lang": "en"}
    assert seen == {"wav": data, "language": "hi"}  # already 16 kHz mono: passed through untouched
    assert client.post("/api/v1/stt", content=b"", headers={"Content-Type": "audio/wav"}).status_code == 400


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_stt_converts_with_ffmpeg(client, monkeypatch):
    got = []
    monkeypatch.setattr(stt, "transcribe", lambda wav, language=None: got.append(wav) or
                        stt.Transcript(text="ok", lang="en", model="fake"))
    assert client.post("/api/v1/stt", content=_wav(rate=8000), headers={"Content-Type": "audio/wav"}).status_code == 200
    with wave.open(io.BytesIO(got[0])) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
    bad = client.post("/api/v1/stt", content=b"not audio at all" * 10, headers={"Content-Type": "audio/webm"})
    assert bad.status_code == 400


def test_tts_streams_mpeg_per_sentence(client, monkeypatch):
    calls = []

    async def fake_synth(text, voice, rate=None):
        calls.append((text, voice))
        yield b"ID3" + text[:5].encode()
        yield b"|"
    monkeypatch.setattr(tts, "edge_synth", fake_synth)
    r = client.post("/api/v1/tts", json={"text": "Hello there. How are **you** today?", "lang": "ne"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"ID3Hello|ID3How a|"  # sentence order kept, markdown cleaned
    assert [c[1] for c in calls] == [config.VOICES["ne"]] * 2
    assert client.post("/api/v1/tts", json={"text": " "}).status_code == 400


def test_tts_failure_is_502(client, monkeypatch):
    async def broken(text, voice, rate=None):
        raise OSError("offline")
        yield b""
    monkeypatch.setattr(tts, "edge_synth", broken)
    r = client.post("/api/v1/tts", json={"text": "Hello."})
    assert r.status_code == 502 and "offline" in r.json()["error"]


# --- frontend + runner ---
def test_frontend_served_when_enabled(client):
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "app.js" in r.text and "KURAMA" in r.text
    for f in ("app.js", "orb.js", "voice.js", "api.js", "config.js", "styles.css"):
        assert client.get("/" + f).status_code == 200, f
    assert client.get("/docs").status_code == 200 and client.get("/openapi.json").status_code == 200


def test_frontend_not_served_when_disabled(make):
    client = make(serve_frontend=False)
    r = client.get("/")
    assert r.status_code == 200 and "text/html" not in r.headers["content-type"] and r.json()["docs"] == "/docs"
    assert client.get("/orb.js").status_code == 404


def test_server_shim_runs_api(monkeypatch):
    from jarvis import server
    from jarvis.core import privacy
    ran = {}
    import uvicorn
    monkeypatch.setattr(privacy, "harden", lambda *a, **k: ran.setdefault("hardened", True))
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: ran.update(kw, app=app))
    monkeypatch.delenv("JARVIS_API_HOST", raising=False)
    monkeypatch.delenv("JARVIS_API_TOKEN", raising=False)
    assert server.main(["--port", "8123", "--no-warm"]) == 0
    assert ran["host"] == "127.0.0.1" and ran["port"] == 8123
    assert ran["app"].state.settings.warm_on_start is False and ran["hardened"]
    ran.clear()
    assert server.main(["--host", "0.0.0.0", "--port", "8124"]) == 2 and "host" not in ran  # no token: refuse


def test_weather_card(client, monkeypatch):
    from jarvis.api.routes import info
    from jarvis.tools.general import _geo
    info._wx_cache.clear()
    monkeypatch.setattr(_geo, "geocode", lambda p: {"lat": 28.05, "lon": 81.62, "name": "Nepalgunj"})
    monkeypatch.setattr(_geo, "get_json", lambda u, q: {"current": {"temperature_2m": 31.2, "weather_code": 0,
                                                                    "is_day": 1}})
    items = client.get("/api/v1/weather").json()["items"]
    assert items[0]["place"] == "Nepalgunj" and items[0]["temp_c"] == 31.2 and items[0]["desc"]


def test_outputs_workspace(client, monkeypatch, tmp_path):
    from jarvis.core import config
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    (tmp_path / "images").mkdir()
    (tmp_path / "poem.md").write_text("# Poem\nroses", encoding="utf-8")
    (tmp_path / "images" / "fox.jpg").write_bytes(b"\xff\xd8\xff")
    items = client.get("/api/v1/outputs").json()["items"]
    assert {i["name"]: i["kind"] for i in items} == {"poem.md": "text", "images/fox.jpg": "image"}
    assert "roses" in client.get("/api/v1/outputs/file", params={"name": "poem.md"}).text
    assert client.get("/api/v1/outputs/file", params={"name": "../../.env"}).status_code == 404


def test_generate_image_job(monkeypatch, tmp_path):
    from jarvis.core import config, jobs
    from jarvis.tools.general import generate_image as gi
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(gi, "fetch_image", lambda p, w, h, **k: b"\x89PNG....")

    class Mgr:
        def submit(self, title, kind, fn, request="", lang="en"):
            class Ctx:
                def progress(self, _): pass
            self.out = fn(Ctx())
            return type("J", (), {"id": 7})()
    m = Mgr()
    monkeypatch.setattr(jobs, "get_manager", lambda: m)
    assert "job #7" in gi.generate_image(prompt="a red fox")
    assert m.out.endswith(".png") and (tmp_path / "images").is_dir()


def test_image_style_default_and_user_style():
    from jarvis.tools.general.generate_image import styled
    assert "cinematic vector" in styled("a tiger in the himalayas")
    assert styled("a tiger, watercolor") == "a tiger, watercolor"


def test_open_url_any_site_name():
    from jarvis.tools.general.open_url import find_site, resolve
    assert resolve("SoFiScore") == "https://www.sofascore.com"
    assert resolve("hamro patro") is None and find_site("hamro patro").startswith("https://duckduckgo.com/?q=")


def test_merge_open_replies_and_image_wallpaper_flow():
    from jarvis.core import fastpath, planner
    assert fastpath.merge_opens(["Sure, opening YouTube.", "Sure, opening Facebook."]) == [
        "Sure, opening YouTube and Facebook."]
    i = fastpath.match("generate the image of a coder workspace and make it as my wallpaper")
    assert i.tool == "generate_image" and i.args["set_as_wallpaper"] and "wallpaper" not in i.args["prompt"]
    assert len(planner.merge_tails([{"text": "draw a fox"}, {"text": "set it as my wallpaper"}])) == 1


def test_image_wallpaper_request_is_single():
    from jarvis.core import planner
    assert not planner.is_multi("generate the image of a calm workspace and very cinematic light and make it my wallpaper")


def test_metrics_prometheus_text(client):
    store.log_llm("openai/gpt-oss-20b", "chat", 10, 5, 0.1, True)
    r = client.get("/api/v1/metrics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert "# TYPE kurama_llm_calls_24h gauge" in r.text
    assert 'kurama_llm_tokens_24h{model="openai/gpt-oss-20b",kind="prompt"}' in r.text
    assert "process_resident_memory_bytes " in r.text
