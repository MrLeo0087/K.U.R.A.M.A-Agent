"""add_watchdog_target: let the crash watchdog keep a dev server alive (confirm; allowlisted binaries only)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="automation", safety="confirm",
      description="Add a dev server for the crash watchdog to keep running and restart if it crashes.")
def add_watchdog_target(name: str, command: str, cwd: str = "", match: str = "") -> str:
    """Add a crash-watchdog target.

    Args:
        name: Short id, e.g. "n8n".
        command: Command to run, e.g. "n8n start" (allowlisted binaries only; no sudo, pipes or &&).
        cwd: Working directory (default: home).
        match: Optional text to recognise an already-running instance in the process list.
    """
    from jarvis.workers import crash_watchdog, status

    msg = crash_watchdog.add_target(name, command, cwd, match)
    if not msg.startswith("error") and not status.running("crash_watchdog"):
        msg += f" (workers not running: start {status.START_HINT})"
    return msg
