"""The owner's own words: "when I say good night, lock the screen" -> saying "good night" (the whole request) runs
"lock the screen", forever, until the owner changes or forgets it. Kept in data/my_words.json, never trimmed.
An app's name ("when I say code, open VS Code") is _apps.teach instead: it works inside any sentence. Both are
saved by the app_name tool.
Agent.run / Agent.stream swap the request before anything else (0 tokens; the trace keeps what was said)."""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from jarvis.core import config

_lock = threading.Lock()
_NOT_A_PHRASE = {"just", "only", "simply", "open", "just open", "only open", "it", "this", "that"}
_ANSWERS = {"yes", "no", "ok", "okay", "yeah", "yep", "nope", "sure", "stop", "cancel", "next", "back", "done",
            "thanks", "thank you", "haan", "ha", "ho", "hoina", "na", "nahi", "huncha", "hunna", "thik cha"}


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
    if k in _ANSWERS or k in _NOT_A_PHRASE:  # 'when I say just open ...' is a preference, not a phrase for a command  # 'yes' / 'no' answer KURAMA's questions: as a phrase it would swallow every answer
        return f"error: '{k}' is how you answer my questions, so it can't stand for a command. Pick other words."
    with _lock:
        d = all_words()
        old = d.get(k)
        d[k] = cmd
        _write(d)
    from jarvis.tools.general import _apps
    if k in _apps.taught():  # one meaning per word: the newest wins
        _apps.teach(k, "")
    return (f"Got it: when you say '{k}', I'll {cmd}." + (f" (It was: {old}.)" if old and old != cmd else "")
            + _how_it_runs(cmd))


def _how_it_runs(cmd: str) -> str:
    """Whether the saved command is one of the instant (0-token) actions, so the owner knows what it costs."""
    try:
        from jarvis.core import fastpath
        return " It runs instantly (no AI)." if fastpath.match(cmd) is not None else \
            " (The AI will do it each time: make it more exact, e.g. a full folder path, to make it instant.)"
    except Exception:  # noqa: BLE001
        return ""


def forget(phrase: str) -> str:
    k = key(phrase)
    with _lock:
        d = all_words()
        if d.pop(k, None) is None:
            return f"'{k}' wasn't one of your words."
        _write(d)
    return f"Forgot '{k}'."


_WHERE = r"\s+(?:in|with|on|using)\s+(?:the\s+)?(vs\s*code|vscode|code|visual studio code|files?|file manager|nautilus|terminal)$"


def expand(text: str) -> str:
    """The command the owner's words stand for, or the text unchanged (whole request only, never inside one).
    'open kurama project IN VS CODE' is the saved 'open kurama project' too (11-06 it went to the AI, which opened
    ~/projects/myproject); an app named there replaces the saved one ('... in files')."""
    d = all_words()
    if not d:
        return text
    k = key(text)
    if k in d:
        return d[k]
    if (m := re.search(_WHERE, k)) and (base := k[:m.start()].strip()) in d:
        cmd, app = d[base], m.group(1)
        app = "files" if app.startswith(("file", "nautilus")) else "terminal" if app == "terminal" else "vs code"
        return re.sub(r"\s+in\s+(?:vs\s*code|vscode|files?|file manager|terminal)$", "", cmd, flags=re.I) + f" in {app}"
    return text


def path_for(name: str) -> Path | None:
    """The folder a saved command opens, by its name ('kurama project' -> /media/.../KURAMA), or None."""
    k = key("open " + (name or ""))  # (key() drops a leading 'kurama': 'Kurama Project' alone became 'project')
    for phrase, cmd in all_words().items():
        if name and k in (phrase, "open " + phrase):
            if (m := re.match(r"^open\s+(/\S.*?)(?:\s+in\s+[\w ]+)?$", cmd.strip(), re.I)) and Path(m.group(1)).exists():
                return Path(m.group(1))
    return None
