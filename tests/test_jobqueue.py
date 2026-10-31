"""KURAMA's job list: add / list / edit / remove keep jobs; start runs them with retries and notices (fakes)."""
import time

from jarvis.core import jobqueue, jobs, longjobs, store


def test_add_list_edit_remove_never_runs():
    assert "1. write an essay about Nepal" in jobqueue.add("write an essay about Nepal")
    jobqueue.add("research black holes")
    assert "1. write an essay about Nepal — waiting" in jobqueue.show()
    assert "now: write it in Nepali" in jobqueue.edit("1", "write it in Nepali")
    assert "Removed job 2" in jobqueue.remove("2")
    assert [r["n"] for r in store.queue_list()] == [1]
    assert jobs.get_manager().active() == []  # nothing started


def test_start_runs_retries_temporary_and_notifies(monkeypatch):
    monkeypatch.setattr(longjobs, "pause_reason", lambda needs_power=False: None)
    told, calls = [], {}
    monkeypatch.setattr(jobqueue, "_tell", lambda title, text, level="info": told.append(title))

    def fake(ctx, text, confirm=None):
        calls[text] = calls.get(text, 0) + 1
        if text == "flaky" and calls[text] < 3:
            return False, "LLMError: rate limit 429", ""
        if text == "refused":
            return False, "Sorry, I couldn't do that: it needs your yes", ""
        return True, "done it", ""
    monkeypatch.setattr(jobqueue, "_run_one", fake)
    monkeypatch.setattr(jobqueue.config, "QUEUE_RETRIES", 3)
    for t in ("flaky", "refused", "fine"):
        jobqueue.add(t)
    assert "Starting 3 job(s)" in jobqueue.start()
    t0 = time.time()
    while any(r["status"] in ("waiting", "queued", "running") for r in store.queue_list()) and time.time() - t0 < 60:
        time.sleep(0.1)
    st = {r["text"]: (r["status"], r["tries"]) for r in store.queue_list()}
    assert st == {"flaky": ("done", 3), "refused": ("failed", 1), "fine": ("done", 1)}
    while (not told or told[-1] != "KURAMA job list finished") and time.time() - t0 < 60:
        time.sleep(0.1)  # the summary comes right after the last job
    assert "KURAMA couldn't do job 2" in told and told[-1] == "KURAMA job list finished"


def test_kurama_tool_passes_job_details():
    from jarvis.tools.core.kurama import _job_args
    assert _job_args("add write an essay about Nepal") == {"action": "add", "text": "write an essay about Nepal"}
    assert _job_args("edit 2 write it in Nepali") == {"action": "edit", "job": "2", "text": "write it in Nepali"}
    assert _job_args("cancel 3") == {"action": "cancel", "job": "3"}
    assert _job_args("") == {"action": "list", "job": ""}


def test_several_jobs_in_one_add_and_list_results():
    out = jobqueue.add("what's the weather in Pokhara; add calculate 18% of 5600; add write a 4 line poem")
    assert "Added 3 job(s)" in out
    jobqueue.add("1. summarize notes 2. back up photos")
    assert [r["text"] for r in store.queue_list()] == ["what's the weather in Pokhara", "calculate 18% of 5600",
                                                       "write a 4 line poem", "summarize notes", "back up photos"]
    store.queue_update(2, status="done", note="18% of 5600 is 1008")
    from jarvis.tools.general.jobs import jobs as jobs_tool
    assert "1008" in jobs_tool("result", "2") and "waiting" in jobs_tool("result", "1")


def test_job_waiting_for_your_answer_lets_the_next_one_run(monkeypatch):
    from jarvis.core import safety
    monkeypatch.setattr(longjobs, "pause_reason", lambda needs_power=False: None)
    monkeypatch.setattr(jobqueue, "_tell", lambda *a, **k: None)
    events, asked = [], []

    def hook(question, timeout=None):  # Telegram: no answer within the wait = no
        asked.append((question, timeout))
        time.sleep(0.6)
        return False
    monkeypatch.setattr(safety, "get_confirm", lambda mode: hook)

    def fake(ctx, text, confirm=None):
        events.append(f"start {text}")
        if text == "needs yes":
            ok = confirm("delete the old backups?")
            events.append(f"answer {ok}")
            return False, "Sorry, I couldn't: you said no", ""
        events.append(f"end {text}")
        return True, "ok", ""
    monkeypatch.setattr(jobqueue, "_run_one", fake)
    jobqueue.add("needs yes; quick one")
    jobqueue.start()
    t0 = time.time()
    while any(r["status"] in ("waiting", "queued", "running") for r in store.queue_list()) and time.time() - t0 < 30:
        time.sleep(0.05)
    assert events.index("start quick one") < events.index("answer False")  # ran while job 1 waited for you
    assert asked and asked[0][1] == jobqueue.config.QUEUE_ASK_S and "Job 1" in asked[0][0]
    assert {r["text"]: r["status"] for r in store.queue_list()} == {"needs yes": "failed", "quick one": "done"}


def test_start_several_numbers_and_adding_while_running(monkeypatch):
    monkeypatch.setattr(longjobs, "pause_reason", lambda needs_power=False: None)
    monkeypatch.setattr(jobqueue, "_tell", lambda *a, **k: None)
    gate = {"go": False}

    def fake(ctx, text, confirm=None):
        while text == "job aa" and not gate["go"]:
            time.sleep(0.05)
        return True, f"did {text}", ""
    monkeypatch.setattr(jobqueue, "_run_one", fake)
    jobqueue.add("job aa; job bb; job cc")
    assert "Starting 2 job(s)" in jobqueue.start("1 2")  # the AI passed '1 2': both, not just 1
    assert store.queue_get(3)["status"] == "waiting"
    assert "Added to the run" in jobqueue.start("3")  # more while it runs: same run
    gate["go"] = True
    t0 = time.time()
    while any(r["status"] in ("waiting", "queued", "running") for r in store.queue_list()) and time.time() - t0 < 30:
        time.sleep(0.05)
    assert [r["status"] for r in store.queue_list()] == ["done", "done", "done"]
