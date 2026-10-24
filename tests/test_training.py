"""Training Guard: metric parsing, alerts, launched runs (real tiny subprocesses), retries, Colab, tools."""
import sys
import time
from types import SimpleNamespace

import pytest

from jarvis.core import config, fastpath, registry, safety, store, training
from jarvis.workers import process_watch as pw


@pytest.fixture(autouse=True)
def quiet(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "TRAINING_KEEP_AWAKE", False)
    monkeypatch.setattr(config, "TRAINING_EXPLAIN", False)
    monkeypatch.setattr(config, "LOG_WATCH_ALERT_COOLDOWN_S", 0)


def titles():
    return [a["title"] for a in store.alerts_recent()]


# --- parsing ---
@pytest.mark.parametrize("line,want", [
    ("{'loss': 0.6931, 'grad_norm': 1.2, 'learning_rate': 5e-05, 'epoch': 0.5}", {"loss": 0.6931, "lr": 5e-05,
                                                                                   "epoch": 0.5}),
    ("{'eval_loss': 0.41, 'eval_accuracy': 0.87, 'epoch': 1.0}", {"eval_loss": 0.41, "eval_acc": 0.87}),
    ("100/100 [==============================] - 5s 50ms/step - loss: 0.4512 - accuracy: 0.8123 - val_loss: 0.5",
     {"loss": 0.4512, "acc": 0.8123, "val_loss": 0.5}),
    ("Epoch 3/10", {"epoch": 3.0, "epochs": 10}),
    ("Epoch 2:  45%|████▌     | 450/1000 [01:23<01:40,  5.40it/s, loss=0.512, v_num=0]",
     {"epoch": 2.0, "pct": 45, "eta": "01:40", "loss": 0.512}),
    ("Epoch [3/10], Step [100/600], Loss: 0.2345", {"epoch": 3.0, "epochs": 10, "step": 100, "steps": 600,
                                                    "loss": 0.2345}),
    ("epoch 4 train_loss nan", {"epoch": 4.0}),
])
def test_parse_line(line, want):
    got = training.parse_line(line)
    for k, v in want.items():
        assert got.get(k) == v, (k, got)


def test_update_events_and_progress_text():
    st: dict = {}
    ev = training.update(st, ["Epoch 1/5", "loss: 0.9", "Epoch 2/5", "loss: 0.6 - accuracy: 0.7"])
    assert ev == [] and "epoch 2/5" in training.progress_text(st) and "acc 0.7" in training.progress_text(st)
    assert training.sparkline([0.9, 0.6]) == "█▁"
    ev = training.update(st, ["loss: nan"])
    assert ev[0][0] == "nan" and training.update(st, ["loss: nan"]) == []  # said once
    ev = training.update(st, ["RuntimeError: CUDA out of memory. Tried to allocate 2 GiB"])
    assert [k for k, _ in ev] == ["oom"]
    ev = training.update(st, ["Traceback (most recent call last):", '  File "t.py", line 3', "ValueError: bad shape"])
    assert ("error", "ValueError: bad shape") in ev and st["error"] == "ValueError: bad shape"
    assert training.update({}, ["Training finished"]) == [("done", "Training finished")]
    assert training.update({}, ["epoch 3 completed"]) == []  # progress, not the end


def test_build_argv_safety_and_project_venv(tmp_path):
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("")
    assert training.build_argv("python train.py --epochs 3", tmp_path)[0] == str(tmp_path / ".venv/bin/python")
    assert training.build_argv("train.py", tmp_path)[1] == "train.py"
    for bad in ("rm -rf /", "python a.py && rm x", "python a.py > out", "bash run.sh"):
        with pytest.raises(ValueError):
            training.build_argv(bad, tmp_path)


# --- launched runs: real subprocesses ---
def wait_done(w, wid, secs=8.0):
    end = time.time() + secs
    while time.time() < end:
        w.tick()
        if store.watch_get(wid)["status"] != "active":
            return store.watch_get(wid)
        time.sleep(0.1)
    raise AssertionError("run did not finish")


