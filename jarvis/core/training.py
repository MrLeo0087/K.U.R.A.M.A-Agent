"""Training Guard: launch or watch ML training runs (local or Google Colab) and report on them.

Plain code does all the watching (0 tokens). The only LLM use is one short fast-tier call when a run crashes, to
turn the traceback into a one-line cause + fix (cached per error, config.TRAINING_EXPLAIN).

Runs live in the SQLite `watches` table (they survive restarts), kinds:
  - "run":   a command KURAMA launched (own process group, output in data/runs/<id>.log, retried on crash)
  - "proc":  a running process you pointed at (PID / name); its log is read from /proc when it writes to a file
  - "log":   a log file you pointed at
  - "colab": a Colab notebook that pings KURAMA through ntfy.sh (a free push service, no account; the topic is
             a long random name kept in kv). KURAMA polls it; silence for COLAB_SILENT_MIN = probably disconnected.
The process_watch worker drives everything (jarvis/workers/process_watch.py); this module holds the logic.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

from jarvis.core import config, store

# ---------------------------------------------------------------- metric parsing (pure, tested)
_NUM = r"(nan|-?inf|-?\d+(?:\.\d+)?(?:e[-+]?\d+)?)"
_KEYS = (r"(?P<k>(?:train_|val_|valid_|eval_|test_)?(?:loss|acc|accuracy|f1|auc|mae|rmse|bleu|rouge\w*|perplexity|ppl)"
         r"|lr|learning_rate)")
_KV = re.compile(rf"['\"]?{_KEYS}['\"]?\s*[:=]?\s*{_NUM}\b", re.I)
_EPOCH = re.compile(r"\bepoch\b['\"]?\s*[:=\[(]?\s*['\"]?\s*(\d+(?:\.\d+)?)(?:\s*(?:/|of)\s*(\d+))?", re.I)
_STEP = re.compile(r"\b(?:global_)?step\b['\"]?\s*[:=\[(]?\s*(\d+)(?:\s*(?:/|of)\s*(\d+))?", re.I)
_TQDM = re.compile(r"(\d+)%\|.*?\|\s*(\d+)/(\d+)\s*\[[\d:]+<([\d:?]+)")
_OOM = re.compile(r"CUDA out of memory|OutOfMemoryError|MemoryError|\bKilled\b|Cannot allocate memory", re.I)
_ERR_LINE = re.compile(r"^\s*(?:[\w.]+(?:Error|Exception|Interrupt)|AssertionError|KeyboardInterrupt)\b.*", re.M)


def parse_line(line: str) -> dict:
    """Metrics found in one log line: {"loss": 0.41, "epoch": 3, "epochs": 10, "pct": 45, "eta": "01:40"...}."""
    out: dict = {}
    for m in _KV.finditer(line):
        k = m.group("k").lower().replace("learning_rate", "lr").replace("accuracy", "acc")
        try:
            out[k] = float(m.group(2))
        except ValueError:
            continue
    if m := _EPOCH.search(line):
        out["epoch"] = float(m.group(1))
        if m.group(2):
            out["epochs"] = int(m.group(2))
    if m := _STEP.search(line):
        out["step"] = int(m.group(1))
        if m.group(2):
            out["steps"] = int(m.group(2))
    if m := _TQDM.search(line):
        out["pct"], out["eta"] = int(m.group(1)), m.group(4)
    return out


def loss_key(metrics: dict) -> str | None:
    for k in ("loss", "train_loss", "eval_loss", "val_loss"):
        if k in metrics:
            return k
    return None


def is_bad(v: float) -> bool:
    return v != v or v in (float("inf"), float("-inf"))


def sparkline(values: list[float]) -> str:
    vals = [v for v in values if not is_bad(v)][-24:]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    bars = "▁▂▃▄▅▆▇█"
    return "".join(bars[int((v - lo) / (hi - lo) * 7) if hi > lo else 3] for v in vals)


def error_summary(lines: list[str]) -> str:
    """The last exception line of a traceback (or the last OOM line)."""
    text = "\n".join(lines)
    errs = _ERR_LINE.findall(text)
    if errs:
        return errs[-1].strip()[:200]
    ooms = [ln for ln in lines if _OOM.search(ln)]
    return ooms[-1].strip()[:200] if ooms else ""


def update(st: dict, lines: list[str]) -> list[tuple[str, str]]:
    """Fold new log lines into a run's state; returns events [(kind, text)]: nan, oom, error, done."""
    events: list[tuple[str, str]] = []
    st["tail"] = ((st.get("tail") or []) + [ln[:300] for ln in lines])[-config.LOG_WATCH_TAIL_LINES * 3:]
    m = st.setdefault("metrics", {})
    hist = st.setdefault("loss_hist", [])
    for ln in lines:
        got = parse_line(ln)
        if got:
            m.update(got)
            k = loss_key(got)
            if k:
                hist.append(got[k])
                if is_bad(got[k]) and not st.get("nan_sent"):
                    st["nan_sent"] = True
                    events.append(("nan", f"{k} became {got[k]} ({ln.strip()[:120]})"))
        if _OOM.search(ln) and not st.get("oom_sent"):
            st["oom_sent"] = True
            events.append(("oom", ln.strip()[:200]))
        if "Traceback (most recent call last)" in ln:
            st["traceback"] = True
        elif re.search(config.LOG_WATCH_DONE_PATTERN, ln) and not _EPOCH.search(ln) and not parse_line(ln):
            events.append(("done", ln.strip()[:200]))
    del hist[:-200]
    if st.get("traceback") and (err := error_summary(st["tail"])) and err != st.get("error"):
        st["error"] = err
        events.append(("error", err))
    st["last_output"] = time.time()
    return events


