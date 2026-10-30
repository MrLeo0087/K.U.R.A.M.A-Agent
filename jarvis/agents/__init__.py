"""Agents: KURAMA's focused helpers, OFF until the owner turns one on (Settings pill / "start coding agent" /
/agent coding). 'general' is plain KURAMA. An agent brings its own tools (offered first), one prompt line and its
own background helpers, which run only while it is on (0 RAM / CPU otherwise). It switches itself off after
AGENT_IDLE_OFF_S without use. New agents: add a module in this package and an entry in AGENTS.

The active agent is kept in the kv table (every process sees it) and in ~/.local/share/kurama/agent (the VS Code
extension reads that file to know whether to watch the terminal).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from jarvis.core import config

log = logging.getLogger(__name__)


@dataclass
class AgentSpec:
    name: str
    title: str
    groups: tuple[str, ...] = ()  # tool groups offered first while on
    prompt: str = ""  # one line added to the system prompt while on
    start: Callable[[], None] | None = None
    stop: Callable[[], None] | None = None
    examples: dict[str, tuple[str, ...]] = field(default_factory=dict)  # meaning -> phrasings (0-token routing)


def _coding() -> AgentSpec:
    from jarvis.agents import coding
    return coding.SPEC


AGENTS: dict[str, Callable[[], AgentSpec]] = {"coding": _coding}
TITLES = {"general": "General", "coding": "Coding agent"}
_last_use = [0.0]


def marker() -> Path:
    return Path(config.AGENT_MARKER)


def _stored() -> str:
    try:
        from jarvis.core import store
        name = store.kv_get("agent") or "general"
    except Exception:  # noqa: BLE001
        name = "general"
    return name if name in AGENTS else "general"


def current() -> str:
    """The agent that is on ('general' = none). Switches itself off after AGENT_IDLE_OFF_S unused."""
    name = _stored()
    if name != "general" and not _last_use[0]:
        touch()  # on since before a restart: the idle clock starts now, its helpers start again
        if (sp := spec(name)) and sp.start:
            try:
                sp.start()
            except Exception as e:  # noqa: BLE001
                log.warning("starting %s failed: %s", name, e)
    if name != "general" and time.time() - _last_use[0] > config.AGENT_IDLE_OFF_S:
        log.info("%s agent off after %.0f min unused", name, config.AGENT_IDLE_OFF_S / 60)
        switch("general")
        return "general"
    return name


def spec(name: str | None = None) -> AgentSpec | None:
    name = name or current()
    return AGENTS[name]() if name in AGENTS else None


def touch() -> None:
    """Something was done with the agent: the idle-off clock starts again."""
    _last_use[0] = time.time()


def switch(name: str) -> str:
    """Turn an agent on ('general' = all off). Returns a sentence for the user."""
    name = (name or "general").strip().lower()
    name = {"code": "coding", "coder": "coding", "programming": "coding", "kurama": "general", "normal": "general",
            "off": "general", "none": "general"}.get(name, name)
    if name != "general" and name not in AGENTS:
        return f"I don't have a '{name}' agent. Agents: general, " + ", ".join(AGENTS) + "."
    old = _stored()
    if old == name:
        touch()
        return f"The {TITLES.get(name, name)} is already on." if name != "general" else "Already in General mode."
    from jarvis.core import store
    if old != "general" and (s := spec(old)) and s.stop:
        try:
            s.stop()
        except Exception as e:  # noqa: BLE001
            log.warning("stopping %s failed: %s", old, e)
    store.kv_set("agent", name)
    try:
        m = marker()
        if name == "general":
            m.unlink(missing_ok=True)
        else:
            m.parent.mkdir(parents=True, exist_ok=True)
            m.write_text(name)
    except OSError as e:
        log.warning("agent marker: %s", e)
    if name != "general":
        touch()
        if (s := spec(name)) and s.start:
            s.start()
        return (f"{TITLES[name]} on. Run your code in the VS Code terminal: if it crashes I'll tell you and fix it. "
                f"Say 'stop coding agent' (or General) when you're done.")
    return "Back to General mode. The coding agent is off."


def prompt_line() -> str:
    s = spec()
    return s.prompt if s else ""


def status() -> dict:
    name = current()
    return {"name": name, "title": TITLES.get(name, name), "agents": ["general", *AGENTS]}
