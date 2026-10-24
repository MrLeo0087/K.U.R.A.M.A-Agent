"""training: Training Guard. How training is going, watch a run / process / log, set up Google Colab pings,
stop watching, or stop a run KURAMA started (safe; stopping a run asks first).

Merged from watch_log, watch_process, list_watches and stop_watch (their old names still work as aliases).
The process_watch worker does the watching: progress, NaN loss, out of memory, crash (+ one-line cause), stuck,
finished, Colab disconnected; alerts go to the desktop and Telegram.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Literal

from jarvis.core import config, safety, store, training as tg
from jarvis.core.registry import alias, tool


def _workers_hint() -> str:
    from jarvis.workers import status
    return "" if status.running("process_watch") else f" (workers not running: start {status.START_HINT})"


def _newest_log(folder: Path) -> Path | None:
    logs = [p for p in folder.rglob("*") if p.suffix in (".log", ".txt", ".out") and p.is_file()
            and time.time() - p.stat().st_mtime < 3600]
    return max(logs, key=lambda p: p.stat().st_mtime) if logs else None


@tool(group="watch", safety="safe",
      description="Training Guard: how training is going (status), watch a training run/process/log file, set up "
                  "Google Colab pings (colab), stop watching, or stop a run KURAMA started (kill).")
def training(action: Literal["status", "watch", "colab", "stop_watching", "kill"] = "status", target: str = "",
             label: str = "", patterns: str = "") -> str:
    """Training Guard.

    Args:
        action: status = progress of every run; watch = start watching `target`; colab = get the notebook cell
            that makes a Colab run report here; stop_watching = forget a watch; kill = stop a run KURAMA started.
        target: For watch: a log file, a folder (its newest log), a PID or a process name (e.g. "train.py").
            For stop_watching / kill: the run's number or name ("all" for every watch).
        label: Optional short name for the alerts.
        patterns: Optional regex to alert on in a log (default: errors, NaN, out of memory, finished).
    """
    from jarvis.workers import process_watch as pw

    if action == "status":
        return tg.status_text()
    if action == "colab":
        cell = tg.colab_setup(label)
        path = Path(config.OUTPUTS_DIR) / "kurama_colab_cell.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cell)
        return ("Paste this cell at the top of your Colab notebook and run it once; then call kurama(epoch=..., "
                "loss=...) in your loop (Hugging Face: callbacks=[KuramaCallback()]). I'll tell you about progress, "
                f"crashes, the end, or if Colab goes quiet. Saved as {path}.\n\n{cell}")
    if action in ("stop_watching", "kill"):
        found = pw.find_watch(target or ("all" if action == "stop_watching" else ""))
        if not found:
            return f"nothing active matches {target!r}"
        if action == "kill":
            runs = [w for w in found if w["kind"] == "run"]
            if not runs:
                return "I can only stop runs I started; for other programs ask me to force-quit the app."
            if not safety.ask(f"Stop {', '.join(w['label'] for w in runs)} now? Unsaved progress is lost."):
                return "The user said no, so it keeps running."
            return "; ".join(tg.kill_run(w) for w in runs)
        for w in found:
            store.watch_update(w["id"], status="stopped", finished=time.time(), result="stopped by user")
        return "stopped watching " + ", ".join(f"#{w['id']} {w['label']}" for w in found)
    # watch
    t = target.strip()
    if not t:
        return "error: what should I watch? A log file, a folder, a PID or a process name."
    p = Path(t).expanduser()
    if p.is_dir() and (log := _newest_log(p)):
        p = log
    if p.is_file():
        wid, msg = pw.register_log(str(p), patterns, label)
    else:
        wid, msg = pw.register_process(t, label)
    return msg + ("" if wid is None else _workers_hint())


alias("watch_log", "training", lambda a: {"target": a.get("path", ""), "label": a.get("label", ""),
                                          "patterns": a.get("patterns", "")}, action="watch")
alias("watch_process", "training", lambda a: {"target": a.get("target", ""), "label": a.get("label", "")},
      action="watch")
alias("list_watches", "training", action="status")
alias("stop_watch", "training", lambda a: {"target": a.get("watch", "")}, action="stop_watching")
