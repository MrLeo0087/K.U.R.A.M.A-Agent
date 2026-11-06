"""The tool registry: every tool the agent may call, with its schema and its PERMISSION.

    read     looks only (list, grep, read, page errors, ports, history, docs, web search…)
    write    changes project files (edit, write): always backed up, undo puts them back
    run      runs something (commands, the project, screenshots): safe-listed, timed out
    phone    reaches the owner's phone (Telegram)

A task gets only the permissions it needs (a change: read + write, the code then runs and checks it; "run it and
tell me": read + run), so a small model can't wander into running things it doesn't need. Two kinds of tools:
the agent's own (tools/builtin.py) and KURAMA's (tools/kurama.py), called through KURAMA's safety layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from coder.core.run import Run


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    permission: str  # read | write | run | phone
    params: dict  # JSON-schema properties
    required: tuple[str, ...]
    fn: Callable[..., str]

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": {
            "type": "object", "properties": self.params, "required": list(self.required)}}}


TOOLS: dict[str, Tool] = {}


def register(name: str, description: str, permission: str, fn: Callable[..., str], params: dict | None = None,
             required: tuple[str, ...] = ()) -> None:
    TOOLS[name] = Tool(name, description, permission, params or {}, required, fn)


# the two "tools" that end a turn (handled by the loop itself)
CONTROL = [
    {"type": "function", "function": {"name": "done", "description": "The goal is reached: say what you did in 1-3 "
                                      "short sentences.", "parameters": {"type": "object", "properties": {
                                          "summary": {"type": "string"}}, "required": ["summary"]}}},
    {"type": "function", "function": {"name": "ask", "description": "Ask the owner ONE question (a real choice, or a "
                                      "command that NEEDS_YES).", "parameters": {"type": "object", "properties": {
                                          "question": {"type": "string"}, "command": {"type": "string"}},
                                          "required": ["question"]}}},
]


def schemas(permissions: set[str], only: set[str] | None = None) -> list[dict]:
    _load()
    out = [t.schema() for t in TOOLS.values() if t.permission in permissions and (only is None or t.name in only)]
    return out + CONTROL


def call(run: Run, name: str, args: dict | None) -> str:
    _load()
    t = TOOLS.get(name)
    if t is None:
        return f"no tool '{name}'. Tools: {', '.join(TOOLS)}"
    try:
        fn: Any = t.fn
        return fn(run, **{k: v for k, v in (args or {}).items() if k in fn.__code__.co_varnames})
    except Exception as e:  # noqa: BLE001 - a tool error is an observation, never a crash of the loop
        return f"tool error: {type(e).__name__}: {str(e)[:300]}"


_loaded = False


def _load() -> None:
    """Fill the registry once: the agent's own tools, then KURAMA's."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    from coder.tools import builtin, kurama
    builtin.register_all()
    kurama.register_all()
