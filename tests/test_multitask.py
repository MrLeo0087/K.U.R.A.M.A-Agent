"""P3b-2 multitasking: planner, fan-out, jobs, rate limiter, writer, job tools, open_url (all mocked)."""
import threading
import time
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

from jarvis.core import agent, config, jobs, llm, planner, ratelimit, registry, router, store, writer


class Responder(BaseChatModel):
    """Fake chat model: fn(messages, kw) -> AIMessage. Thread-safe (no shared script)."""

    fn: Any = None
    model_id: str = "fake"

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, tool_choice=None, **kw):
        return self.bind(tools=[convert_to_openai_tool(t) for t in tools], tool_choice=tool_choice)

    def _generate(self, messages, stop=None, run_manager=None, **kw: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self.fn(messages, kw, self.model_id))])


def tool_names(kw) -> list[str]:
    return [t["function"]["name"] for t in kw.get("tools") or []]


def last_human(messages) -> str:
    return next(m.content for m in reversed(messages) if isinstance(m, HumanMessage))


@pytest.fixture
def respond(monkeypatch):
    def install(fn):
        monkeypatch.setattr(llm, "model_for", lambda m: Responder(model_id=m, fn=fn))
    return install


def usage(p=10, c=20):
    return {"input_tokens": p, "output_tokens": c, "total_tokens": p + c}


# --- planner detection ---
@pytest.mark.parametrize("text", [
    "what time is it?", "Hi KURAMA, how are you today?", "Explain in detail how a car engine works.",
    "what's the difference between rice and wheat", "तिमी को हौ?", "search rock and roll",
    "अहिले कति बज्यो", "kitne baje hain?"])
def test_single_intent_needs_no_llm(text, monkeypatch):
    monkeypatch.setattr(llm, "structured", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM")))
    p = planner.plan(text)
    assert p.method == "single" and len(p.tasks) == 1 and p.tasks[0]["kind"] == "quick"


@pytest.mark.parametrize("text", [
    "write a 300-word essay about Nepal and open YouTube",
    "open youtube then tell me the time",
    "youtube kholo aur ek nibandh likho",  # hi romanized
    "यूट्यूब खोलो और एक निबंध लिखो",  # hi Devanagari
    "युट्युब खोल अनि नेपालको बारेमा निबन्ध लेख",  # ne Devanagari
    "open youtube ani time bata",  # ne romanized
])
def test_multi_intent_flagged(text):
    assert planner.is_multi(text)


def test_long_job_heuristic():
    assert planner.is_long_job("write a 2000-word essay about Nepal")
    assert planner.is_long_job("write a thousand-line essay about Nepal")
    assert planner.target_words("a thousand-line essay") == 1000 * config.WORDS_PER_LINE
    assert planner.is_long_job("write a python script for a snake game")
    assert planner.is_long_job("scan the whole repo for bugs")
    assert not planner.is_long_job("write a short story about a cat")
    assert not planner.is_long_job("write a 50-word poem")
    assert not planner.is_long_job("tell me a story")
    assert planner.title_of("write a 300-word essay about Nepal") == "essay about Nepal"
    single = planner.plan("write a 2000-word essay about Nepal")
    assert single.method == "single" and single.tasks[0]["kind"] == "long"


def test_structured_decomposition_with_fake_model(respond):
    seen = []

    def fn(messages, kw, model):
        seen.append((model, tool_names(kw)))
        return AIMessage(content="", usage_metadata=usage(), tool_calls=[{
            "id": "p1", "name": "TaskPlan", "args": {"tasks": [
                {"text": "write a 300-word essay about Nepal", "kind": "long"},
                {"text": "open YouTube", "kind": "quick"}]}}])
    respond(fn)
    p = planner.plan("write a 300-word essay about Nepal and open YouTube")
    assert p.method == "llm"
    assert [t["kind"] for t in p.tasks] == ["long", "quick"]
    assert seen == [(config.LLM_FAST, ["TaskPlan"])]
    row = store._exec("SELECT purpose, total_tokens FROM llm_calls")[0]
    assert (row["purpose"], row["total_tokens"]) == ("planner", 30)


def test_decomposition_failure_falls_back_to_rules(monkeypatch):
    monkeypatch.setattr(llm, "structured", lambda *a, **k: (_ for _ in ()).throw(llm.LLMError("down")))
    p = planner.plan("write a 300-word essay about Nepal and open YouTube")
    assert p.method == "rules"
    assert p.tasks == [{"text": "write a 300-word essay about Nepal", "kind": "long"},
                       {"text": "open YouTube", "kind": "quick"}]


# --- fan-out ---
@pytest.fixture
def slow_tools(monkeypatch):
    for name in ("slow_alpha", "slow_beta"):
        def f(name=name) -> str:
            time.sleep(0.5)
            return f"{name} ok"
        f.__name__ = name
        registry.tool(group="testslow", description=f"slow {name}")(f)
    monkeypatch.setattr(router, "route", lambda text, log_it=True: router.Route(["testslow"], "rules"))
    yield
    for name in ("slow_alpha", "slow_beta"):
        registry.REGISTRY.tools.pop(name, None)


def test_fanout_runs_quick_tasks_concurrently(respond, slow_tools, monkeypatch):
    monkeypatch.setattr(planner, "plan", lambda text: planner.Plan(
        [{"text": "do alpha", "kind": "quick"}, {"text": "do beta", "kind": "quick"}], "llm"))

    def fn(messages, kw, model):
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content=f"Finished {messages[-1].name}.")
        which = "slow_alpha" if "alpha" in last_human(messages) else "slow_beta"
        return AIMessage(content="", tool_calls=[{"id": which, "name": which, "args": {}}])
    respond(fn)
    bot = agent.Agent()
    t0 = time.monotonic()
    answer = bot.run("do alpha and do beta")
    dt = time.monotonic() - t0
    assert answer == "Finished slow_alpha. Finished slow_beta."
    assert dt < 1.0, f"tasks ran sequentially ({dt:.2f}s)"
    assert len(bot.history) == 2 and bot.history[0].content == "do alpha and do beta"


