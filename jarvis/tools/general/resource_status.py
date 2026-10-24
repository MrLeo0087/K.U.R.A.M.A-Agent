"""resource_status: KURAMA's own health (RAM, swap, CPU, disk, KURAMA RSS, workers).

No longer a tool of its own: `laptop_doctor` (action=kurama) calls it (old name kept as an alias)."""
from __future__ import annotations



def resource_status() -> str:
    from jarvis.workers import resource_guard, status

    hogs = ", ".join(f"{n} {mb:.0f} MB" for n, _, mb in resource_guard.top_memory(3))
    return f"{resource_guard.summary()}. Top memory: {hogs}. {status.summary()}"
