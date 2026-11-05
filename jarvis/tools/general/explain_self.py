"""explain_self: KURAMA explains itself from facts, not guesses: what it just did (the last request's real record:
the tools it ran, their arguments and results), how those tools work (their own code notes, core/selfindex.py),
the settings that change them (with current values), and the file it made when the question is about it. One short
smart-model call (~800-1,500 tokens), only when asked "how did you do that?" / "explain this" / "can I use it in..."."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from jarvis.core.registry import tool

SYSTEM = ("You are {name}, the owner's laptop assistant, explaining yourself to the owner (not a developer). Use "
          "ONLY the FACTS: your real last request, your tools' notes, current settings. Say in everyday words where the "
          "information comes from and what you do (e.g. 'I ask Cloudflare's test server and time a download'). Never "
          "show tool names, function calls or code unless asked for code. If a fact is missing, say you don't know. "
          "To change how something works: if a listed setting fits, tell the exact words to say, like: set speed test "
          "seconds to 30 (instant); otherwise say it needs a code change. For using a result elsewhere (VS Code, "
          "Colab, the phone) give short numbered steps. At most 6 short sentences unless steps or code are asked.")


def _last_request(max_age_s: float = 1800) -> dict | None:
    """The newest finished request before this one (not an explanation itself)."""
    from jarvis.core import trace
    cur = (trace.current() or {}).get("id")
    for row in trace.recent(1, 8):
        if row["id"] == cur or time.time() - float(row["ts"]) > max_age_s:
            continue
        full = trace.get(row["id"]) or {}
        if "explain_self" in str(full.get("tools") or ""):
            continue
        return full
    return None


def _file_facts(text: str, limit: int = 1500) -> str:
    """The start of a file the last answer named (a notebook's steps, a script), when it exists and is text."""
    for m in re.finditer(r"(/[^\s'\"()]+\.(?:ipynb|py|md|txt|json|sh))", text or ""):
        p = Path(m.group(1))
        if not p.is_file() or p.stat().st_size > 2_000_000:
            continue
        try:
            if p.suffix == ".ipynb":
                cells = json.loads(p.read_text(encoding="utf-8")).get("cells", [])
                body = "\n".join(("[markdown] " if c.get("cell_type") == "markdown" else "[code] ")
                                 + "".join(c.get("source", []))[:400] for c in cells)
            else:
                body = p.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue
        return f"FILE {p}:\n{body[:limit]}"
    return ""


def facts(question: str) -> str:
    from jarvis.core import selfindex
    out, names = [], []
    last = _last_request()
    if last:
        try:
            calls = json.loads(last.get("tools") or "[]")
        except ValueError:
            calls = []
        names = [c.get("name", "") for c in calls if c.get("name") and not c["name"].startswith("_")]
        out.append(f"LAST REQUEST: \"{last.get('text', '')}\" -> answered: \"{str(last.get('answer') or '')[:500]}\"")
        for c in calls[:4]:
            if c.get("name", "").startswith("_"):
                continue
            what = (getattr(selfindex.card(c.get("name", "")), "what", "") or "an action").split(":")[0]
            out.append(f"DID: {what} with {json.dumps(c.get('args') or {}, ensure_ascii=False)[:200]} -> "
                       f"{str(c.get('result') or '')[:300]}")
        if f := _file_facts(str(last.get("answer") or "") + " " + " ".join(str(c.get("result") or "") for c in calls)):
            out.append(f)
    cards = selfindex.cards_for(names) + [c for c in selfindex.by_meaning(question, 2) if c.name not in names]
    out += [c.text(how_chars=1100, plain=True) for c in cards[:3]]
    return "\n\n".join(out)


@tool(group="self", safety="safe", max_chars=2500,
      description="Explain how you did your last action or how one of your tools works (method, data source, "
                  "settings that change it, how to use its result elsewhere), from your real record and code notes.")
def explain_self(question: str) -> str:
    """Explain yourself.

    Args:
        question: The owner's question, as asked ("how did you get the time?", "explain this code").
    """
    from jarvis.core import identity, llm
    known = facts(question)
    if not known:
        return "I haven't done anything recently to explain, and no tool of mine matches that question."
    reply = llm.chat([{"role": "system", "content": SYSTEM.format(name=identity.name())},
                      {"role": "user", "content": f"FACTS:\n{known}\n\nQUESTION: {question}"}],
                     tier="smart", purpose="explain_self", max_tokens=700, reasoning_effort="low")
    return (getattr(reply, "text", "") or "").strip() or "error: I couldn't put the explanation together. Ask again?"
