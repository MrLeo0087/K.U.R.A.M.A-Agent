"""Monitoring: one trace row per request with path, route, tools, AI calls, tokens, reply and time (MONITORING.md)."""
import json
import sqlite3

from langchain_core.messages import AIMessage

from jarvis.core import agent, config, trace
from tests.test_agent import call, fake  # noqa: F401  (fixture)


def rows():
    c = sqlite3.connect(str(config.TRACE_DB))
    c.row_factory = sqlite3.Row
    return [dict(r) for r in c.execute("SELECT * FROM traces ORDER BY ts")]


def test_ai_request_is_traced(fake):
    fake(call("get_time", {}, 1), AIMessage(content="It is noon."))
    assert agent.Agent().run("is it late already") == "It is noon."
    r = rows()[-1]
    assert (r["text"], r["path"], r["answer"], r["intent"]) == ("is it late already", "ai", "It is noon.", "get_time")
    assert r["llm_calls"] >= 1 and r["ms"] >= 0 and json.loads(r["tools"])[0]["name"] == "get_time"


def test_shortcut_is_traced_with_zero_tokens(monkeypatch):
    monkeypatch.setattr(config, "FASTPATH", True)
    agent.Agent().run("what time is it")
    r = rows()[-1]
    assert r["path"] == "fastpath" and r["tokens"] == 0 and r["route_method"] == "fastpath" and r["answer"]


def test_eval_runs_and_disabled_tracing_write_nothing(monkeypatch):
    agent.Agent(persist=False).run("what time is it")
    monkeypatch.setattr(config, "TRACING", False)
    agent.Agent().run("what time is it")
    assert not config.TRACE_DB.exists() or rows() == []


def test_calls_outside_a_request_are_ignored():
    import contextvars

    def worker():  # a background worker's thread: a fresh context, no current trace
        trace.on_llm("m", "agent", 10, 5, 3, True)
        return trace.current()
    assert contextvars.Context().run(worker) is None
    tr = trace.begin("x")
    trace.end(tr, "y")
    trace.on_llm("m", "agent", 10, 5, 3, True)  # after the request ended: not added
    assert len(tr["llm"]) == 0 and rows()[-1]["text"] == "x"


def test_report_finds_corrections_and_commands_without_tools(fake):
    import importlib.util
    spec = importlib.util.spec_from_file_location("trace_report", config.ROOT / "scripts" / "trace_report.py")
    tr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tr)
    fake(AIMessage(content="Done, bluetooth is off."), AIMessage(content="Sorry."))
    bot = agent.Agent()
    bot.run("turn off bluetooth")
    bot.run("no it didn't turn off")
    text = tr.report(tr.load(config.TRACE_DB, 1), 1)
    assert "2 requests" in text and "Likely mistakes" in text and "without any tool" in text
