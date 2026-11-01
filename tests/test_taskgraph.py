"""Phase 2: a planned request runs as a task graph. Steps get what the steps they need MADE (real paths), try the
0-token shortcut first, run without the chat history, are checked (a claim with no tool failed), get one re-plan,
and the steps after a failed one are skipped with the reason; steps after a background job become a follow-up."""
import json
import time

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from jarvis.core import agent, config, planner, safety, taskgraph, workmem
from jarvis.tools.general import _apps
from tests.test_p7c import human, names, respond, roots, tc, tg  # noqa: F401  (fixtures)


def plan_as(monkeypatch, *steps):
    monkeypatch.setattr(planner, "is_multi", lambda t: True)
    monkeypatch.setattr(planner, "decompose", lambda text: [dict(s) for s in steps])


def test_a_step_gets_the_folder_the_step_before_made(respond, roots, monkeypatch):  # noqa: F811
    folder = roots / "new_project2"
    plan_as(monkeypatch, {"text": f"create a folder {folder}", "kind": "quick"},
            {"text": "open this folder in vs code", "kind": "quick", "depends_on": [0]})
    opened, seen = [], []
    from jarvis.tools.general import _sys
    monkeypatch.setattr(_sys, "run", lambda argv, *a, **k: opened.append(argv) or "")

    def fn(messages, kw):
        seen.append(messages)
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content=messages[-1].content)
        h = human(messages)
        if h.startswith("create a folder"):
            return tc("make_folder", {"path": str(folder)})
        if h.startswith("open this folder"):
            assert f"Files: {folder}" in h, h  # the real path of what step 1 made
            return tc("open_path", {"path": str(folder), "app": "vscode"})
        return AIMessage(content="?")
    respond(fn)
    bot = agent.Agent(confirm=lambda p: True)
    bot.history = [HumanMessage("old chat about cricket"), AIMessage("Nepal won.")]
    bot.run(f"create a folder {folder} and open this folder in vs code")
    assert folder.is_dir() and opened == [["code", str(folder)]]
    assert [s["status"] for s in bot.last["steps"]] == ["ok", "ok"] and bot.last["steps"][0]["things"] == [str(folder)]
    step2 = next(m for m in seen if human(m).startswith("open this folder"))
    assert not any("cricket" in str(m.content) for m in step2)  # a step runs without the chat history


def test_failed_step_skips_what_needs_it_but_not_the_rest(respond, monkeypatch):
    monkeypatch.setattr(config, "TASK_REPLAN", False)
    plan_as(monkeypatch, {"text": "create a folder /nonexistent_root/x", "kind": "quick"},
            {"text": "open it in vs code", "kind": "quick", "depends_on": [0]},
            {"text": "what time is it", "kind": "quick"})

    def fn(messages, kw):
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content=messages[-1].content)
        h = human(messages)
        if h.startswith("create a folder"):
            return tc("make_folder", {"path": "/nonexistent_root/x"})
        if h.startswith("what time"):
            return tc("get_time", {})
        raise AssertionError(f"a skipped step ran: {h}")
    respond(fn)
    bot = agent.Agent(confirm=lambda p: True)
    ans = bot.run("create a folder /nonexistent_root/x, open it in vs code and tell me the time")
    st = [s["status"] for s in bot.last["steps"]]
    assert st == ["failed", "skipped", "ok"], st
    assert 'I skipped "open it in vs code" because "create a folder /nonexistent_root/x" didn\'t work.' in ans


@pytest.mark.parametrize("claim", ["Made it — new_project2 is in your Downloads folder.", "Done, I sent it to Telegram.",
                                   "Opened Webcam in VS Code."])
