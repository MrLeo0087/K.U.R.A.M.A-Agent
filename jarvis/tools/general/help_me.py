"""help_me: what KURAMA can do, by area, with real ways to ask (from the tools' own examples), or for one need:
the closest tools by meaning (core/selfindex.py). 0 tokens. For a stuck or confused owner (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="self", safety="safe", max_chars=3500,
      description="Help using KURAMA: every area with example commands, or (topic) the commands closest to a need.")
def help_me(topic: str = "") -> str:
    """Help.

    Args:
        topic: A need or area ("files", "send to my phone", "training"); empty = everything by area.
    """
    from jarvis.core import config, registry, selfindex
    if topic.strip():
        cards = selfindex.by_meaning(topic, 4)
        if not cards:
            return f"I didn't find a command for '{topic}'. " + _teach()
        lines = [f"- {c.what}" + (f" Say: \"{c.say[0]}\"" if c.say else "") for c in cards]
        return f"For '{topic}', try:\n" + "\n".join(lines) + "\n" + _teach()
    registry.REGISTRY._ensure()
    by_group: dict[str, list[str]] = {}
    for n, t in registry.REGISTRY.tools.items():
        g = registry.group_of(t)
        if g == "core" or not config.TOOL_EXAMPLES.get(n):
            continue
        by_group.setdefault(g, []).extend(config.TOOL_EXAMPLES[n][:1])
    lines = []
    for g in sorted(by_group):
        about = (config.TOOL_GROUP_DESCRIPTIONS.get(g) or g).split(",")[0].split("(")[0].strip()
        lines.append(f"- {g}: {about}. e.g. " + " / ".join(f'"{e}"' for e in by_group[g][:2]))
    return ("What I can do (ask \"help with <something>\" for one area, \"how did you do that?\" after any answer, "
            "\"what settings can I change?\"):\n" + "\n".join(lines) + "\n" + _teach())


def _teach() -> str:
    return ("Your own command: \"when I say <words>, <what to do>\". Nothing fits? I can build a small new tool for "
            "it (I ask first).")
