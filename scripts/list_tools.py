"""Print every registered tool as a markdown table: group | tool | safety | description.

    venv/bin/python scripts/list_tools.py > /tmp/tools.md
Used to keep the tool table at the end of README.md current.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.core.registry import REGISTRY, group_of, safety_of  # noqa: E402


def rows() -> list[tuple[str, str, str, str]]:
    REGISTRY.discover()
    out = []
    for g in REGISTRY.groups():
        for t in REGISTRY.schemas_for([g]):
            desc = (t.description or "").strip().splitlines()[0] if t.description else ""
            out.append((group_of(t), t.name, safety_of(t), desc.replace("|", "/")))
    return out


def main() -> int:
    r = rows()
    print(f"{len(r)} tools in {len({x[0] for x in r})} groups.\n")
    print("| Group | Tool | Safety | What it does |")
    print("|---|---|---|---|")
    for g, n, s, d in r:
        print(f"| {g} | `{n}` | {s} | {d} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
