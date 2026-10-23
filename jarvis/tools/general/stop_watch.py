"""stop_watch: stop one watch (by number or name) or all of them (safe)."""
from __future__ import annotations

import time

from jarvis.core.registry import tool


@tool(group="watch", safety="safe", description="Stop a process/log watch by number or name, or 'all'.")
def stop_watch(watch: str) -> str:
    """Stop watching.

    Args:
        watch: Watch number like "3", part of its name, or "all".
    """
    from jarvis.core import store
    from jarvis.workers import process_watch

    found = process_watch.find_watch(watch)
    if not found:
        return f"no active watch matches {watch!r}"
    for w in found:
        store.watch_update(w["id"], status="stopped", finished=time.time(), result="stopped by user")
    return "stopped " + ", ".join(f"#{w['id']} {w['label']}" for w in found)
