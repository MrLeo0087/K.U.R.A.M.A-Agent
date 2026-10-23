"""resource_status: "how's my system doing" (RAM, swap, CPU, disk, Jarvis RSS, workers) (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="system", safety="safe",
      description="System health: RAM, swap, CPU load, disk use, Jarvis memory, top memory hogs, workers.")
def resource_status() -> str:
    from jarvis.workers import resource_guard, status

    hogs = ", ".join(f"{n} {mb:.0f} MB" for n, _, mb in resource_guard.top_memory(3))
    return f"{resource_guard.summary()}. Top memory: {hogs}. {status.summary()}"
