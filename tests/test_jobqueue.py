"""KURAMA's job list: add / list / edit / remove keep jobs; start runs them with retries and notices (fakes)."""
import time

from jarvis.core import jobqueue, jobs, longjobs, store


def test_add_list_edit_remove_never_runs():
    assert "Added job 1" in jobqueue.add("write an essay about Nepal")
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

    def fake(ctx, text):
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
    while any(r["status"] in ("waiting", "running") for r in store.queue_list()) and time.time() - t0 < 60:
        time.sleep(0.1)
    st = {r["text"]: (r["status"], r["tries"]) for r in store.queue_list()}
    assert st == {"flaky": ("done", 3), "refused": ("failed", 1), "fine": ("done", 1)}
    assert "KURAMA couldn't do job 2" in told and told[-1] == "KURAMA job list finished"


def test_kurama_tool_passes_job_details():
    from jarvis.tools.core.kurama import _job_args
    assert _job_args("add write an essay about Nepal") == {"action": "add", "text": "write an essay about Nepal"}
    assert _job_args("edit 2 write it in Nepali") == {"action": "edit", "job": "2", "text": "write it in Nepali"}
    assert _job_args("cancel 3") == {"action": "cancel", "job": "3"}
    assert _job_args("") == {"action": "list", "job": ""}