def script(tmp_path, body):
    p = tmp_path / "train.py"
    p.write_text(body)
    return f"{sys.executable} {p}"


def test_run_finishes_with_summary(tmp_path):
    cmd = script(tmp_path, "for e in range(1, 4): print(f'Epoch {e}/3 - loss: {1/e:.3f} - accuracy: {e/4:.2f}')\n")
    wid, msg = training.launch(cmd, str(tmp_path), "toy")
    assert wid and "started toy" in msg
    row = wait_done(pw.ProcessWatcher(), wid)
    assert row["status"] == "done" and "epoch 3/3" in row["result"] and "loss 0.333" in row["result"]
    a = store.alerts_recent()[0]
    assert a["title"] == "Training finished: toy" and a["level"] == "info"
    assert "toy" in training.status_text()


def test_run_crash_is_retried_then_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRAINING_EXPLAIN", True)
    monkeypatch.setattr(training, "explain", lambda err, tail: "the batch is too big; lower batch_size")
    cmd = script(tmp_path, "print('Epoch 1/5 - loss: 0.9')\nraise ValueError('shapes (3,) and (4,) not aligned')\n")
    wid, _ = training.launch(cmd, str(tmp_path), "crashy", retries=1)
    w = pw.ProcessWatcher()
    end = time.time() + 10
    while store.watch_get(wid)["status"] == "active" and time.time() < end:
        w.tick()
        time.sleep(0.1)
    row = store.watch_get(wid)
    assert row["status"] == "failed" and "ValueError" in row["result"] and row["state"]["attempt"] == 2
    t = titles()
    assert "Training crashed, restarting: crashy" in t and "Training crashed: crashy" in t
    crash = store.alerts_recent()[0]
    assert "Likely: the batch is too big" in crash["text"] and crash["level"] == "error"


def test_kill_asks_first(tmp_path):
    cmd = script(tmp_path, "import time\nprint('Epoch 1/9', flush=True)\ntime.sleep(30)\n")
    wid, _ = training.launch(cmd, str(tmp_path), "long")
    out = safety.execute("training", {"action": "kill", "target": "long"}, confirm=lambda p: False)
    assert "keeps training" in out.output and store.watch_get(wid)["status"] == "active"
    out = safety.execute("training", {"action": "kill", "target": str(wid)}, confirm=lambda p: True)
    assert "stopped run" in out.output and store.watch_get(wid)["status"] == "stopped"


# --- logs and processes ---
def test_log_watch_progress_nan_and_finish(tmp_path):
    log = tmp_path / "train.log"
    log.write_text("old Error before the watch\n")
    wid, msg = pw.register_log(str(log), label="exp1")
    assert wid and "tailing" in msg
    w = pw.ProcessWatcher()
    with log.open("a") as f:
        f.write("Epoch 1/10 - loss: 0.9\rEpoch 2/10 - loss: 0.7\n")
    w.tick()
    assert not store.alerts_recent() and "epoch 2/10" in training.describe(store.watch_get(wid))
    log.rename(tmp_path / "train.log.1")  # rotation
    log.write_text("Epoch 3/10 - loss: nan\n")
    w.tick()
    assert titles()[0] == "Loss is NaN: exp1"
    with log.open("a") as f:
        f.write("Traceback (most recent call last):\n  File x\nRuntimeError: boom\n")
    w.tick()
    assert titles()[0] == "Error in the log: exp1" and "RuntimeError: boom" in store.alerts_recent()[0]["text"]
    with log.open("a") as f:
        f.write("training finished\n")
    w.tick()
    assert store.watch_get(wid)["status"] == "done" and titles()[0] == "Training finished: exp1"


