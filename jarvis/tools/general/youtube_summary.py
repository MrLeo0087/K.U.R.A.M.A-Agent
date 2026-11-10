"""youtube_summary: a YouTube video in two minutes (main points + timestamps) from its subtitles; the video open in
the browser when no link is given (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="browser", safety="safe", max_chars=2500,
      description="Summarize a YouTube video (the one open in the browser, or a link) from its subtitles: what it "
                  "is about, main points and timestamps to jump to.")
def youtube_summary(url: str = "") -> str:
    """YouTube video summary.

    Args:
        url: The video link; empty = the YouTube video open in the browser.
    """
    from jarvis.core import ytsummary
    return ytsummary.summarize(url)
