"""download_file: download a big file now or tonight, resuming if the connection breaks; tells you when done (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import automation
from jarvis.core.registry import tool


@tool(group="automation", safety="safe",
      description="Download manager: download a file (dataset, model, ISO) now or tonight, resumes after a broken "
                  "connection, retries, and says when it's done; or list downloads.")
def download_file(action: Literal["add", "list"] = "add", url: str = "", folder: str = "",
                  when: Literal["now", "tonight"] = "now") -> str:
    """Downloads.

    Args:
        action: add = queue `url`; list = downloads and their progress.
        url: The http(s) link.
        folder: Where to save it (default ~/Downloads; loose names work).
        when: now, or tonight (after 1 AM, when the network is free).
    """
    if action == "list":
        return automation.downloads_text()
    return automation.queue(url, folder, when)
