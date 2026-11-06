"""KURAMA's own tools, lent to the coding agent (it lives on the laptop: it can use what KURAMA can):

    web_search      search the web (docs, an error message, a library's usage)        read
    read_webpage    the text of a web page (a docs page, a GitHub README)              read
    screen_text     the text on the screen right now (an error dialog, a terminal)     read
    tell_phone      a message to the owner's Telegram (a long job's result)            phone

They run through KURAMA's safety layer (logged like every KURAMA tool; anything that would need a yes is refused
here, the agent has to call ask instead). Their output is cut like the agent's own tools.
"""
from __future__ import annotations

from coder.core.run import Run

OUT = 1800


def _kurama(name: str, args: dict) -> str:
    from jarvis.core import safety
    res = safety.execute(name, args, confirm=lambda prompt: False)  # (no yes from here: the agent asks instead)
    out = res.output if res.ok else f"error: {res.error or res.output}"
    return out if len(out) <= OUT else out[:OUT] + " …(cut)"


def web_search(run: Run, query: str) -> str:
    return _kurama("web_search", {"query": query})


def read_webpage(run: Run, url: str) -> str:
    return _kurama("read_webpage", {"url": url})


def screen_text(run: Run) -> str:
    return _kurama("read_text", {"source": "screen"})


def tell_phone(run: Run, text: str) -> str:
    return _kurama("send_message_telegram", {"text": text[:3500]})


def register_all() -> None:
    from coder.tools import registry
    s = {"type": "string"}
    registry.register("web_search", "Search the web (docs, an error message, how to use a library).", "read",
                      web_search, {"query": s}, ("query",))
    registry.register("read_webpage", "The text of a web page (docs, a README).", "read", read_webpage,
                      {"url": s}, ("url",))
    registry.register("screen_text", "The text on the owner's screen right now (an error dialog, a terminal).", "read",
                      screen_text)
    registry.register("tell_phone", "Send the owner a short message on Telegram.", "phone", tell_phone,
                      {"text": s}, ("text",))