def progress_text(st: dict) -> str:
    """'epoch 3/10, loss 0.412 ▇▅▄▃▂, acc 0.87, 45% (ETA 01:40)'."""
    m = st.get("metrics") or {}
    parts = []
    if "epoch" in m:
        e = m["epoch"]
        parts.append(f"epoch {int(e) if e == int(e) else round(e, 2)}" + (f"/{m['epochs']}" if m.get("epochs") else ""))
    elif "step" in m:
        parts.append(f"step {m['step']}" + (f"/{m['steps']}" if m.get("steps") else ""))
    if k := loss_key(m):
        parts.append(f"{k.replace('_', ' ')} {m[k]:.4g} {sparkline(st.get('loss_hist') or [])}".rstrip())
    for k in ("val_loss", "eval_loss", "acc", "val_acc", "eval_acc", "f1"):
        if k in m and k != loss_key(m):
            parts.append(f"{k.replace('_', ' ')} {m[k]:.4g}")
    if "pct" in m:
        parts.append(f"{m['pct']}%" + (f" (ETA {m['eta']})" if m.get("eta") and "?" not in m["eta"] else ""))
    return ", ".join(parts)


# ---------------------------------------------------------------- launching local runs
LAUNCHERS = ("python", "python3", "torchrun", "accelerate", "deepspeed", "papermill", "jupyter")


def runs_dir() -> Path:
    d = Path(config.DATA_DIR) / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def project_python(cwd: Path) -> str | None:
    """The project's own venv interpreter (venv/, .venv/, env/), so `python train.py` uses its packages."""
    for name in ("venv", ".venv", "env"):
        py = cwd / name / "bin" / "python"
        if py.is_file():
            return str(py)
    return None


def build_argv(command: str, cwd: Path) -> list[str]:
    """Check and split a training command (no shell). Raises ValueError with a friendly reason."""
    if re.search(r"[|;&<>`$]", command):
        raise ValueError("use one plain command (no pipes, ;, &&, redirects or $)")
    argv = shlex.split(command)
    if not argv:
        raise ValueError("which command should I run?")
    exe = os.path.basename(argv[0])
    if argv[0].endswith((".py", ".ipynb")):  # "train.py --epochs 5" -> python train.py ...
        argv = ["python", *argv]
        exe = "python"
    if not (exe in LAUNCHERS or re.fullmatch(r"python3(\.\d+)?", exe)):
        raise ValueError(f"{exe!r} is not a training launcher (allowed: {', '.join(LAUNCHERS)})")
    if exe in ("python", "python3") and (py := project_python(cwd)):
        argv[0] = py
    elif shutil.which(argv[0]) is None and not Path(argv[0]).is_file():
        raise ValueError(f"{argv[0]!r} is not installed")
    return argv


def launch(command: str, cwd: str = ".", label: str = "", retries: int = 0) -> tuple[int | None, str]:
    """Start a training command in the background (own process group, kept awake). Returns (watch id, message)."""
    from jarvis.tools.interactive import _proc

    try:
        wd = _proc.resolve_dir(cwd or ".")
        argv = build_argv(command, wd)
    except (ValueError, _proc.ProcError) as e:
        return None, f"error: {e}"
    label = (label or Path(argv[1] if len(argv) > 1 else argv[0]).name)[:60]
    wid = store.watch_add("run", command, label, "", {"cwd": str(wd), "argv": argv, "retries": max(0, int(retries)),
                                                      "attempt": 0})
    err = start_attempt(wid)
    if err:
        store.watch_update(wid, status="failed", finished=time.time(), result=err)
        return None, f"error: {err}"
    return wid, f"run #{wid}: started {label} in {wd} (log {runs_dir() / f'{wid}.log'})"