def test_a_claim_with_no_tool_is_a_failed_step(claim):
    assert taskgraph.judge(claim, {"calls": [], "things": [], "jobs": []}, agent.HONEST) == "failed"
    assert taskgraph.judge(claim, {"calls": [("make_folder", True)], "things": [], "jobs": []}, agent.HONEST) == "ok"
    assert taskgraph.judge(claim, {"calls": [("make_folder", False)], "things": [], "jobs": []}, agent.HONEST) == "failed"
    assert taskgraph.judge(claim, {"calls": [("x", True)], "things": [], "jobs": [7]}, agent.HONEST) == "waiting"


def test_a_failed_step_gets_one_corrected_try(respond, roots, monkeypatch):  # noqa: F811
    good = roots / "reports"
    plan_as(monkeypatch, {"text": "create a folder reports in /nonexistent_root", "kind": "quick"},
            {"text": "what time is it", "kind": "quick"})
    asked = []
    monkeypatch.setattr(taskgraph, "replan", lambda step, ans, req: asked.append((step, ans)) or f"create a folder {good}")

    def fn(messages, kw):
        if isinstance(messages[-1], ToolMessage):
            return AIMessage(content=messages[-1].content)
        h = human(messages)
        if h.startswith("create a folder reports"):
            return tc("make_folder", {"path": "/nonexistent_root/reports"})
        if h.startswith(f"create a folder {good}"):
            return tc("make_folder", {"path": str(good)})
        return tc("get_time", {})
    respond(fn)
    bot = agent.Agent(confirm=lambda p: True)
    bot.run("create a folder reports in /nonexistent_root and tell me the time")
    assert good.is_dir() and len(asked) == 1
    assert [s["status"] for s in bot.last["steps"]] == ["ok", "ok"] and bot.last["replanned"][0]["to"].endswith("reports")


def test_steps_after_a_background_job_become_a_follow_up(respond, monkeypatch):
    plan_as(monkeypatch, {"text": "write an essay about Nepal", "kind": "long"},
            {"text": "save it as essay.md", "kind": "quick", "depends_on": [0]},
            {"text": "send it to telegram", "kind": "quick", "depends_on": [1]},
            {"text": "what time is it", "kind": "quick"})
    started, follow = [], []
    monkeypatch.setattr(agent.jobs, "start_task", lambda text, lang="en": started.append(text) or
                        type("J", (), {"id": 4, "title": "essay about Nepal", "kind": "write"})())
    monkeypatch.setattr(agent, "start_after_job", lambda job, texts, lang=None: follow.append((job, texts)) or
                        type("F", (), {"id": 5})())
    respond(lambda m, kw: AIMessage(content=m[-1].content) if isinstance(m[-1], ToolMessage) else tc("get_time", {}))
    bot = agent.Agent(confirm=lambda p: True)
    ans = bot.run("write an essay about Nepal, save it as essay.md, send it to telegram and tell me the time")
    assert follow == [(4, ["save it as essay.md", "send it to telegram"])]
    assert "as soon as job #4 is finished" in ans and ans.rstrip().endswith("(job #4).")
    assert [s["status"] for s in bot.last["steps"]] == ["waiting", "after", "after", "ok"]


def test_independent_steps_of_a_wave_run_together(respond, monkeypatch):
    plan_as(monkeypatch, {"text": "a", "kind": "quick"}, {"text": "b", "kind": "quick"},
            {"text": "c", "kind": "quick", "depends_on": [0, 1]})
    spans = {}

    def fn(messages, kw):
        h = human(messages).split("\n")[0]
        t0 = time.monotonic()
        time.sleep(0.3)
        spans[h] = (t0, time.monotonic())
        return AIMessage(content=f"did {h}")
    respond(fn)
    ans = agent.Agent().run("a and b then c")
    assert spans["a"][0] < spans["b"][1] and spans["b"][0] < spans["a"][1]  # a and b overlapped
    assert spans["c"][0] >= max(spans["a"][1], spans["b"][1])  # c waited for both
    assert ans == "did a. did b. did c."


