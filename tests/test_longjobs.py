"""Long Job Engine (Night Shift step 1): durable state, crash/restart resume, caps, pause, heavy lock, tools.
No real AI (token use is faked through store.log_llm) and no real RAM/battery probe."""
from __future__ import annotations

import json
import os
import threading
import time

import pytest

from jarvis.core import config, jobs, longjobs, store

REAL_PAUSE_REASON = longjobs.pause_reason


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(config, "LONG_JOB_PROBE_S", 0.0)  # probe on every check
    monkeypatch.setattr(config, "LONG_JOB_RECHECK_S", 0.05)
    monkeypatch.setattr(longjobs, "pause_reason", lambda needs_power=False: None)  # never the real laptop
    monkeypatch.setattr(longjobs, "_heavy", threading.Semaphore(1))


def _wait(jid: int, timeout: float = 10.0) -> dict:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        row = store.job_get(jid)
        if row["status"] not in jobs.ACTIVE:
            return row
        time.sleep(0.02)
    raise AssertionError(f"job #{jid} still {store.job_get(jid)['status']}")


def _wait_status(jid: int, status: str, timeout: float = 5.0) -> None:
    t0 = time.monotonic()
    while store.job_get(jid)["status"] != status:
        assert time.monotonic() - t0 < timeout, store.job_get(jid)["status"]
        time.sleep(0.02)


def _lines(path: str) -> list[str]:
    return open(path, encoding="utf-8").read().splitlines()


def test_selftest_runs_with_steps_and_checkpoints():
    job = longjobs.submit("self test", longjobs.selftest, {"n": 3, "sleep": 0.01})
    row = _wait(job.id)
    assert row["status"] == "done", row
    assert _lines(row["output_path"]) == [f"step {i} pid {os.getpid()}" for i in (1, 2, 3)]
    texts = [s["text"] for s in longjobs.steps(job.id)]
    assert texts[0] == "started" and texts[-1] == "finished" and "step 2/3" in texts
    assert len(json.loads(store.job_state_get(job.id)["state"])["done"]) == 3


def test_lambda_is_refused():
    with pytest.raises(ValueError):
        longjobs.submit("x", lambda ctx, p: None)


def _crashed_job(n: int, done: int, owner: str) -> int:
    """A long job a crash left 'running' after `done` checkpointed steps, owned by `owner`."""
    jid = store.job_insert("crashed self test", "long", "", status="running")
    state = {"done": [{"i": i, "pid": 1, "ts": 0} for i in range(1, done + 1)]}
    store.job_state_insert(jid, fn="jarvis.core.longjobs:selftest", params=json.dumps({"n": n, "sleep": 0.01}),
                           state=json.dumps(state), caps=json.dumps({"tokens": 0, "seconds": 0}), used_s=0.0,
                           owner=owner, paused=0, origin="")
    return jid


def test_crash_left_running_is_resumed_from_checkpoint():
    jid = _crashed_job(5, 2, "999999:1")  # its process is gone
    jobs.reset_manager()
    assert jobs.get_manager() is not None  # a new manager must not mark a long job failed
    assert store.job_get(jid)["status"] == "running"
    assert longjobs.recover() == [jid]
    row = _wait(jid)
    assert row["status"] == "done"
    assert [ln.split()[1] for ln in _lines(row["output_path"])] == ["1", "2", "3", "4", "5"]  # 1-2 not redone
    assert "resumed from its last checkpoint" in [s["text"] for s in longjobs.steps(jid)]


def test_job_owned_by_a_live_process_is_left_alone():
    import psutil
    parent = psutil.Process(os.getppid())
    jid = _crashed_job(3, 0, f"{parent.pid}:{int(parent.create_time())}")
    assert longjobs.recover() == []
    assert store.job_get(jid)["status"] == "running"


def test_quit_marks_interrupted_then_restart_resumes():
    job = longjobs.submit("long self test", longjobs.selftest, {"n": 30, "sleep": 0.05})
    t0 = time.monotonic()
    while not json.loads(store.job_state_get(job.id)["state"] or "{}").get("done"):
        assert time.monotonic() - t0 < 5
        time.sleep(0.02)
    jobs.get_manager().shutdown(cancel=True, wait=True)  # KURAMA quits
    row = store.job_get(job.id)
    assert row["status"] == jobs.INTERRUPTED, row
    jobs._manager = None
    store.job_state_update(job.id, owner="999999:1")  # the quit process is gone
    assert longjobs.recover() == [job.id]
    row = _wait(job.id, 15)
    assert row["status"] == "done"
    assert [int(ln.split()[1]) for ln in _lines(row["output_path"])] == list(range(1, 31))


def burn_tokens(ctx, params):
    for i in range(int(params["calls"])):
        if ctx.state.get("i", 0) > i:
            continue
        ctx.step(f"call {i + 1}")
        store.log_llm("fake", ctx.purpose(f"call{i}"), 300, 200, 5, True)
        ctx.checkpoint(i=i + 1)
    return None


