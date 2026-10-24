"""watch_process: alert when a PID or named process exits, with its runtime (safe).

No longer a tool of its own: `training` calls watch_process() (old name kept as an alias)."""
from __future__ import annotations



def watch_process(target: str, label: str = "") -> str:
    """Watch a process until it exits.

    Args:
        target: A PID like "12345" or a process name like "python train.py" / "ffmpeg".
        label: Optional short name for the alert, e.g. "training run".
    """
    from jarvis.workers import process_watch, status

    wid, msg = process_watch.register_process(target, label)
    if wid is None:
        return msg
    hint = "" if status.running("process_watch") else f" (workers not running: start {status.START_HINT})"
    return f"{msg}; I'll alert you when it exits{hint}"
