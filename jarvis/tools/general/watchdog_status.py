"""watchdog_status: crash-watchdog targets and whether they are up (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="automation", safety="safe", description="Show crash-watchdog targets, their state and restarts.")
def watchdog_status() -> str:
    from jarvis.workers import crash_watchdog, status

    targets = crash_watchdog.load_targets()
    if not targets:
        return "no watchdog targets (add one in config.WATCHDOG_TARGETS or with add_watchdog_target)"
    live = status.worker_info("crash_watchdog")
    lines = []
    for t in targets:
        s = live.get(t["name"]) or {}
        state = s.get("state") or ("unknown: workers not running" if not live else "pending")
        extra = f", pid {s['pid']}" if s.get("pid") else ""
        extra += f", {s['restarts_1h']} restarts/h" if s.get("restarts_1h") else ""
        lines.append(f"{t['name']}: {state}{extra} ({t['command']})")
    return "\n".join(lines)
