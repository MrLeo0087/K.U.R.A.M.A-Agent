"""The owner's standing rules for how KURAMA answers ("from now on, keep your answers short", "always call me boss",
"never use emojis"): kept in data/style.json until the owner changes or forgets one, and added to EVERY AI reply's
instructions (profile facts only join personal-looking requests, so a rule there was missing from most replies).
At most STYLE_MAX rules, STYLE_MAX_CHARS in all (the system prompt stays small). Saved through the app_name tool;
fastpath.style_intent catches "from now on / always / never ..." about replies by meaning, 0 tokens."""
from __future__ import annotations

import json
import re
import threading
import time

from jarvis.core import config

_lock = threading.Lock()
_dropped: list[tuple[str, float]] = []  # (rule, until): the chat's recent replies still follow a forgotten rule
DROPPED_S = 600


def _path():
    return config.DATA_DIR / "style.json"


def rules() -> list[str]:
    try:
        d = json.loads(_path().read_text(encoding="utf-8"))
        return [str(x) for x in d if str(x).strip()] if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _write(rs: list[str]) -> None:
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps(rs, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_path())


def clean(text: str) -> str:
    """'Okay KURAMA, from now on please keep your answers short.' -> 'keep your answers short'."""
    t = " ".join((text or "").split()).strip(" .!")
    names = "|".join(re.escape(n) for n in config.ASSISTANT_NAMES)
    t = re.sub(rf"^(?:(?:ok(?:ay)?|hey|so|and|also|listen|remember)[\s,]+)*(?:(?:{names})[\s,]+)?", "", t, flags=re.I)
    t = re.sub(r"^(?:from\s+now\s+on|starting\s+now|going\s+forward)[\s,]+(?:please\s+)?", "", t, flags=re.I)
    return t[:1].lower() + t[1:] if t else t


def _words(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-z']{3,}", t.lower())} - {"the", "and", "you", "your", "always", "never", "please"}


def add(rule: str) -> str:
    r = clean(rule)
    if len(r) < 4:
        return "error: say the rule, e.g. 'from now on, keep your answers short'"
    r = r[:config.STYLE_RULE_MAX_CHARS]
    with _lock:
        rs = rules()
        same = [x for x in rs if _words(x) and len(_words(x) & _words(r)) / len(_words(x) | _words(r)) >= 0.6]
        rs = [x for x in rs if x not in same] + [r]  # a newer version of the same rule replaces it
        dropped = rs[:-config.STYLE_MAX] if len(rs) > config.STYLE_MAX else []
        rs = rs[-config.STYLE_MAX:]
        _write(rs)
    note = f" (I let go of the oldest: {dropped[0]})" if dropped else ""
    return f"Got it. From now on: {r}.{note}"


def forget(what: str) -> str:
    """By its words ('the short answers rule'), its number, or 'all'."""
    with _lock:
        rs = rules()
        w = (what or "").strip().lower()
        if w in ("all", "everything", "all rules"):
            _write([])
            _dropped.extend((r, time.time() + DROPPED_S) for r in rs)
            return f"Forgot all {len(rs)} rules."
        if w.isdigit() and 1 <= int(w) <= len(rs):
            gone = rs.pop(int(w) - 1)
        else:
            scored = sorted(((len(_words(x) & _words(w)), x) for x in rs), reverse=True)
            if not scored or scored[0][0] == 0:
                return "I couldn't tell which rule you mean. Say 'list my rules' to see them."
            gone = scored[0][1]
            rs.remove(gone)
        _write(rs)
        _dropped.append((gone, time.time() + DROPPED_S))
    return f"Forgot the rule: {gone}."


def line() -> str:
    """The rules for this request ('' when none), within STYLE_MAX_CHARS; a rule forgotten in the last DROPPED_S
    is named as stopped (the replies in the chat history still follow it, and the model copies them)."""
    now = time.time()
    _dropped[:] = [(r, t) for r, t in _dropped if t > now and r not in rules()]
    stopped = ("No longer follow: " + "; ".join(r for r, _ in _dropped) + ".") if _dropped else ""
    out, size = [], 0
    for r in reversed(rules()):  # the newest first when space runs out
        if size + len(r) + 2 > config.STYLE_MAX_CHARS:
            break
        out.insert(0, r)
        size += len(r) + 2
    now_rules = ("My standing rules for your reply (follow them unless I say otherwise now): " + "; ".join(out) + ".") \
        if out else ""
    return " ".join(x for x in (now_rules, stopped) if x)
