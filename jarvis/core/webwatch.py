"""Website watcher: tell me when a page changes (exam results, college notices, a GitHub release, a price) (0 tokens).

A watch is a row in the `watches` table (kind "web"): the URL, an optional focus word (only lines containing it
count, e.g. "result" or "BSc"), and how often to look. The process_watch worker fetches due pages, turns them into
text lines and compares them with the last copy; lines that differ only in numbers (clocks, visitor counters) are
not a change unless you asked to watch numbers. A change sends the new lines and the link to the desktop and phone.
"""
from __future__ import annotations

import re
import time

from jarvis.core import config, notify, store


def page_lines(url: str, focus: str = "") -> list[str]:
    from jarvis.tools.general import _web
    from jarvis.tools.general.read_webpage import fetch

    if _web.is_private_host(url):
        raise ValueError("that address is on a private network")
    ctype, body = fetch(url)
    text = _web.html_to_text(body)[1] if "html" in ctype or "<html" in body[:500].lower() else body
    lines = [" ".join(ln.split()) for ln in text.splitlines()]
    lines = [ln for ln in lines if len(ln) >= 3]
    if focus:
        words = [w.lower() for w in focus.split()]
        lines = [ln for ln in lines if all(w in ln.lower() for w in words)]
    return list(dict.fromkeys(lines))[:2000]


def _key(line: str, numbers: bool) -> str:
    return line if numbers else re.sub(r"\d+", "#", line)


def changes(old: list[str], new: list[str], numbers: bool = False) -> list[str]:
    """New lines (by meaning: digit-only edits ignored unless `numbers`)."""
    seen = {_key(x, numbers) for x in old}
    return [ln for ln in new if _key(ln, numbers) not in seen]


def add(url: str, focus: str = "", every_min: float = 0, numbers: bool = False, label: str = "") -> str:
    url = url.strip()
    if not re.match(r"^https?://", url):
        url = "https://" + url
    every = max(config.WEBWATCH_MIN_EVERY_MIN, every_min or config.WEBWATCH_EVERY_MIN)
    try:
        lines = page_lines(url, focus)
    except Exception as e:
        return f"error: couldn't read {url}: {e}"
    if focus and not lines:
        note = f" Nothing on it mentions {focus!r} yet; I'll tell you when something does."
    else:
        note = f" Right now it has {len(lines)} lines" + (f" mentioning {focus!r}" if focus else "") + "."
    name = (label or re.sub(r"^https?://(www\.)?", "", url).split("/")[0] + (f" ({focus})" if focus else ""))[:60]
    wid = store.watch_add("web", url, name, focus, {"lines": lines, "every": every * 60, "checked": time.time(),
                                                    "numbers": numbers, "changes": 0})
    return f"Watching {url} (#{wid}) every {every:.0f} min; I'll message you when it changes.{note}"


def check(w: dict) -> list[str]:
    """Fetch a due page; on change, alert and return the new lines."""
    st = w["state"]
    now = time.time()
    if now - float(st.get("checked") or 0) < float(st.get("every") or config.WEBWATCH_EVERY_MIN * 60):
        return []
    st["checked"] = now
    try:
        new = page_lines(w["target"], w.get("patterns") or "")
        st.pop("errors", None)
    except Exception as e:
        st["errors"] = int(st.get("errors") or 0) + 1
        if st["errors"] == config.WEBWATCH_FAIL_ALERT:
            notify.notify(f"Can't reach {w['label']}", f"{w['target']} failed {st['errors']} times: {e}",
                          level="warning", source="webwatch")
        store.watch_update(w["id"], state=st)
        return []
    added = changes(st.get("lines") or [], new, bool(st.get("numbers")))
    st["lines"] = new
    if added:
        st["changes"] = int(st.get("changes") or 0) + 1
        st["last_change"] = now
        st["last_added"] = added[:5]
        shown = "\n".join(f"+ {ln[:200]}" for ln in added[:6]) + (f"\n(+{len(added) - 6} more)" if len(added) > 6 else "")
        notify.notify(f"Page changed: {w['label']}", f"{shown}\n{w['target']}", level="info", source="webwatch",
                      telegram=True)
    store.watch_update(w["id"], state=st)
    return added


def describe(w: dict) -> str:
    st = w["state"]
    last = st.get("last_change")
    when = time.strftime("%d %b %H:%M", time.localtime(last)) if last else "no change yet"
    return f"#{w['id']} {w['label']}: every {float(st.get('every', 0)) / 60:.0f} min, {st.get('changes', 0)} " \
           f"change(s), last: {when}" + (f" | {st['last_added'][0][:80]}" if st.get("last_added") else "")

