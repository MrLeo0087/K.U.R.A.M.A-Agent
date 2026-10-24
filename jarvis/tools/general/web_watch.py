"""web_watch: tell me when a web page changes: exam results, college notices, releases, prices (safe, 0 tokens)."""
from __future__ import annotations

import time
from typing import Literal

from jarvis.core import store, webwatch
from jarvis.core.registry import tool


@tool(group="web", safety="safe",
      description="Website watcher: message the user when a page changes (results, notices, releases, prices). add "
                  "a URL (optionally only lines with a word like 'result'), list, stop, or check now.")
def web_watch(action: Literal["add", "list", "stop", "check"] = "list", url: str = "", word: str = "",
              every_minutes: float = 0) -> str:
    """Watch web pages.

    Args:
        action: add = start watching `url`; list = all watches; stop = stop the watch `url` (number, name or
            'all'); check = look at all of them now.
        url: The page (https://...) or, for stop, the watch's number/name.
        word: Only lines containing this word count (e.g. "result", "BSc 2nd year", "v2.").
        every_minutes: How often to look (default 60, at least 10).
    """
    watches = [w for w in store.watches_list(("active",)) if w["kind"] == "web"]
    if action == "add":
        return webwatch.add(url, word, every_minutes) if url.strip() else "error: which page should I watch?"
    if action == "stop":
        q = url.strip().lstrip("#").lower()
        hit = [w for w in watches if q in ("all", "") or q == str(w["id"]) or q in w["label"].lower()
               or q in w["target"].lower()]
        for w in hit:
            store.watch_update(w["id"], status="stopped", finished=time.time(), result="stopped by user")
        return "Stopped watching " + ", ".join(w["label"] for w in hit) if hit else "No page watch matches that."
    if action == "check":
        out = []
        for w in watches:
            w["state"]["checked"] = 0
            added = webwatch.check(w)
            out.append(f"{w['label']}: " + (f"{len(added)} new line(s): {added[0][:100]}" if added else "no change"))
        return "\n".join(out) or "No pages are being watched."
    return "\n".join(webwatch.describe(w) for w in watches) or "No pages are being watched."
