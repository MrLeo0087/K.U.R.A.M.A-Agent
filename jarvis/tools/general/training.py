"""training: Training Guard. How training is going, watch a run / process / log, set up Google Colab pings,
stop watching, or stop a run KURAMA started (safe; stopping a run asks first).

Merged from watch_log, watch_process, list_watches and stop_watch (their old names still work as aliases).
The process_watch worker does the watching: progress, NaN loss, out of memory, crash (+ one-line cause), stuck,
finished, Colab disconnected; alerts go to the desktop and Telegram.

Colab / Kaggle: "set up colab" (or kaggle) writes a ready notebook, KURAMA_colab.ipynb / KURAMA_kaggle.ipynb, to
~/Downloads and the workspace (0 tokens). Colab: colab.research.google.com > File > Upload notebook; Kaggle: New
Notebook > File > Import Notebook (Internet on). Turn the GPU on, run the cells top to bottom: step 3 (the link cell)
reports epochs / loss / accuracy over a private ntfy.sh channel made for this laptop, step 5 is a demo training.
On the laptop: "training status", "stop training". It is a normal Jupyter notebook: it also opens in VS Code (Jupyter
extension) and runs there on the laptop (CPU, needs torch installed locally) and still reports here.
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


def _notebook(platform: str, label: str = "") -> str:
    """0 tokens: the ready notebook (.ipynb) for Colab or Kaggle, linked to this laptop. Saved in Downloads (easy to
    upload) and the workspace; on Telegram it comes as a file. The link cell is also copied to the clipboard."""
    import shutil
    cell = tg.colab_setup(label)  # a fixed template, no LLM code generation
    name = "KURAMA_kaggle.ipynb" if platform == "kaggle" else "KURAMA_colab.ipynb"
    d = Path(config.OUTPUTS_DIR) / "colab"
    d.mkdir(parents=True, exist_ok=True)
    (d / "kurama_link_cell.py").write_text(cell)
    nb = d / name
    nb.write_text(tg.colab_notebook(cell, platform))
    site = "Kaggle" if platform == "kaggle" else "Colab"
    ctx = safety.context()
    if ctx.get("channel") == "telegram":  # on the phone: the notebook comes as a file
        from jarvis.tools.general.send_file_telegram import deliver
        deliver(nb, f"KURAMA {site} notebook: open it in {site}, run the cells top to bottom")
        return f"Sent you {name}. Open it in {site} and run the cells from top to bottom; the steps are inside."
    where = str(nb)
    try:
        dl = Path(config.NOTEBOOK_COPY_DIR)
        if dl.is_dir():
            shutil.copy2(nb, dl / name)
            where = str(dl / name)
    except OSError:
        pass
    rel = str(nb.relative_to(Path(config.OUTPUTS_DIR)))
    if ctx.get("published") is not None:
        ctx["published"].append(rel)
    how = ("kaggle.com/code > New Notebook > File > Import Notebook" if platform == "kaggle"
           else "colab.research.google.com > File > Upload notebook")
    return (f"Your {site} training notebook is ready: {where} (also in the workspace). Open {how}, turn on the GPU"
            + (" and Internet" if platform == "kaggle" else "") + ", and run the cells from top to bottom: step 3 "
            "links the run to me, step 5 is a complete demo training to replace with yours. Then ask me "
            "\"training status\" or \"stop training\".")


@tool(group="watch", safety="safe",
      description="Training Guard: how training is going (status: epochs, accuracy, ETA), watch a run/process/log, "
                  "get the training notebook linked to KURAMA (colab / kaggle: a ready .ipynb), stop a training run (stop = after this epoch, stop_now = "
                  "at once; local or Colab, asks first), or stop watching.")
def training(action: Literal["status", "watch", "colab", "kaggle", "stop", "stop_now", "stop_watching", "kill"] = "status",
             target: str = "", label: str = "", patterns: str = "") -> str:
    """Training Guard.

    Args:
        action: status = progress of every run; watch = start watching `target`; colab / kaggle = the ready
            notebook (.ipynb) whose runs report here; stop = stop a training run after the current epoch (Colab) / now
            (local); stop_now = interrupt it at once; stop_watching = forget a watch.
        target: For watch: a log file, a folder (its newest log), a PID or a process name (e.g. "train.py").
            For stop_watching / kill: the run's number or name ("all" for every watch).
        label: Optional short name for the alerts.
        patterns: Optional regex to alert on in a log (default: errors, NaN, out of memory, finished).
    """
    from jarvis.workers import process_watch as pw

    if action == "status":
        return tg.status_text(detailed=True)  # fetches the latest Colab metrics right now, formatted
    if action in ("colab", "kaggle"):
        return _notebook(action, label)
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
