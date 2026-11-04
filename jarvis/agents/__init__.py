"""Agents: KURAMA's focused helpers, OFF until the owner turns one on (Settings pill / "start coding agent" /
/agent coding). 'general' is plain KURAMA. An agent brings its own tools (offered first), one prompt line and its
own background helpers, which run only while it is on (0 RAM / CPU otherwise). It switches itself off after
AGENT_IDLE_OFF_S without use.

New agent = one new folder, nothing else to edit: jarvis/agents/<name>/__init__.py defines `SPEC = AgentSpec(...)`
(and optionally tools.py with its @tool functions, group = one of SPEC.groups). It is found automatically
(core/plugins.py); a broken agent is logged and skipped, the others keep working. `scripts/new_plugin.py agent X`
writes the skeleton and its test.

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
    aliases: tuple[str, ...] = ()  # other names the owner may say ("code", "coder")
    welcome: Callable[[], str] | None = None  # the sentence said when it turns on (default: "<title> on.")
    status: Callable[[], dict] | None = None  # extra fields for the dashboard while it is on


class _Agents(dict):
    """name -> loader of its AgentSpec, found in this package (the folders are listed without importing them)."""

    def __init__(self) -> None:
        super().__init__()
        from jarvis.core import plugins
        for n in plugins.names(__name__):
            self[n] = (lambda n=n: _load(n))


def _load(name: str) -> AgentSpec | None:
    from jarvis.core import plugins
    sp = plugins.load_one(__name__, name, "SPEC")
    return sp if isinstance(sp, AgentSpec) else None


AGENTS: dict[str, Callable[[], AgentSpec | None]] = _Agents()
_last_use = [0.0]


def title(name: str) -> str:
    if name == "general":
        return "General"
    sp = spec(name)
    return sp.title if sp else name


def _alias(name: str) -> str:
    fixed = {"kurama": "general", "normal": "general", "off": "general", "none": "general"}
    if name in fixed or name in AGENTS:
        return fixed.get(name, name)
    for n in AGENTS:
        if (sp := spec(n)) and name in sp.aliases:
            return n
    return name


def groups() -> tuple[str, ...]:
    """Every agent's own tool groups (never routed to; offered only while that agent is on)."""
    out = list(config.AGENT_GROUPS)
    for n in AGENTS:
        if sp := spec(n):
            out += [g for g in sp.groups if g not in out]
    return tuple(out)


def tool_modules() -> list[str]:
    """jarvis.agents.<name>.tools for every agent that has one (registry.discover imports them)."""
    import importlib.util
    out = []
    for n in AGENTS:
        mod = f"{__name__}.{n}.tools"
        try:
            if importlib.util.find_spec(mod) is not None:
                out.append(mod)
        except (ImportError, ValueError):
            pass
    return out


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
    return AGENTS[name]() if name in AGENTS else None  # None: not an agent, or a broken one (logged)


def touch() -> None:
    """Something was done with the agent: the idle-off clock starts again."""
    _last_use[0] = time.time()


def switch(name: str) -> str:
    """Turn an agent on ('general' = all off). Returns a sentence for the user."""
    name = (name or "general").strip().lower()
    name = _alias(name)
    if name != "general" and spec(name) is None:
        return f"I don't have a '{name}' agent. Agents: general, " + ", ".join(AGENTS) + "."
    old = _stored()
    if old == name:
        touch()
        return f"The {title(name)} is already on." if name != "general" else "Already in General mode."
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
        s = spec(name)
        if s and s.start:
            s.start()
        if s and s.welcome:
            try:
                return s.welcome()
            except Exception as e:  # noqa: BLE001 - the agent is on even if its greeting failed
                log.warning("%s welcome failed: %s", name, e)
        return f"{title(name)} on. Say 'General' when you're done."
    return f"Back to General mode. The {title(old).lower() if old != 'general' else 'agent'} is off."


def prompt_line() -> str:
    s = spec()
    return s.prompt if s else ""


def status() -> dict:
    name = current()
    out = {"name": name, "title": title(name), "agents": ["general", *AGENTS]}
    if name != "general" and (s := spec(name)) and s.status:
        try:
            out.update(s.status())
        except Exception as e:  # noqa: BLE001
            log.warning("%s status failed: %s", name, e)
    return out
