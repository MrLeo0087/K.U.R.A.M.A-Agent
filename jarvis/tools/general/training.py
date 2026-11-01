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
      description="Training Guard: how training is going (status: epochs, accuracy, ETA), watch a run/process/log, "
                  "link a Google Colab notebook (colab), stop a training run (stop = after this epoch, stop_now = "
                  "at once; local or Colab, asks first), or stop watching.")
def training(action: Literal["status", "watch", "colab", "stop", "stop_now", "stop_watching", "kill"] = "status",
             target: str = "", label: str = "", patterns: str = "") -> str:
    """Training Guard.

    Args:
        action: status = progress of every run; watch = start watching `target`; colab = get the notebook cell
            that makes a Colab run report here; stop = stop a training run after the current epoch (Colab) / now
            (local); stop_now = interrupt it at once; stop_watching = forget a watch.
        target: For watch: a log file, a folder (its newest log), a PID or a process name (e.g. "train.py").
            For stop_watching / kill: the run's number or name ("all" for every watch).
        label: Optional short name for the alerts.
        patterns: Optional regex to alert on in a log (default: errors, NaN, out of memory, finished).
    """
    from jarvis.workers import process_watch as pw

    if action == "status":
        return tg.status_text(detailed=True)  # fetches the latest Colab metrics right now, formatted
    if action == "colab":
        cell = tg.colab_setup(label)  # 0 tokens: a fixed template, no LLM code generation
        d = Path(config.OUTPUTS_DIR) / "colab"
        d.mkdir(parents=True, exist_ok=True)
        py = d / "kurama_colab_cell.py"
        py.write_text(cell)
        nb = d / "KURAMA_colab.ipynb"
        nb.write_text(tg.colab_notebook(cell))  # an .ipynb you can import into Colab (File > Upload notebook)
        ctx = safety.context()
        if ctx.get("channel") == "telegram":  # on the phone: the notebook comes as a file
            from jarvis.tools.general.send_file_telegram import deliver
            deliver(nb, "KURAMA Colab notebook — open it in Colab (Upload notebook), or copy its first cell")
            where = "sent to you as a notebook (.ipynb) file"
        else:
            rel = str(nb.relative_to(Path(config.OUTPUTS_DIR)))
            if ctx.get("published") is not None:
                ctx["published"].append(rel)
            where = "in your workspace as KURAMA_colab.ipynb (also at " + str(nb) + ")"
            try:  # the owner wants to paste it at once: the cell goes to the clipboard too
                from jarvis.tools.general import _sys
                _sys.clip_set(cell)
                where += "; the cell is COPIED: paste it as the first cell of your Colab or Kaggle notebook"
            except Exception:  # noqa: BLE001 - no clipboard tool: the file is enough
                pass
        return (f"The training notebook is {where}. Works in Colab and Kaggle (Kaggle: Settings > Internet on). "
                "Run that cell once, then start training. Keras: model.fit(..., callbacks=[KuramaKeras()]); "
                "PyTorch: call kurama(epoch=e, epochs=N, loss=l, acc=a) each epoch and 'if kurama_should_stop(): break'; "
                "HF: callbacks=[KuramaCallback()]. At the end kurama_send('best.pt') sends the checkpoint here. "
                "Optional Colab secrets KURAMA_TG_TOKEN and KURAMA_TG_CHAT make alerts reach your phone when the laptop is off.")
    if action in ("stop", "stop_now", "kill"):
        runs = [w for w in pw.find_watch(target) if w["kind"] in ("run", "colab")]
        if not runs:
            return "No training run of mine is active" + (f" matching {target!r}" if target else "") + \
                ". (For other programs ask me to stop the process or force-quit the app.)"
        if len(runs) > 1 and not target:
            return "Which one? " + "; ".join(f"#{w['id']} {w['label']}" for w in runs)
        w = runs[0]
        now = action != "stop"
        how = "right now" if now else ("after the current epoch" if w["kind"] == "colab" else "now")
        if not safety.ask(f"Stop training {w['label']} {how}?" + (" Progress since the last checkpoint is lost."
                                                                 if now else "")):
            return "The user said no, so it keeps training."
        if w["kind"] == "colab":
            if not tg.colab_command(w["target"], "stop_now" if now else "stop"):
                return "error: couldn't reach Colab's command channel (internet?)"
            return (f"Sent. Colab checks every 30 s, then {w['label']} stops {how}; I'll confirm when it has."
                    " (A plain PyTorch loop needs `if kurama_should_stop(): break` for the gentle stop.)")
        return tg.kill_run(w)
    if action == "stop_watching":
        found = pw.find_watch(target or "all")
        if not found:
            return f"nothing active matches {target!r}"
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
