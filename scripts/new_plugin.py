"""Write the skeleton of a new tool, memory source or agent, plus its test (`make new-tool NAME=x` etc.).

    venv/bin/python scripts/new_plugin.py tool  word_count --group general --safety safe
    venv/bin/python scripts/new_plugin.py memory bookmarks
    venv/bin/python scripts/new_plugin.py agent  study

Nothing else needs editing: tools, memory sources and agents are found by themselves. Never overwrites a file.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TOOL = '''"""{name}: TODO one line: what it does ({safety})."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="{group}", safety="{safety}", description="TODO: one line the AI reads to decide when to use this tool.")
def {name}(text: str = "") -> str:
    """TODO: one line.

    Args:
        text: TODO what the argument means.
    """
    if not text.strip():
        return "error: give me some text"
    return f"TODO: the answer for {{text!r}}"  # return a short sentence; or results.Reply(text, paths=[...])
'''
TOOL_TEST = '''"""{name}: mocked test (no network, no real AI)."""
from __future__ import annotations

from jarvis.core import registry


def test_{name}_runs():
    registry.REGISTRY.discover()
    res = registry.call("{name}", {{"text": "hello"}})
    assert res.ok and "hello" in res.output
    assert not registry.call("{name}", {{"text": ""}}).output.startswith("TODO")
'''
MEMORY = '''"""{title}: TODO one line: what this memory holds."""
from __future__ import annotations

from jarvis.core.memories import Hit, MemorySource, words


def _search(query: str, k: int) -> list[Hit]:
    items: list[dict] = []  # TODO: read your data (a store table, a JSON file under config.DATA_DIR, ...)
    q = words(query)
    found = [it for it in items if q & words(it["text"])]
    return [Hit(it["text"], ref=str(it.get("id", ""))) for it in found[:k]]


SOURCE = MemorySource("{name}", "TODO: one line for the owner", _search)
'''
MEMORY_TEST = '''"""Memory source {name}: mocked test."""
from __future__ import annotations

from jarvis.core import memories


def test_{name}_source_searches():
    src = memories.sources()["{name}"]
    assert src.search("anything", 3) == [] or all(isinstance(h, memories.Hit) for h in src.search("anything", 3))
'''
AGENT = '''"""The {name} agent: TODO what it helps with. Off until the owner turns it on ("start {name} agent")."""
from __future__ import annotations

from jarvis.agents import AgentSpec

EXAMPLES: dict[str, tuple[str, ...]] = {{
    "TODO_action": ("TODO a way the owner says it", "TODO another way"),
}}

SPEC = AgentSpec(
    name="{name}", title="{title} agent", groups=("{name}_agent",),
    prompt="{title} agent ON: TODO one line for the AI about what to do while this agent is on.",
    examples=EXAMPLES, aliases=())
'''
AGENT_TOOLS = '''"""Tools of the {name} agent: offered only while it is on (group {name}_agent)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="{name}_agent", safety="safe", description="TODO: what this agent tool does.")
def {name}_agent(request: str = "") -> str:
    """TODO.

    Args:
        request: What the owner asked.
    """
    return f"TODO: {{request}}"
'''
AGENT_TEST = '''"""The {name} agent: found by itself, turns on and off (mocked)."""
from __future__ import annotations

from jarvis import agents


def test_{name}_agent_loads_and_switches():
    sp = agents.spec("{name}")
    assert sp is not None and sp.name == "{name}"
    assert "on" in agents.switch("{name}").lower() and agents.current() == "{name}"
    agents.switch("general")
'''


def write(path: Path, text: str) -> None:
    if path.exists():
        sys.exit(f"{path.relative_to(ROOT)} already exists: nothing written")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    print("wrote", path.relative_to(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=["tool", "memory", "agent"])
    ap.add_argument("name")
    ap.add_argument("--group", default="general", help="tool group (tools only)")
    ap.add_argument("--safety", default="safe", choices=["safe", "confirm", "blocked"], help="tools only")
    a = ap.parse_args()
    name = a.name.strip().lower().replace("-", "_")
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", name):
        sys.exit("name: lower-case letters, digits and _ (e.g. word_count)")
    fmt = {"name": name, "title": name.replace("_", " ").capitalize(), "group": a.group, "safety": a.safety}
    if a.kind == "tool":
        write(ROOT / "jarvis/tools/general" / f"{name}.py", TOOL.format(**fmt))
        write(ROOT / "tests" / f"test_tool_{name}.py", TOOL_TEST.format(**fmt))
    elif a.kind == "memory":
        write(ROOT / "jarvis/memories" / f"{name}.py", MEMORY.format(**fmt))
        write(ROOT / "tests" / f"test_memory_{name}.py", MEMORY_TEST.format(**fmt))
    else:
        write(ROOT / "jarvis/agents" / name / "__init__.py", AGENT.format(**fmt))
        write(ROOT / "jarvis/agents" / name / "tools.py", AGENT_TOOLS.format(**fmt))
        write(ROOT / "tests" / f"test_agent_{name}.py", AGENT_TEST.format(**fmt))
    print("next: fill in the TODOs, then `make test-fast` and `make lint`")


if __name__ == "__main__":
    main()