def test_long_task_goes_to_job_manager_and_returns_at_once(respond, monkeypatch):
    from jarvis.tools.general import open_url
    opened: list[str] = []
    monkeypatch.setattr(open_url, "_open", opened.append)
    gate = threading.Event()

    def fake_writer(ctx, request, lang="en", kind="write"):
        gate.wait(5)
        return None
    monkeypatch.setattr(writer, "run", fake_writer)
    monkeypatch.setattr(planner, "decompose", lambda text: [
        {"text": "write a 300-word essay about Nepal", "kind": "long"},
        {"text": "open YouTube", "kind": "quick"}])

    def fn(messages, kw, model):
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content="YouTube is open.")
        assert "open_url" in tool_names(kw)
        return AIMessage(content="", tool_calls=[{"id": "o1", "name": "open_url", "args": {"target": "youtube"}}])
    respond(fn)
    t0 = time.monotonic()
    answer = agent.Agent().run("write a 300-word essay about Nepal and open YouTube")
    assert time.monotonic() - t0 < 1.0
    assert answer.lower().startswith(("youtube is open.", "sure, opening youtube.")) and 'Writing "essay about Nepal"' in answer
    assert opened == ["https://www.youtube.com"]
    job = jobs.get_manager().list()[0]
    assert job.status in ("queued", "running") and job.title == "essay about Nepal"
    gate.set()
    assert jobs.get_manager().wait(job.id, 5).status == "done"
    assert store.job_get(job.id)["status"] == "done"


def test_single_long_request_becomes_job(respond, monkeypatch):
    monkeypatch.setattr(writer, "run", lambda ctx, request, lang="en", kind="write": None)
    respond(lambda *a: (_ for _ in ()).throw(AssertionError("no LLM call expected")))
    answer = agent.Agent().run("write a 2000-word essay about Nepal")
    assert "job #1" in answer and "essay about Nepal" in answer


def test_time_question_makes_no_planner_call(respond):
    calls = []

    def fn(messages, kw, model):
        calls.append(tool_names(kw))
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content="It is noon.")
        return AIMessage(content="", tool_calls=[{"id": "t", "name": "get_time", "args": {}}])
    respond(fn)
    bot = agent.Agent()
    assert bot.run("what time is it?") == "It is noon."
    assert bot.last["plan"]["method"] == "single" and "TaskPlan" not in sum(calls, [])
    assert not store._exec("SELECT 1 FROM llm_calls WHERE purpose='planner'")