def test_stalled_run_warns_once(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRAINING_STALL_MIN", 1)
    cmd = script(tmp_path, "import time\nprint('Epoch 1/9', flush=True)\ntime.sleep(30)\n")
    wid, _ = training.launch(cmd, str(tmp_path), "stuck")
    w = pw.ProcessWatcher()
    time.sleep(0.5)
    w.tick()
    st = store.watch_get(wid)["state"]
    st["last_output"] = time.time() - 120
    store.watch_update(wid, state=st)
    w.tick()
    w.tick()
    assert titles().count("No progress: stuck") == 1
    training.kill_run(store.watch_get(wid))


# --- Colab ---
def test_colab_setup_events_and_silence(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path / "out")
    out = registry.call("training", {"action": "colab", "label": "bert"}).output
    topic = store.kv_get("colab_topic")
    cell = (tmp_path / "out" / "kurama_colab_cell.py").read_text()
    assert topic.startswith("kurama-") and len(topic) > 25 and f'"{topic}"' in cell and "KuramaCallback" in out
    compile((tmp_path / "out" / "kurama_colab_cell.py").read_text(), "cell", "exec")  # the saved cell is valid Python
    msgs = [{"id": "a", "event": "start", "run": "bert"},
            {"id": "b", "event": "progress", "run": "bert", "epoch": 1, "loss": 0.8, "eval_accuracy": 0.7},
            {"id": "c", "event": "progress", "run": "bert", "epoch": 2, "loss": 0.5}]
    monkeypatch.setattr(training, "colab_poll", lambda since: msgs)
    w = pw.ProcessWatcher()
    w.tick()
    row = next(r for r in store.watches_list(("active",)) if r["kind"] == "colab")
    assert "epoch 2" in training.describe(row) and "loss 0.5" in training.describe(row)
    assert titles()[0] == "Colab training started: bert" and store.kv_get("colab_since") == "c"
    st = row["state"]
    st["last_msg"] = time.time() - 3600
    store.watch_update(row["id"], state=st)
    monkeypatch.setattr(training, "colab_poll", lambda since: [])
    w.last_colab_poll = 0
    w.tick()
    assert titles()[0] == "Colab went quiet: bert"
    monkeypatch.setattr(training, "colab_poll", lambda since: [{"id": "d", "event": "done", "run": "bert", "epoch": 3}])
    w.last_colab_poll = 0
    w.tick()
    assert store.watch_get(row["id"])["status"] == "done" and titles()[0] == "Training finished: bert"


# --- tools, aliases, fast path ---
def test_tools_aliases_and_fastpath(tmp_path, monkeypatch):
    assert registry.safety_of(registry.get("run_training")) == "confirm"
    assert registry.safety_of(registry.get("training")) == "safe"
    assert "no running process" in registry.call("watch_log", {"path": str(tmp_path / "x.log")}).output
    (tmp_path / "a.log").write_text("")
    assert "tailing" in registry.call("watch_log", {"path": str(tmp_path / "a.log")}).output
    assert "a.log" in registry.call("list_watches", {}).output
    assert "stopped watching" in registry.call("stop_watch", {"watch": "a.log"}).output
    (tmp_path / "runs").mkdir(exist_ok=True)
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "out.log").write_text("x\n")
    assert "out.log" in registry.call("training", {"action": "watch", "target": str(tmp_path / "proj")}).output
    assert "declined" in safety.execute("run_training", {"command": "python t.py"}, confirm=lambda p: False).output.lower()
    monkeypatch.setattr(config, "FASTPATH", True)
    it = fastpath.match("how is my training going")
    assert (it.tool, it.args) == ("training", {"action": "status"})
    assert fastpath.match("connect my colab notebook").args == {"action": "colab"}


