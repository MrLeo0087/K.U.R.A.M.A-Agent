"""A multi-step request whose step starts a background job: the next steps wait for the job's real output."""
import time

from jarvis.core import agent, jobs, longjobs, store


def test_chain_waits_for_started_job(monkeypatch, tmp_path):
    monkeypatch.setattr(longjobs, "pause_reason", lambda needs_power=False: None)
    out = tmp_path / "report.md"
    out.write_text("Black holes are regions of spacetime...", encoding="utf-8")
    seen = []

    def fake_run(self, text, mode, lang, prev="", request=""):
        seen.append((text, prev))
        if text.startswith("write"):  # this step only STARTS a background job
            def work(ctx):
                time.sleep(0.3)
                return str(out)
            jobs.get_manager().submit("report", "write", work)
            return "Writing it in the background (job started)."
        return f"done: {text}"
    monkeypatch.setattr(agent.Agent, "_run_task", fake_run)
    bot = agent.Agent.__new__(agent.Agent)
    bot.last = {}
    res = bot._chain_node({"chain": [{"text": "write a report on black holes", "idx": 0},
                                     {"text": "send it to telegram", "idx": 1}], "mode": "text"})["results"]
    assert "as soon as job #" in res[1]["answer"]
    assert [t for t, _ in seen] == ["write a report on black holes"]  # step 2 did NOT run on "job started"
    follow = max(store.jobs_list(5), key=lambda r: r["id"])
    t0 = time.time()
    while store.job_get(follow["id"])["status"] in jobs.ACTIVE and time.time() - t0 < 15:
        time.sleep(0.1)
    assert store.job_get(follow["id"])["status"] == "done"
    text, prev = seen[-1]
    assert text == "send it to telegram" and str(out) in prev and "Black holes" in prev
