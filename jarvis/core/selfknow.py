"""KURAMA's knowledge about itself (docs/kurama_self.md) + the owner password gate for sensitive parts.

The password is never stored in plain text (config.SELF_PASSWORD_HASH = sha256(salt + normalized password)) and a
message that is only the password is redacted before it is saved to history.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from pathlib import Path

from jarvis.core import config

DOC = config.ROOT / "docs" / "kurama_self.md"
_state = {"pending": "", "pending_ts": 0.0, "unlocked_until": 0.0, "fails": 0}
_PW_LEAD = re.compile(r"^(?:(?:the|my)\s+)?(?:password|passcode|pass|पासवर्ड)\s*(?:is|:|हो|है)?\s*|^(?:it'?s|it is)\s+",
                      re.I)
def _aliases() -> dict[str, str]:
    """KURAMA_PASSWORD_ALIASES (.env): 'heard=meant' pairs, comma-separated (never in the code: the repo is public)."""
    return {a.strip().lower(): b.strip().lower() for a, _, b in
            (p.partition("=") for p in config.SELF_PASSWORD_ALIASES.split(",")) if a.strip() and b.strip()}


def _norm_pw(text: str) -> str:
    t = re.sub(r"[^\w\s:']", " ", (text or "").strip().lower(), flags=re.U)
    t = _PW_LEAD.sub("", " ".join(t.split()))
    return _aliases().get(t, t).replace(" ", "")


def hash_for(password: str) -> str:
    """The value for KURAMA_PASSWORD_HASH in .env (python -m jarvis.core.selfknow asks for a new password)."""
    return hashlib.sha256((config.SELF_PASSWORD_SALT + _norm_pw(password)).encode()).hexdigest()


def check_password(text: str) -> bool:
    digest = hashlib.sha256((config.SELF_PASSWORD_SALT + _norm_pw(text)).encode()).hexdigest()
    return hmac.compare_digest(digest, config.SELF_PASSWORD_HASH)


_NOT_PW = re.compile(r"^\s*(?:what|how|why|who|where|when|open|close|play|show|tell|change|set|make|create|search|"
                     r"stop|cancel|no|never ?mind|forget|hey|hi|hello|ok|okay|yes)\b", re.I)


def looks_like_password_try(text: str) -> bool:
    """A short answer right after "say the password". Anything else drops the question (the user moved on)."""
    if not pending():
        return False
    t = (text or "").strip()
    if check_password(t) or (0 < len(t.split()) <= 3 and not _NOT_PW.match(t)):
        return True
    _state["pending"] = ""
    return False


def redact(text: str) -> str:
    """History never keeps the password."""
    return "[password given]" if check_password(text) else text


def unlocked() -> bool:
    return time.time() < _state["unlocked_until"]


def pending() -> str:
    if _state["pending"] and time.time() - _state["pending_ts"] > config.SELF_PENDING_S:
        _state["pending"] = ""
    return _state["pending"]


def try_unlock(text: str) -> str:
    """The user answered the password question: unlock and return the waiting topic, or refuse."""
    topic = pending()
    if check_password(text):
        _state.update(unlocked_until=time.time() + config.SELF_UNLOCK_S, pending="", fails=0)
        return "Thank you, that's correct. " + section(topic)
    _state["fails"] += 1
    if _state["fails"] >= 2:
        _state.update(pending="", fails=0)
        return "Sorry, that's not the right password, so I can't share that."
    return "Sorry, that's not the right password. Please try once more."


def _sections() -> dict[str, tuple[bool, str]]:
    out: dict[str, tuple[bool, str]] = {}
    try:
        raw = DOC.read_text(encoding="utf-8")
    except OSError:
        return out
    for m in re.finditer(r"^## (\w+)(\s*\[locked\])?\s*\n(.*?)(?=^## |\Z)", raw, re.M | re.S):
        out[m.group(1).lower()] = (bool(m.group(2)), m.group(3).strip())
    return out


def _facts() -> dict[str, str]:
    from jarvis.core import identity
    from jarvis.core.registry import REGISTRY
    try:
        from jarvis.core import store
        owner = store.profile_get("name") or "my owner"
    except Exception:
        owner = "my owner"
    groups = REGISTRY.groups()
    return {
        "name": identity.name(), "owner": owner, "root": str(config.ROOT), "data_dir": str(config.DATA_DIR),
        "outputs_dir": str(config.OUTPUTS_DIR), "db_path": str(config.DB_PATH), "memory_db": str(config.MEMORY_DB_PATH),
        "log_dir": str(config.LOG_DIR), "skills_dir": str(config.SKILLS_DIR), "sandbox_dir": str(config.SANDBOX_DIR),
        "models_dir": str(config.EMBED_CACHE_DIR), "env_path": str(config.ROOT / ".env"),
        "llm_smart": config.LLM_DEFAULT, "llm_fast": config.LLM_FAST, "llm_voice": config.LLM_VOICE,
        "stt": config.STT_MODEL, "unlock_min": str(int(config.SELF_UNLOCK_S // 60)),
        "group_count": str(len(groups)), "tool_count": str(sum(len(REGISTRY.schemas_for([g])) for g in groups)),
    }


def topics() -> list[str]:
    return list(_sections())


def is_locked(topic: str) -> bool:
    return _sections().get(topic, (False, ""))[0]


def section(topic: str) -> str:
    s = _sections()
    if topic not in s:
        return f"I don't have notes about {topic!r}; I know about: {', '.join(s)}."
    body = re.sub(r"\n(?!- )\s*", " ", s[topic][1])  # unwrap paragraphs, keep "- " list lines
    try:
        return body.format(**_facts())
    except (KeyError, IndexError, ValueError):
        return body


def ask(topic: str) -> str:
    """Public topics at once; locked ones only after the password (asks for it and remembers the topic)."""
    topic = (topic or "overview").strip().lower()
    if is_locked(topic) and not unlocked():
        _state.update(pending=topic, pending_ts=time.time(), fails=0)
        return ("LOCKED: this is protected information. Ask the user to say the password first "
                "(do not guess or mention it). Their next message will be checked automatically.")
    return section(topic)


def find_tools(need: str, k: int = 6) -> list[tuple[str, str, str]]:
    """(group, tool, description) of the tools that best match a need, by word overlap (0 tokens)."""
    from jarvis.core.registry import REGISTRY, group_of
    words = {w for w in re.findall(r"[a-z0-9]+", need.lower()) if len(w) > 2} - _STOP
    if not words:
        return []
    scored = []
    for g in REGISTRY.groups():
        gloss = config.TOOL_GROUP_DESCRIPTIONS.get(g, "").lower()
        for t in REGISTRY.schemas_for([g]):
            text = f"{t.name.replace('_', ' ')} {t.description} {g} {gloss}".lower()
            score = sum(3 if w in t.name else 1 for w in words if w in text)
            if score:
                scored.append((score, group_of(t), t.name, t.description))
    scored.sort(key=lambda x: -x[0])
    return [(g, n, d) for _, g, n, d in scored[:k]]


_STOP = set("""the and for you can with want need how what that this have does any some make tool tools
your there about from into please would could should help like know tell use using""".split())


if __name__ == "__main__":  # set a new owner password: prints the line to put in .env
    import getpass
    pw = getpass.getpass("New KURAMA password: ")
    if pw and pw == getpass.getpass("Again: "):
        print(f"Put this in .env (replace the old line), then restart KURAMA:\nKURAMA_PASSWORD_HASH={hash_for(pw)}")
    else:
        print("The two passwords were empty or different; nothing changed.")