# --- Colab: stop from the phone, direct phone messages, files, status anywhere ---
def test_colab_stop_direct_file_and_status(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path / "out")
    monkeypatch.setattr(config, "COLAB_FILES_DIR", str(tmp_path / "Colab"))
    registry.call("training", {"action": "colab", "label": "cnn"})
    sent = []
    monkeypatch.setattr(training, "colab_command", lambda run, cmd, **kw: sent.append((run, cmd, kw)) or True)
    msgs = [{"id": "a", "event": "start", "run": "cnn", "direct": True},
            {"id": "b", "event": "progress", "run": "cnn", "epoch": 12, "epochs": 30, "loss": 0.41, "accuracy": 0.87,
             "val_accuracy": 0.84}]
    monkeypatch.setattr(training, "colab_poll", lambda since: msgs)
    w = pw.ProcessWatcher()
    w.tick()
    first = store.alerts_recent()[0]
    assert first["title"] == "Colab training started: cnn" and "telegram" not in (first.get("channels") or "")
    row = next(r for r in store.watches_list(("active",)) if r["kind"] == "colab")
    st = row["state"]
    st["started"] = time.time() - 3600  # 12 of 30 epochs in an hour -> 1h 30m left
    store.watch_update(row["id"], state=st)
    status = registry.call("status_now", {}).output
    assert "epoch 12/30" in status and "acc 0.87" in status and "val acc 0.84" in status and "~1h 30m left" in status
    assert "last update" in status
    no = safety.execute("training", {"action": "stop"}, confirm=lambda p: False)
    assert "keeps training" in no.output and not sent
    yes = safety.execute("training", {"action": "stop"}, confirm=lambda p: True)
    assert sent == [("cnn", "stop", {})] and "after the current epoch" in yes.output
    safety.execute("training", {"action": "stop_now", "target": "cnn"}, confirm=lambda p: True)
    assert sent[-1][1] == "stop_now"
    # the run stops, then sends its checkpoint through Drive after it ended: still delivered, link closed again
    monkeypatch.setattr(training, "colab_poll", lambda since: [{"id": "c", "event": "stopped", "run": "cnn", "epoch": 13}])
    w.last_colab_poll = 0
    w.tick()
    assert store.watch_get(row["id"])["status"] == "stopped" and titles()[0] == "Colab training stopped: cnn"

    class FakeStream:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_bytes(self):
            yield b"weights"
    monkeypatch.setattr(pw.notify, "_http", lambda: SimpleNamespace(stream=FakeStream))
    monkeypatch.setattr(training, "colab_poll", lambda since: [{"id": "d", "event": "file", "run": "cnn",
                                                                "name": "best.pt", "drive_id": "XYZ"}])
    w.last_colab_poll = 0
    w.tick()
    assert (tmp_path / "Colab" / "cnn" / "best.pt").read_bytes() == b"weights"
    assert sent[-1] == ("cnn", "got_file", {"id": "XYZ"}) and titles()[0] == "Got a file from Colab: cnn"
    assert not [r for r in store.watches_list(("active",)) if r["kind"] == "colab"]  # no phantom new run


def test_colab_cell_is_valid_python():
    cell = training.colab_cell("kurama-test", "run1")
    compile(cell, "cell", "exec")
    assert '"kurama-test"' in cell and "KuramaKeras" in cell and "kurama_should_stop" in cell


def test_keep_awake_reaps_stale_blockers(monkeypatch):
    killed, started = [], []

    class P:
        def __init__(self, pid, cmd):
            self.info = {"pid": pid, "cmdline": cmd}

        def terminate(self):
            killed.append(self.info["pid"])
    stale = ["systemd-inhibit", "--what=sleep:idle", "--who=KURAMA", pw.ProcessWatcher.INHIBIT_WHY, "--mode=block", "sleep", "infinity"]
    monkeypatch.setattr(pw.psutil, "process_iter", lambda attrs=None: [P(11, stale), P(12, ["bash"])])
    monkeypatch.setattr(config, "TRAINING_KEEP_AWAKE", True)
    monkeypatch.setattr(pw.shutil, "which", lambda b: "/usr/bin/" + b)
    monkeypatch.setattr(pw.subprocess, "Popen", lambda args, **k: started.append(args) or SimpleNamespace(poll=lambda: None, pid=99))
    w = pw.ProcessWatcher()
    w.keep_awake(True)
    assert killed == [11] and started[0][-2:] == ["sleep", "600"]