def test_filler_and_learned_plans(monkeypatch, tmp_path):
    from jarvis.core import semantic
    import numpy as np
    monkeypatch.setattr(semantic, "ready", lambda: True)
    monkeypatch.setattr(semantic, "best_of", lambda t, n, table: ("filler", 0.97) if "let's" in t else ("request", 0.9))
    assert planner.parts("let's work .. create a folder x, open it in vs code") == ["create a folder x",
                                                                                    "open it in vs code"]
    monkeypatch.setattr(taskgraph, "_vec", lambda text: np.ones(4, dtype=np.float32) / 2)  # every text: same meaning
    clauses = ["make a folder x in downloads", "open it in vs code"]
    taskgraph.learn_plan("make a folder x in downloads and open it in vs code", clauses,
                         [{"text": "make folder", "kind": "quick"}, {"text": "open", "kind": "quick", "depends_on": [0]}])
    got = taskgraph.learned_plan("make a folder y in documents and open it in vs code",
                                 ["make a folder y in documents", "open it in vs code"])
    assert got == [{"text": "make a folder y in documents", "kind": "quick"},
                   {"text": "open it in vs code", "kind": "quick", "depends_on": [0]}]
    assert taskgraph.learned_plan("x", ["a", "b", "c"]) is None  # a different number of parts: not this plan


def test_close_step_closes_only_what_the_plan_opened(monkeypatch):
    from jarvis.tools.general import close_app
    wins = [{"id": "0x1", "title": "main.py - KURAMA - Visual Studio Code"},
            {"id": "0x2", "title": "notes.md - Visual Studio Code"}]
    closed = []
    monkeypatch.setattr(_apps, "match_windows", lambda name, windows=None: (wins, "VS Code"))
    monkeypatch.setattr(_apps, "wmctrl", lambda args: closed.append(args[-1]))
    with taskgraph.plan_windows(["0x1"]):  # 0x1 was open before the request (the owner's work)
        out = close_app.close_app("vs code")
    assert closed == ["0x2"] and "your other 1 window(s) stay open" in out
    closed.clear()
    token = safety._CTX.set({"confirm": lambda p: False})
    try:
        with taskgraph.plan_windows(["0x1", "0x2"]):  # nothing new: ask, and the answer is no
            out = close_app.close_app("vs code")
    finally:
        safety._CTX.reset(token)
    assert closed == [] and out.startswith("Left VS Code open")
    out = close_app.close_app("vs code")  # a plain "close vs code" (no plan): closes it as asked
    assert closed == ["0x1", "0x2"]


def test_the_owners_folder_request_plans_with_no_ai(monkeypatch):
    from jarvis.core import fastpath
    from types import SimpleNamespace
    monkeypatch.setattr(taskgraph, "filler", lambda t: t.startswith("let's"))
    monkeypatch.setattr(fastpath, "match", lambda t: SimpleNamespace(tool="x"))  # each part is a shortcut
    p = planner.plan("let's work .. create a new folder in download folder name new_project2 and open this "
                     "folder in vs code")
    assert p.method == "rules" and p.tasks == [
        {"text": "create a new folder in download folder name new_project2", "kind": "quick"},
        {"text": "open this folder in vs code", "kind": "quick", "depends_on": [0]}]


@pytest.mark.parametrize("text", ["create a folder test in downloads and open it in vs code",
                                  "make a folder reports and then open it in vs code"])
def test_open_it_in_vs_code_after_a_folder_is_two_tasks_not_code(text):
    from jarvis.core import fastpath
    assert fastpath.to_file_intent(text) is None and planner.is_multi(text)


@pytest.mark.parametrize("text", ["write a function that adds two numbers and put it in this file",
                                  "create a calculator code and write it in the open file"])
def test_code_into_the_open_file_stays_one_request(monkeypatch, text):
    from jarvis.core import assist, fastpath
    monkeypatch.setattr(assist, "pending_code_active", lambda: False)
    assert fastpath.to_file_intent(text) is not None

