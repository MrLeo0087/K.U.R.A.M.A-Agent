"""laptop_health: battery health (of new, charge cycles), disk free and how fast it fills, RAM now (safe, 0 tokens).
The quiet checks behind it message you only when something needs you (core/health.py)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="system", safety="safe",
      description="Laptop health: battery health % and charge cycles, disk free and how fast it fills, RAM now.")
def laptop_health() -> str:
    """Laptop health report."""
    from jarvis.core import health
    return health.report()