def test_token_cap_stops_then_resume_adds_budget():
    job = longjobs.submit("burn", burn_tokens, {"calls": 6}, max_tokens=1200)
    row = _wait(job.id)
    assert row["status"] == jobs.STOPPED and "token budget" in row["error"], row
    assert 1200 <= row["tokens"] <= 1500  # stopped at the first check over the cap
    msg = jobs.resume(str(job.id))
    assert "token cap now" in msg
    row = _wait(job.id)
    assert row["status"] == "done" and row["tokens"] == 3000  # 6 calls, none repeated


def slow(ctx, params):
    for i in range(200):
        ctx.step(f"tick {i}")
        time.sleep(0.01)


def test_time_cap_and_deadline_stop():
    a = longjobs.submit("time cap", slow, {}, max_minutes=0.1 / 60)
    b = longjobs.submit("deadline", slow, {}, deadline=time.time() + 0.1)
    ra, rb = _wait(a.id), _wait(b.id)
    assert ra["status"] == jobs.STOPPED and "time budget" in ra["error"]
    assert rb["status"] == jobs.STOPPED and "end time" in rb["error"]


def test_user_pause_and_resume():
    job = longjobs.submit("pausable", longjobs.selftest, {"n": 40, "sleep": 0.02})
    time.sleep(0.1)
    assert "pausing job" in longjobs.pause(job.id)
    _wait_status(job.id, "paused")
    n = len(json.loads(store.job_state_get(job.id)["state"])["done"])
    time.sleep(0.3)
    assert len(json.loads(store.job_state_get(job.id)["state"])["done"]) == n  # no progress while paused
    assert "continues" in jobs.resume(str(job.id))
    assert _wait(job.id, 15)["status"] == "done"
    assert "paused: paused by you" in [s["text"] for s in longjobs.steps(job.id, 100)]


def test_pause_flag_from_another_process_is_seen():
    job = longjobs.submit("pausable", longjobs.selftest, {"n": 40, "sleep": 0.02})
    time.sleep(0.1)
    store.job_state_update(job.id, paused=1)  # e.g. the Telegram worker wrote it
    _wait_status(job.id, "paused")
    store.job_state_update(job.id, paused=0)
    _wait_status(job.id, "running")
    jobs.get_manager().cancel(job.id)
    assert _wait(job.id)["status"] == "cancelled"


def test_auto_pause_on_low_ram_and_cancel_while_paused(monkeypatch):
    reason = {"v": "low RAM"}
    monkeypatch.setattr(longjobs, "pause_reason", lambda needs_power=False: reason["v"])
    job = longjobs.submit("ram", longjobs.selftest, {"n": 3, "sleep": 0.01})
    _wait_status(job.id, "paused")
    assert store.job_get(job.id)["progress"] == "paused: low RAM"
    reason["v"] = None
    assert _wait(job.id)["status"] == "done"
    reason["v"] = "not charging"
    job2 = longjobs.submit("night", longjobs.selftest, {"n": 3, "sleep": 0.01}, needs_power=True)
    _wait_status(job2.id, "paused")
    jobs.get_manager().cancel(job2.id)
    assert _wait(job2.id)["status"] == "cancelled"


def test_pause_reason_reads_battery_and_ram(monkeypatch):
    import psutil
    from collections import namedtuple
    pause_reason = REAL_PAUSE_REASON
    Bat = namedtuple("Bat", "percent power_plugged")
    VM = namedtuple("VM", "available")
    monkeypatch.setattr(psutil, "virtual_memory", lambda: VM(4000 * 1048576))
    monkeypatch.setattr(psutil, "sensors_battery", lambda: Bat(80, True))
    assert pause_reason(True) is None
    monkeypatch.setattr(psutil, "sensors_battery", lambda: Bat(80, False))
    assert pause_reason(False) is None and pause_reason(True) == "not charging"
    monkeypatch.setattr(psutil, "sensors_battery", lambda: Bat(20, False))
    assert pause_reason(False) == "battery 20%"
    monkeypatch.setattr(psutil, "virtual_memory", lambda: VM(100 * 1048576))
    assert pause_reason(False) == "low RAM"


_running: list[int] = []
_overlap: list[bool] = []


def heavy_work(ctx, params):
    _running.append(ctx.job.id)
    _overlap.append(len(_running) > 1)
    time.sleep(0.15)
    _running.remove(ctx.job.id)


def test_one_heavy_job_at_a_time():
    _overlap.clear()
    a = longjobs.submit("heavy a", heavy_work, {}, heavy=True)
    b = longjobs.submit("heavy b", heavy_work, {}, heavy=True)
    assert _wait(a.id)["status"] == "done" and _wait(b.id)["status"] == "done"
    assert _overlap == [False, False]


def test_jobs_tool_pause_result_resume():
    from jarvis.tools.general.jobs import jobs as jobs_tool
    job = longjobs.submit("tool test", longjobs.selftest, {"n": 40, "sleep": 0.02})
    time.sleep(0.1)
    assert "pausing" in jobs_tool("pause", str(job.id))
    _wait_status(job.id, "paused")
    assert "steps:" in jobs_tool("result", str(job.id))
    assert "continues" in jobs_tool("resume", str(job.id))
    assert _wait(job.id, 15)["status"] == "done"
    assert "no long job" in jobs_tool("pause", "99999")


def test_recover_with_no_long_jobs_does_nothing():
    jobs.reset_manager()
    assert longjobs.recover() == []
    assert jobs._manager is None  # nothing created while idle
