"""page_summary: what the page open in the browser right now is about; 'yes' = a detailed overview (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="browser", safety="safe", description="What the web page open in the browser RIGHT NOW is about (short "
      "overview, then offers a detailed one in the workspace). Never pass an older link: it reads the current tab.")
def page_summary(action: Literal["summary", "detail", "cancel"] = "summary") -> str:
    """The current browser page.

    Args:
        action: summary (2-3 sentences + offer), detail (the detailed overview to the workspace), cancel.
    """
    from jarvis.core import pageread

    return pageread.run(action)
