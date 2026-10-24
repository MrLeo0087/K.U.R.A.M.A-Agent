"""run_training: start a training command in the background and guard it (confirm: it runs a program).

Uses the project's own venv for `python ...`, keeps the laptop awake, logs to data/runs/<id>.log, and can restart
the run after a crash (your script should resume from its last checkpoint). Alerts like `training`.
"""
from __future__ import annotations

from jarvis.core import training as tg
from jarvis.core.registry import tool


@tool(group="watch", safety="confirm",
      description="Start a training command in the background (e.g. 'python train.py --epochs 10') and guard it: "
                  "progress, crash (+ cause), NaN, out of memory, stuck, finished; optional auto-restart.")
def run_training(command: str, folder: str = ".", label: str = "", retries: int = 0) -> str:
    """Run and guard a training command.

    Args:
        command: The command, e.g. "python train.py --epochs 10" (python/torchrun/accelerate/papermill...).
        folder: The project folder to run it in (loose names work, e.g. "my_project").
        label: Optional short name for the alerts.
        retries: Restart it this many times if it crashes (0-5).
    """
    wid, msg = tg.launch(command, folder, label, min(max(int(retries or 0), 0), 5))
    if wid is None:
        return msg
    from jarvis.tools.general.training import _workers_hint
    return msg + _workers_hint() + ". I'll tell you when it finishes or if something goes wrong."