def test_join_reply_in_nepali():
    assert "पृष्ठभूमिमा" in agent.job_started_text(3, "निबन्ध", "write", "ne")
    assert "job #3" in agent.job_started_text(3, "essay", "write", None)


# --- rate limiter ---
@pytest.fixture
def clock(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(ratelimit, "_clock", lambda: t[0])
    monkeypatch.setattr(config, "MODEL_TPM", 1000)
    monkeypatch.setattr(config, "MODEL_RPM", 100)
    ratelimit.reset()
    return t


def test_background_keeps_reserve_for_interactive(clock):
    ratelimit.acquire("m", 650, "interactive")  # 350 left
    done = threading.Event()

    def bg():
        ratelimit.acquire("m", 100, "background")  # 350-100 < 300 reserve: must wait
        done.set()
    th = threading.Thread(target=bg, daemon=True)
    th.start()
    time.sleep(0.3)
    assert not done.is_set()
    t0 = time.monotonic()
    ratelimit.acquire("m", 100, "interactive")  # still fits: no wait
    assert time.monotonic() - t0 < 0.05
    clock[0] += 30  # refill 500 tokens
    assert done.wait(2)


def test_background_wait_is_cancellable(clock):
    ratelimit.acquire("m", 900, "interactive")
    ev = threading.Event()
    ev.set()
    with pytest.raises(ratelimit.Cancelled):
        ratelimit.acquire("m", 100, "background", cancel=ev)


def test_settle_and_headers(clock):
    t = ratelimit.acquire("m", 500)
    ratelimit.settle(t, 100)
    assert ratelimit.available("m") == pytest.approx(900)
    ratelimit.update_from_headers("m", {"x-ratelimit-remaining-tokens": "250"})
    assert ratelimit.available("m") == pytest.approx(250)
    ratelimit.settle(t, 0)  # headers are newer than the ticket: ignored
    assert ratelimit.available("m") == pytest.approx(250)


def test_llm_chat_uses_thread_priority(respond, monkeypatch):
    seen = []
    real = ratelimit.acquire
    monkeypatch.setattr(ratelimit, "acquire", lambda m, est, pr=None, **k: seen.append(pr) or real(m, est, pr))
    respond(lambda *a: AIMessage(content="hi", usage_metadata=usage()))
    llm.chat([{"role": "user", "content": "x"}])
    with ratelimit.context("background"):
        llm.chat([{"role": "user", "content": "x"}])
    assert seen == ["interactive", "background"]


# --- jobs ---
def test_job_cancel_running_and_queued():
    m = jobs.JobManager(max_workers=1)
    started = threading.Event()

    def loop(ctx):
        started.set()
        while True:
            ctx.check()
            time.sleep(0.02)
    a = m.submit("essay about Nepal", "write", loop)
    b = m.submit("report on rivers", "write", lambda ctx: "never")
    assert started.wait(2)
    assert m.cancel("rivers").id == b.id
    assert m.cancel("nepal essay").id == a.id
    m.wait(a.id, 2)
    assert (a.status, b.status) == ("cancelled", "cancelled")
    assert store.job_get(a.id)["status"] == "cancelled"
    m.shutdown()


def test_announcer_text_and_voice(capsys):
    ann = jobs.Announcer()
    job = jobs.Job(7, "essay about Nepal", "write", status="done", output_path="/tmp/x.md", lang="ne")
    ann(job)
    assert "[job #7 done] essay about Nepal -> /tmp/x.md" in capsys.readouterr().out
    ann.mode = "voice"
    ann(job)
    text, lang = ann.pop()
    assert lang == "ne" and "essay about Nepal" in text and ann.pop() is None


# --- writer ---
def test_write_document_job_paces_sections_to_file(respond, monkeypatch):
    seen = []
    real = ratelimit.acquire

    def spy(m, est, pr=None, **k):
        seen.append((m, est, pr or ratelimit.current_priority()))
        return real(m, est, pr, **k)
    monkeypatch.setattr(ratelimit, "acquire", spy)

    def fn(messages, kw, model):
        if "Outline" in tool_names(kw):
            return AIMessage(content="", usage_metadata=usage(50, 40), tool_calls=[{
                "id": "o", "name": "Outline", "args": {"title": "Nepal", "sections": ["Land", "People", "Future"]}}])
        return AIMessage(content=" ".join(["word"] * 180), usage_metadata=usage(100, 250))
    respond(fn)
    monkeypatch.setattr(config, "WRITER_WORDS_PER_SECTION", 200)
    from jarvis.tools.general.write_document import write_document
    out = write_document.tool.invoke({"request": "write a 550-word essay about Nepal"})
    assert out.startswith("started job #1")
    job = jobs.get_manager().wait(1, 5)
    assert job.status == "done", job.error
    text = open(job.output_path, encoding="utf-8").read()
    assert text.startswith("# Nepal") and text.count("## ") == 3 and writer.count_words(text) > 500
    assert str(config.OUTPUTS_DIR) in job.output_path
    assert all(m == config.LLM_DEFAULT and pr == "background" for m, _, pr in seen) and len(seen) == 4
    assert all(est <= 1500 + 1000 for _, est, _ in seen)
    assert store.job_get(1)["tokens"] == 90 + 3 * 350


def test_writer_respects_cancel(respond, monkeypatch):
    m = jobs.JobManager(max_workers=1)
    holder = {}

    def fn(messages, kw, model):
        if "Outline" in tool_names(kw):
            return AIMessage(content="", tool_calls=[{"id": "o", "name": "Outline",
                                                      "args": {"title": "T", "sections": ["A", "B", "C"]}}])
        holder["job"].cancel_event.set()  # cancelled while the first section is written
        return AIMessage(content="text")
    respond(fn)
    holder["job"] = m.submit("essay", "write", lambda ctx: writer.run(ctx, "write a 900-word essay", "en"))
    m.wait(holder["job"].id, 5)
    assert holder["job"].status == "cancelled"
    assert open(holder["job"].output_path).read().count("## ") == 1
    m.shutdown()


# --- job tools ---
def test_job_tools():
    m = jobs.get_manager()
    gate = threading.Event()
    j = m.submit("essay about Nepal", "write", lambda ctx: gate.wait(5) and None)
    assert "essay about Nepal" in registry.call("list_jobs").output
    assert registry.call("cancel_job", {"job": "nepal"}).output == f"cancelled job #{j.id}: essay about Nepal"
    gate.set()
    m.wait(j.id, 2)
    path = config.OUTPUTS_DIR / "x.md"
    config.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text("# Hello\n\n" + "abc " * 200)
    k = m.submit("hello", "write", lambda ctx: str(path))
    m.wait(k.id, 2)
    res = registry.call("job_result", {"job_id": k.id}).output
    assert f"path: {path}" in res and "# Hello" in res and len(res) < 450
    assert "jobs" in router.rule_groups("what are you working on")


# --- open_url ---
def test_open_url_mocked(monkeypatch):
    from jarvis.tools.general import open_url
    opened: list[str] = []
    monkeypatch.setattr(open_url, "_open", opened.append)
    assert registry.call("open_url", {"target": "YouTube"}).output == "opened https://www.youtube.com"
    assert open_url.resolve("github.com/foo") == "https://github.com/foo"
    assert open_url.resolve("https://example.org/a") == "https://example.org/a"
    assert registry.call("open_url", {"target": "hamro patro"}).output == "opened hamro patro"  # found by search
    assert "error" in registry.call("open_url", {"target": "???"}).output
    assert opened[0] == "https://www.youtube.com" and opened[1].startswith("https://duckduckgo.com/")
    assert registry.get("open_url").metadata["safety"] == "safe"
    assert "browser" in router.rule_groups("open youtube")


def test_window_control_is_never_a_writing_job():
    from jarvis.core import planner, router
    assert not planner.is_long_job("uh make the full screen to VS Code the VS Code is not full screen")
    assert not planner.is_long_job("split Brave and VS Code side by side")
    assert planner.is_long_job("write a python script that renames files")
    assert router.route("Can you full screen the VS Code?", log_it=False).groups == ["windows"]


def test_parts_that_are_all_shortcuts_skip_the_planner_call(monkeypatch):
    monkeypatch.setattr(planner, "decompose", lambda text: (_ for _ in ()).throw(AssertionError("no planner call")))
    p = planner.plan("what's the weather in Pokhara and what time is it")
    assert p.method == "rules" and [t["text"] for t in p.tasks] == ["what's the weather in Pokhara", "what time is it"]
    assert not any("depends_on" in t for t in p.tasks)  # the 'it' in 'what time is it' points at nothing
    assert planner.refers_back("open it") and not planner.refers_back("is it raining in Pokhara")
