"""status_now: one answer to "what's going on?": training (epochs, accuracy, ETA), jobs, downloads, recording, page
watches, guard, what's next, the laptop and recent alerts (safe, 0 tokens). Telegram /status uses it too."""
from __future__ import annotations

from jarvis.core import overview
from jarvis.core.registry import tool


@tool(group="usage", safety="safe",
      description="Current status of everything: training runs (epoch x/N, accuracy, loss, ETA), background jobs, "
                  "downloads, lecture recording, page watches, guard, next reminder/class, laptop, recent alerts.")
def status_now() -> str:
    """Everything that's going on right now."""
    return overview.status_all()