def start_attempt(wid: int) -> str:
    w = store.watch_get(wid)
    st = w["state"]
    log_path = runs_dir() / f"{wid}.log"
    inhibit = ["systemd-inhibit", "--what=sleep:idle", "--who=KURAMA", f"--why=training {w['label']}",
               "--mode=block"] if shutil.which("systemd-inhibit") and config.TRAINING_KEEP_AWAKE else []
    try:
        with open(log_path, "ab") as log:
            log.write(f"\n=== KURAMA run #{wid} attempt {st['attempt'] + 1}: {w['target']} ===\n".encode())
            log.flush()
            p = subprocess.Popen([*inhibit, *st["argv"]], cwd=st["cwd"], stdout=log, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, start_new_session=True,
                                 env={**os.environ, "PYTHONUNBUFFERED": "1"})
    except OSError as e:
        return f"could not start: {e}"
    st.update(pid=p.pid, started=st.get("started") or time.time(), attempt_started=time.time(),
              attempt=st["attempt"] + 1, log=str(log_path), offset=log_path.stat().st_size, traceback=False,
              nan_sent=False, oom_sent=False, error="")
    store.watch_update(wid, state=st, status="active")
    key = f"run_exit:{wid}:{st['attempt']}"
    threading.Thread(target=lambda: store.kv_set(key, str(p.wait())), name=f"run-{wid}", daemon=True).start()
    return ""


def exit_code(wid: int, attempt: int, pid: int) -> int | None:
    """The run's exit code once it has finished (None = still running; -1 = gone, code unknown). The process
    that started the run records the code (kv run_exit:<id>:<attempt>), so the worker can read it."""
    rc = store.kv_get(f"run_exit:{wid}:{attempt}")
    if rc is not None:
        return int(rc)
    # still listed (running, or a zombie its parent is about to reap and record) -> not finished yet
    return None if os.path.exists(f"/proc/{pid}") else -1


def kill_run(w: dict) -> str:
    pid = (w.get("state") or {}).get("pid")
    if not pid:
        return "nothing to stop"
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError:
        return "error: not allowed to stop that process"
    store.watch_update(w["id"], status="stopped", finished=time.time(), result="stopped by user")
    return f"stopped run #{w['id']} {w['label']}"


def proc_log(pid: int) -> str | None:
    """The file a process writes its output to (stdout/stderr), if it is a regular file."""
    for fd in (1, 2):
        try:
            target = os.readlink(f"/proc/{pid}/fd/{fd}")
        except OSError:
            continue
        if target.startswith("/") and os.path.isfile(target):
            return target
    return None


# ---------------------------------------------------------------- Google Colab bridge (ntfy.sh)
def colab_topic(create: bool = False) -> str:
    topic = store.kv_get("colab_topic") or ""
    if not topic and create:
        topic = "kurama-" + secrets.token_urlsafe(18).replace("-", "x").replace("_", "y")
        store.kv_set("colab_topic", topic)
    return topic


COLAB_SNIPPET = '''# --- KURAMA training ping: run this cell once at the top of your Colab notebook ---
import json, threading, time, urllib.request
KURAMA_TOPIC, KURAMA_RUN, _k_last = "{topic}", "{run}", [0.0]
def kurama(event="progress", force=False, **metrics):
    """Tell KURAMA how training goes. Call kurama(epoch=e, loss=l, acc=a) in your loop; kurama("done") at the end."""
    if event == "progress" and not force and time.time() - _k_last[0] < {every}: return
    _k_last[0] = time.time()
    data = {{"event": event, "run": KURAMA_RUN, **{{k: (float(v) if isinstance(v, (int, float)) else str(v)[:300])
                                                 for k, v in metrics.items()}}}}
    try: urllib.request.urlopen(urllib.request.Request("https://ntfy.sh/" + KURAMA_TOPIC,
                                                       data=json.dumps(data).encode()), timeout=5)
    except Exception: pass
def _kurama_alive():
    while True:
        time.sleep(600)
        if time.time() - _k_last[0] > 590: kurama("alive", force=True)
threading.Thread(target=_kurama_alive, daemon=True).start()
def _kurama_crash(shell, etype, evalue, tb, tb_offset=None):
    kurama("error", force=True, error=f"{{etype.__name__}}: {{evalue}}")
    shell.showtraceback((etype, evalue, tb), tb_offset=tb_offset)
get_ipython().set_custom_exc((Exception,), _kurama_crash)
try:  # Hugging Face Trainer: Trainer(..., callbacks=[KuramaCallback()])
    from transformers import TrainerCallback
    class KuramaCallback(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kw):
            nums = {{k: v for k, v in (logs or {{}}).items() if isinstance(v, (int, float))}}
            kurama(epoch=state.epoch or 0, step=state.global_step, steps=state.max_steps, **nums)
        def on_train_end(self, args, state, control, **kw):
            kurama("done", force=True, epoch=state.epoch or 0, step=state.global_step)
except ImportError: pass
kurama("start", force=True)
# Keras: model.fit(..., callbacks=[keras.callbacks.LambdaCallback(on_epoch_end=lambda e, logs: kurama(epoch=e + 1, **logs))])
# PyTorch loop: kurama(epoch=epoch, loss=loss.item())  ...  and kurama("done") when finished
'''


