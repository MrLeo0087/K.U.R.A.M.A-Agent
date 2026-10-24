"""list_watches: active process/log watches and recently finished ones (safe).

No longer a tool of its own: `training` calls list_watches() (old name kept as an alias)."""
from __future__ import annotations



def list_watches() -> str:
    from jarvis.core import store
    from jarvis.workers import process_watch, status

    rows = store.watches_list(("active",), 20) + store.watches_list(("done", "stopped"), 3)
    lines = [process_watch.describe(w) for w in rows] or ["no watches"]
    if not status.running("process_watch"):
        lines.append(f"(process_watch worker not running: start {status.START_HINT})")
    return "\n".join(lines)
