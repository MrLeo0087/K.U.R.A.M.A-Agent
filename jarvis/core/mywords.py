"""The owner's own words: "when I say good night, lock the screen" -> saying "good night" (the whole request) runs
"lock the screen", forever, until the owner changes or forgets it. Kept in data/my_words.json, never trimmed.
An app's name ("when I say code, open VS Code") is _apps.teach instead: it works inside any sentence. Both are
saved by the app_name tool.
Agent.run / Agent.stream swap the request before anything else (0 tokens; the trace keeps what was said)."""
from __future__ import annotations

import json
import re
import threading

from jarvis.core import config

_lock = threading.Lock()


def _path():
    return config.DATA_DIR / "my_words.json"


def key(text: str) -> str:
    """'Good night, Kurama!' -> 'good night': lower case, no punctuation, no name / please around it."""
    t = " ".join(re.sub(r"[^\w\s']", " ", (text or "").lower()).split())
    names = "|".join(re.escape(n.lower()) for n in config.ASSISTANT_NAMES)
    t = re.sub(rf"^(?:(?:hey|hi|ok|okay)\s+)?(?:{names})\s+", "", t)
    t = re.sub(rf"\s+(?:please|{names})$", "", t)
    return re.sub(r"^please\s+", "", t).strip()


def all_words() -> dict[str, str]:
    try:
        d = json.loads(_path().read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(d: dict[str, str]) -> None:
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_path())


def save(phrase: str, command: str) -> str:
    k, cmd = key(phrase), " ".join((command or "").split()).strip(" .")
    if not k or not cmd:
        return "error: say the words and what they should do, e.g. 'when I say good night, lock the screen'"
    if key(cmd) == k:
        return "error: the words and the command are the same"
    with _lock:
        d = all_words()
        old = d.get(k)
        d[k] = cmd
        _write(d)
    from jarvis.tools.general import _apps
    if k in _apps.taught():  # one meaning per word: the newest wins
        _apps.teach(k, "")
    return f"Got it: when you say '{k}', I'll {cmd}." + (f" (It was: {old}.)" if old and old != cmd else "")


def forget(phrase: str) -> str:
    k = key(phrase)
    with _lock:
        d = all_words()
        if d.pop(k, None) is None:
            return f"'{k}' wasn't one of your words."
        _write(d)
    return f"Forgot '{k}'."


def expand(text: str) -> str:
    """The command the owner's words stand for, or the text unchanged (whole request only, never inside one)."""
    d = all_words()
    return d.get(key(text), text) if d else text