def colab_setup(label: str = "") -> str:
    topic = colab_topic(create=True)
    run = (label or f"colab-{time.strftime('%d%b-%H%M')}").replace('"', "")[:40]
    if not any(w["kind"] == "colab" and w["target"] == run for w in store.watches_list(("active",))):
        store.watch_add("colab", run, run, "", {"started": time.time(), "last_msg": 0.0, "expect_until":
                                                time.time() + 3600})
    return COLAB_SNIPPET.format(topic=topic, run=run, every=int(config.COLAB_PROGRESS_EVERY_S))


def colab_poll(since: str) -> list[dict]:
    """New ntfy messages for our topic since `since` (an id or a duration like '12h')."""
    import urllib.request

    topic = colab_topic()
    if not topic:
        return []
    url = f"https://ntfy.sh/{topic}/json?poll=1&since={since}"
    with urllib.request.urlopen(url, timeout=10) as r:  # noqa: S310 (fixed https host)
        lines = r.read().decode("utf-8", "replace").splitlines()
    out = []
    for ln in lines:
        try:
            msg = json.loads(ln)
        except ValueError:
            continue
        if msg.get("event") != "message":
            continue
        try:
            body = json.loads(msg.get("message") or "{}")
        except ValueError:
            continue
        out.append({"id": msg.get("id"), "time": msg.get("time"), **body})
    return out


# ---------------------------------------------------------------- crash explanation (the only LLM use)
def explain(error: str, tail: list[str]) -> str:
    """'cause -> fix' for a crash from the error memory (0 tokens when seen before, with the user's own fix),
    else one short fast-tier call that is remembered; '' when off or unavailable."""
    if not config.TRAINING_EXPLAIN or not error:
        return ""
    from jarvis.core import errmem

    r = errmem.explain("\n".join([*tail[-12:], error]))
    text = r.get("explanation") or ""
    return text + (f" You fixed it before by: {r['fix']}" if r.get("fix") else "")


# ---------------------------------------------------------------- status for "how's training?"
def fmt_duration(seconds: float) -> str:
    s = int(max(0, seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m" if h else (f"{m}m {s}s" if m else f"{s}s")


KINDS = ("run", "proc", "log", "colab")  # training/process watches ("web" watches belong to webwatch)


def describe(w: dict) -> str:
    st = w.get("state") or {}
    where = {"run": "local", "proc": "process", "log": "log", "colab": "Colab"}.get(w["kind"], w["kind"])
    head = f"#{w['id']} {w['label']} ({where}"
    if w["status"] == "active":
        since = st.get("started") or w["created"]
        head += f", running {fmt_duration(time.time() - since)})"
    else:
        head += f", {w['status']})"
    prog = progress_text(st)
    tail = (st.get("tail") or [""])[-1][:120] if not prog else ""
    extra = f": {prog}" if prog else (f": {w['result']}" if w.get("result") and w["status"] != "active" else "")
    if st.get("error") and w["status"] != "done":
        extra += f" | last error: {st['error'][:120]}"
    return head + extra + (f" | {tail}" if tail else "")


def status_text(include_recent: bool = True) -> str:
    active = [w for w in store.watches_list(("active",)) if w["kind"] in KINDS]
    lines = [describe(w) for w in active]
    if include_recent:
        recent = [w for w in store.watches_list(("done", "failed", "stopped")) if w["kind"] in KINDS
                  and w.get("finished") and time.time() - w["finished"] < 12 * 3600][:3]
        if recent:
            lines += ["Recently finished:"] + [describe(w) for w in recent]
    return "\n".join(lines) if lines else "Nothing is training or being watched right now."
