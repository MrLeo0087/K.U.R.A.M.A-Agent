"""The Nepal documents service: routed by meaning (not live search), asked in a background job, the answer parsed
from its server-sent events (the service is mocked)."""
from __future__ import annotations

import contextlib

from jarvis.core import config, nepaldocs, querykind


class FakeResp:
    headers = {"content-type": "text/event-stream; charset=utf-8"}

    def __init__(self, lines):
        self._lines = lines

    def raise_for_status(self):
        pass

    def iter_lines(self):
        yield from self._lines


class FakeClient:
    lines: list[str] = []
    asked: list[dict] = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @contextlib.contextmanager
    def stream(self, method, url, json=None, headers=None):
        FakeClient.asked.append({"url": url, "json": json, "key": (headers or {}).get("X-API-Key")})
        yield FakeResp(FakeClient.lines)


def test_ask_parses_the_stream(monkeypatch):
    import httpx
    monkeypatch.setattr(nepaldocs, "settings", lambda: ("http://rag.example", "k1"))
    monkeypatch.setattr(httpx, "Client", FakeClient)
    nepaldocs._cache.clear()
    FakeClient.lines = ['event: status', 'data: {"stage": "searching", "message": "Searching services documents"}', '',
                        'event: token', 'data: {"token": "The fee is "}', '', 'event: token', 'data: {"token": "Rs 10."}',
                        '', 'event: done', 'data: {"answer": "x", "sources": [{"title": "Citizenship Act 2063"}]}']
    seen = []
    out = nepaldocs.ask("What is the citizenship fee?", status=seen.append)
    assert out == "The fee is Rs 10.\n\nSources: Citizenship Act 2063"
    assert seen == ["Searching services documents"] and FakeClient.asked[-1] == {
        "url": "http://rag.example/ask", "json": {"query": "What is the citizenship fee?"}, "key": "k1"}
    FakeClient.lines = []
    assert nepaldocs.ask("what is the citizenship fee?") == out  # cached (no second call)


def test_routed_by_meaning_not_search(monkeypatch):
    from jarvis.core import lanes
    monkeypatch.setattr(querykind, "opening_kind", lambda text: None)
    monkeypatch.setattr(querykind, "again", lambda text: None)
    monkeypatch.setattr(lanes, "scores", lambda t: {"nepal": 0.95, "search": 0.7, "general": 0.6})
    it = querykind.route("what is the overspeeding rule in nepal")
    assert (it.tool, it.args) == ("nepal_docs", {"question": "what is the overspeeding rule in nepal"})
    monkeypatch.setattr(lanes, "scores", lambda t: {"nepal": 0.74, "search": 0.89})
    assert querykind.route("what is the latest news in nepal") is None  # live data: the usual web search
    assert querykind.nepal("नेपालको सबैभन्दा ठूलो जिल्ला कुन हो") and not querykind.nepal("आज को मौसम कस्तो छ")


def test_the_tool_runs_in_the_background(monkeypatch):
    from jarvis.core import jobs
    from jarvis.tools.general import nepal_docs as tool
    monkeypatch.setattr(nepaldocs, "settings", lambda: ("http://rag.example", "k"))
    monkeypatch.setattr(nepaldocs, "ask", lambda q, status=None: "Answer.")
    out = tool.nepal_docs("what is the divorce process")
    assert out.startswith("Looking that up in the Nepal documents (job #")
    job_id = int(out.split("#")[1].split(")")[0])
    for _ in range(50):
        j = jobs.get_manager().get(job_id)
        if j and j.status == "done":
            break
        import time
        time.sleep(0.05)
    assert j.status == "done" and j.progress == "» Answer."
    assert config.NEPAL_DOCS_CACHE_S >= 3600
