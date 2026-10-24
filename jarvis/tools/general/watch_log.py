"""watch_log: tail a log file and alert on errors / progress / completion (safe).

No longer a tool of its own: `training` calls watch_log() (old name kept as an alias)."""
from __future__ import annotations



def watch_log(path: str, patterns: str = "", label: str = "") -> str:
    """Watch a log file.

    Args:
        path: Path of the log file, e.g. ~/runs/exp1/train.log.
        patterns: Optional regex to alert on instead of the defaults (Traceback|Error|nan loss|CUDA|Killed|OOM).
        label: Optional short name for the alerts.
    """
    from jarvis.workers import process_watch, status

    wid, msg = process_watch.register_log(path, patterns, label)
    if wid is None:
        return msg
    hint = "" if status.running("process_watch") else f" (workers not running: start {status.START_HINT})"
    return f"{msg}{hint}"
