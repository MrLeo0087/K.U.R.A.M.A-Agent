""""Ask Gemini / ask ChatGPT" (plan 11-09 phase 5, 0 KURAMA tokens): your question + what you selected + where it
is (the page's title and address, or the file and the lines around it in VS Code) -> one prompt; Brave opens the
site and the KURAMA browser extension pastes it and presses send (browser_ext/bridge.js).

- "ask gemini why this works" / "ask chatgpt what this means" / "ask claude ...": that site.
- "ask the AI ..." / no site named: your default (kv askai_default, Gemini at first; "use chatgpt by default").
- A follow-up within FOLLOW_S with nothing new selected ("ask it simpler") goes to the SAME tab (the extension
  finds it), so the conversation there continues; otherwise a new chat.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

from jarvis.core import store

SITES = {"gemini": "https://gemini.google.com/app", "chatgpt": "https://chatgpt.com/", "claude": "https://claude.ai/new"}
NAMES = {"gemini": "Gemini", "chatgpt": "ChatGPT", "claude": "Claude"}
DEFAULT_KEY, LAST_KEY = "askai_default", "askai_last"
FOLLOW_S = 30 * 60
MAX_SEL = 6000
# the site names as typed AND as speech-to-text writes them (11-10 voice: "chat LGBT", "Gemini" fine; also
# "chat g p t", "jemini")
_SITES = (r"gemini|jemini|gemni|bard|chat\s*g\.?\s*p\.?\s*t\.?|chat\s*gbt|chat\s*gtp|chat\s*lgbt|chat\s*gpd|chatgpt|"
          r"gpt|open\s*ai|claude")
_SITE_RE = re.compile(r"\b(" + _SITES + r")\b", re.I)
# the request's own words that only say "ask <site>" (the rest is the question): "ask gemini ...", "ask this to the
# gemini that ...", "can you ask to the chat gpt what ...", "send this to chatgpt"
_LEAD = re.compile(r"^\s*(?:(?:hey|ok|okay|please|so|now|can\s+you|could\s+you|will\s+you|kurama)[\s,]+)*(?:go\s+and\s+)?"
                   r"(?:ask|send|give|paste|put)\s+(?:(?:this|it|that|these|this\s+\w+)\s+)?(?:to|with|on|in|into)?\s*"
                   r"(?:the\s+)?(?:" + _SITES + r"|ai|it)\b[\s,:.-]*(?:(?:and\s+)?(?:ask|tell)\s+(?:it\s+|him\s+)?)?"
                   r"(?:that|whether|if|about|to)?\b[\s,:-]*", re.I)


def site_of(text: str) -> str:
    m = _SITE_RE.search(text or "")
    if not m:
        return ""
    w = re.sub(r"[\s.]+", "", m.group(1).lower())
    if w.startswith("chat") or w in ("gpt", "openai"):
        return "chatgpt"
    if w in ("bard", "jemini", "gemni"):
        return "gemini"
    return w


def default_site() -> str:
    s = (store.kv_get(DEFAULT_KEY) or "").strip()
    return s if s in SITES else "gemini"


def set_default(site: str) -> str:
    s = site_of(site) or site.strip().lower()
    if s not in SITES:
        return "Say Gemini, ChatGPT or Claude."
    store.kv_set(DEFAULT_KEY, s)
    return f"'Ask the AI' now goes to {NAMES[s]}."


def addressed(text: str) -> bool:
    """The request is FOR a web AI ('ask gemini ...', 'send this to chatgpt', 'ask it simpler'), not about one."""
    return bool(_LEAD.match(text or "")) and not re.search(r"\bclaude\s+code\b", text or "", re.I)  # (KURAMA's link)


def question_of(text: str) -> str:
    q = re.sub(r"^(?:to|about)\s+", "", _LEAD.sub("", text or "", count=1).strip(), flags=re.I)
    return q[:1].upper() + q[1:] if q else ""


def _around(file: Path, sel: str, lines: tuple[int, int] | None, pad: int = 8) -> str:
    """The lines around the selection in its file (for the AI to see where it sits)."""
    try:
        rows = file.read_text(errors="replace").splitlines()
    except OSError:
        return ""
    if lines is None:
        i = file.read_text(errors="replace").find(sel)
        if i < 0:
            return ""
        a = file.read_text(errors="replace")[:i].count("\n") + 1
        lines = (a, a + sel.count("\n"))
    a, b = max(1, lines[0] - pad), min(len(rows), lines[1] + pad)
    return "\n".join(rows[a - 1:b])


def context() -> dict:
    """{'selection', 'where', 'around', 'lang'}: the text highlighted LAST (VS Code / browser / any app) and where."""
    from jarvis.core import context as ctx
    from jarvis.tools.interactive import _secrets
    s = ctx.latest_selection()
    out = {"selection": "", "where": "", "around": "", "lang": ""}
    if s["source"] == "editor":
        f = Path(s["file"])
        if _secrets.private(s["text"], f):
            return out  # .env / keys: never in a prompt
        out.update(selection=s["text"], lang=f.suffix.lstrip("."),
                   where=f"the file `{f.name}`" + (f" (lines {s['lines'][0]}-{s['lines'][1]})" if s.get("lines") else "")
                   + (f" in the project `{Path(s['root']).name}`" if s.get("root") else ""))
        if len(s["text"]) < 3000:
            out["around"] = _around(f, s["text"], s.get("lines"))
    elif s["source"] == "browser":
        url, title = s.get("url") or "", s.get("title") or ""
        out.update(selection=s["text"], where=f'the web page "{title}" ({url})' if url else "a web page")
    elif s["source"] == "screen" and not _secrets.private(s["text"]):
        out["selection"] = s["text"]
    out["selection"] = out["selection"][:MAX_SEL]
    return out


def build(question: str, c: dict) -> str:
    q = question.strip() or ("Explain this simply, with one example." if c["selection"] else "")
    if not c["selection"]:
        return q
    parts = [q, ""]
    parts.append(f"Here is what I selected{(' in ' + c['where']) if c['where'] else ''}:")
    fence = c["lang"] or ""
    parts.append(f"```{fence}\n{c['selection']}\n```")
    if c["around"] and c["around"].strip() != c["selection"].strip():
        parts.append(f"The lines around it:\n```{fence}\n{c['around']}\n```")
    return "\n".join(parts).strip()


def ask(text: str, site: str = "") -> str:
    """Build the prompt and send it to the site through the browser. Returns what was done."""
    from jarvis.agents.coding import bridge
    from jarvis.tools.general.open_url import _open
    s = site_of(site) or site_of(text)
    c = context()
    q = question_of(text)
    if q and not re.search(r"\b(?:this|that|it|these|those|here|above|selected|selection|highlighted|the\s+(?:code|"
                           r"sentence|paragraph|text|function|line|lines|word|words|error|snippet|passage|class|method|"
                           r"definition|part|bit|term|phrase|query|output))\b", q, re.I):
        c["selection"] = ""  # 'ask gemini what is backpropagation': a question of its own, not about an old highlight
    last = json.loads(store.kv_get(LAST_KEY) or "{}")
    follow = (time.time() - float(last.get("t") or 0) < FOLLOW_S
              and (not c["selection"] or c["selection"] == last.get("selection"))
              and (not s or s == last.get("site")))
    s = s or (last.get("site") if follow else "") or default_site()
    if follow:
        c["selection"] = ""  # the site already has it
    prompt = build(q, c)
    if not prompt:
        return f"What should I ask {NAMES[s]}? Select some text or say the question ('ask {s} why this works')."
    try:  # also on the clipboard: Ctrl+V if the site changed its page and the extension can't paste
        from jarvis.core.rewrite import _xclip
        _xclip(["-selection", "clipboard"], prompt)
    except Exception:  # noqa: BLE001
        pass
    pid = uuid.uuid4().hex[:12]
    bridge._prompts.clear()  # one waiting prompt at a time (the extension fetches it once)
    bridge._prompts[pid] = prompt
    _open(f"{SITES[s]}#kurama={pid}" + ("&same=1" if follow else ""))
    store.kv_set(LAST_KEY, json.dumps({"t": time.time(), "site": s,
                                       "selection": c["selection"] or last.get("selection", "") if follow else c["selection"]}))
    what = "your follow-up" if follow else (f"your question + the selected text ({len(c['selection'])} characters)"
                                           if c["selection"] else "your question")
    return (f"Sent {what} to {NAMES[s]} in Brave{' (same chat)' if follow else ''}; the answer is there. "
            f"If it didn't send by itself: sign in there, or press Ctrl+V and Enter.")
