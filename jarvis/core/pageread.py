"""'What is this page about?' = the page open in the browser RIGHT NOW (never an older link from the chat).

The page: the browser window the user is looking at (its title) -> its address from the browser's own history
(readlater.current_page). Its text: fetched from the web; when that is thin (a login wall, a web app like a Groq
dashboard, a JS shell) the visible window is read instead (OCR: Tesseract free, vision only when unsure).
One fast-tier call writes a 2-3 sentence overview and KURAMA asks "Want a detailed overview?"; 'yes' (within
PAGE_DETAIL_TTL_S) writes the detailed one to the workspace as a background job (smart tier). Nothing is cached:
every question reads the page again.
"""
from __future__ import annotations

import json
import logging
import re
import time

from jarvis.core import config, store

log = logging.getLogger("jarvis.pageread")
PENDING_KEY = "page_detail"  # the page just summarized, waiting for 'yes' -> detailed overview
THIN_CHARS = 400  # fetched text shorter than this = not the real content (login wall / web app)
SHORT_PROMPT = ("You describe a web page for the user in 2-3 short plain sentences: what the site/page is and what it "
                "shows right now (main numbers, items or headings). No intro, no 'this page'. Use only the given text.")
DETAIL_PROMPT = ("Write a detailed, well organised overview of this web page in Markdown: a one-line summary, then "
                 "headings with bullets for its sections, key facts, numbers, links/actions it offers. Use only the "
                 "given text; never invent.")


def current() -> tuple[str, str, str] | str:
    """(url, title, text) of the page in the browser window the user is looking at, or a message."""
    from jarvis.core import browsertab, readlater, rewrite
    tab = browsertab.get()  # the browser extension knows the open tab exactly, whichever window is in front
    if tab:
        url, ptitle = tab
    else:  # no extension: the browser window in front, its address from the browser's history
        wid, _ = rewrite.target_window()
        title = rewrite._window_name(wid) if wid else ""
        if not readlater._browser_of(title):
            return "Open the page in your browser first (Brave, Chrome or Firefox), then ask me again."
        page = readlater.current_page(title)
        url, ptitle = page if page else ("", title.rsplit(" - ", 1)[0])
    text = ""
    if url:
        try:
            from jarvis.tools.general.read_webpage import read_webpage
            got = read_webpage(url, max_chars=3000)
            text = "" if got.startswith("error:") else got
        except Exception as e:  # noqa: BLE001
            log.info("page fetch failed: %s", e)
    if len(text) < THIN_CHARS:  # a login wall / web app: read what is on the screen instead
        try:
            from jarvis.core import ocr
            shot = ocr.grab_window()
            if not isinstance(shot, str):
                seen = ocr.read(shot).text.strip()
                if len(seen) > len(text):
                    text = seen
        except Exception as e:  # noqa: BLE001
            log.info("page OCR failed: %s", e)
    if not text.strip():
        return f"I couldn't read '{ptitle}'. Select the text on the page and say 'explain this'."
    return url, ptitle, text[:6000]


def summary() -> str:
    got = current()
    if isinstance(got, str):
        return got
    url, title, text = got
    from jarvis.core import llm
    try:
        short = str(llm.chat([{"role": "system", "content": SHORT_PROMPT},
                              {"role": "user", "content": f"Title: {title}\nAddress: {url}\n\n{text[:3500]}"}],
                             tier="fast", purpose="page_summary", max_tokens=220)).strip()
    except Exception as e:  # noqa: BLE001
        log.warning("page summary failed: %s", e)
        return f"This is '{title}'. I couldn't summarise it right now."
    store.kv_set(PENDING_KEY, json.dumps({"ts": time.time(), "url": url, "title": title, "text": text}))
    return f"{short}\nWant a detailed overview? Say yes."


def waiting() -> dict | None:
    try:
        d = json.loads(store.kv_get(PENDING_KEY) or "{}")
    except ValueError:
        return None
    return d if d and time.time() - float(d.get("ts", 0)) <= config.PAGE_DETAIL_TTL_S else None


def detail() -> str:
    d = waiting()
    if not d:
        return "Ask me 'what is this page about' first."
    store.kv_delete(PENDING_KEY)
    from jarvis.core import jobs

    def job(ctx) -> str:
        from jarvis.core import llm, workspace
        md = str(llm.chat([{"role": "system", "content": DETAIL_PROMPT},
                           {"role": "user", "content": f"Title: {d['title']}\nAddress: {d['url']}\n\n{d['text']}"}],
                          tier="smart", purpose=ctx.purpose("page_detail"), max_tokens=1400,
                          priority="background")).strip()
        md = f"# {d['title']}\n\n{d['url']}\n\n" + re.sub(r"^#\s+.*\n+", "", md, count=1)
        path = workspace.publish(f"page: {d['title'][:50]}", md, folder="answers")
        if path:
            ctx.set_output(path)
        return f"» The detailed overview of {d['title'][:60]} is in the workspace."
    j = jobs.get_manager().submit(f"page overview: {d['title'][:40]}", "page", job)
    return f"Writing the detailed overview in the background (job #{j.id})."


def cancel() -> str:
    store.kv_delete(PENDING_KEY)
    return "Okay."


def run(action: str = "summary") -> str:
    return {"detail": detail, "cancel": cancel}.get(action, summary)()
