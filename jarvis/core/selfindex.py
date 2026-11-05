"""KURAMA's knowledge of its own tools, built from the code itself (never a hand-kept list that goes stale):
for each tool, what it does (its description), how it works (its file's docstring), which of the owner's settings
it reads (usersettings.related) and how to ask for it (config.TOOL_EXAMPLES). Used to explain "how did you do
that?" (explain_last), to answer "can you...?" (find_capability) and for help (help_me). 0 tokens to build.
tests/test_plugin_contracts.py checks every tool has these parts.
"""
from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass


@dataclass
class Card:
    name: str
    group: str
    what: str
    how: str
    settings: list[str]
    say: list[str]
    direct: bool = False  # saying the need itself runs this tool (the instant shortcut matched it)

    def short(self) -> str:
        """What it does in a few words, for the owner ('Send a file or folder to the phone over Wi-Fi')."""
        import re
        s = re.split(r"(?<=[a-z)])[:.;](?:\s|$)", self.what.strip(), maxsplit=1)[0].strip()
        s = re.sub(r"\bthe user's\b", "your", re.sub(r"\b(?:the user|the owner)\b", "you", s))
        return (s[:1].lower() + s[1:])[:110]

    def ask(self) -> str:
        return f'say "{self.say[0]}"' if self.say else ""

    def text(self, how_chars: int = 600, plain: bool = False) -> str:
        """plain: no internal names (for answers to the owner: 'I look at the get_time tool' sounded like a robot)."""
        from jarvis.core import usersettings
        head = f"ABILITY: {self.what}" if plain else f"TOOL {self.name} ({self.group}): {self.what}"
        how = self.how
        if plain:  # no file / function names: "[netdoctor.speed]", "internet_doctor: ..."
            import re
            how = re.sub(r"\[[\w.]+\]\s*", "", re.sub(r"^\w+:\s*", "", how)).replace(self.name, "this")
        out = [head, f"HOW IT WORKS: {how[:how_chars]}"]
        if self.settings:
            vals = [f"{n} = {usersettings.shown(usersettings.BY_NAME[n])}" for n in self.settings]
            out.append("SETTINGS THE OWNER CAN CHANGE: " + "; ".join(vals))
        if self.say:
            out.append("HOW TO ASK: " + " / ".join(f'"{s}"' for s in self.say[:3]))
        return "\n".join(out)


def _module(t) -> object | None:
    fn = getattr(t, "func", None)
    return sys.modules.get(fn.__module__) if fn is not None else None


def card(name: str) -> Card | None:
    from jarvis.core import config, registry, usersettings
    registry.REGISTRY._ensure()
    t = registry.REGISTRY.tools.get(name)
    if t is None:
        return None
    mod = _module(t)
    how = " ".join((inspect.getdoc(mod) or "").split()) if mod else ""
    try:
        src = inspect.getsource(mod) if mod else ""
    except (OSError, TypeError):
        src = ""
    extra, more_src = _helpers(mod, src)
    how += extra
    src += more_src
    return Card(name, registry.group_of(t), (t.description or "").strip(), how,
                [s.name for s in usersettings.related(src)], list(config.TOOL_EXAMPLES.get(name, ())))


def _first(doc: str | None, n: int = 260) -> str:
    return " ".join((doc or "").split("\n\n")[0].split())[:n]


def _helpers(mod, src: str) -> str:
    """More of HOW from the code: the docstrings of the file's own functions, then of the core modules it uses
    (training -> core/training.py, internet_doctor -> core/netdoctor.py). Built from the code, never hand-kept."""
    import importlib
    import re
    parts = []
    for name, fn in inspect.getmembers(mod, inspect.isfunction) if mod else []:
        if fn.__module__ == mod.__name__ and (d := _first(inspect.getdoc(fn), 200)):
            parts.append(d)
    used = set(re.findall(r"from jarvis\.core import ([\w, ]+?)(?:\s+as\s+\w+)?\s*(?:#|$)", src, re.M))
    names = {n.strip().split(" as ")[0] for grp in used for n in grp.split(",")}
    names |= set(re.findall(r"from jarvis\.core\.(\w+) import", src))
    more = ""
    for n in sorted(names - {"config", "registry", "safety", "store", "llm", "trace", "results"}):
        try:
            m = importlib.import_module(f"jarvis.core.{n}")
            more += inspect.getsource(m)
        except Exception:  # noqa: BLE001
            continue
        if d := _first(inspect.getdoc(m), 300):
            parts.append(f"[{n}] {d}")
        for fname, fn in inspect.getmembers(m, inspect.isfunction):  # the functions of it this tool calls
            if fn.__module__ == m.__name__ and re.search(rf"\.{fname}\(", src) and (d := _first(inspect.getdoc(fn), 260)):
                parts.append(f"[{n}.{fname}] {d}")
    return ((" Details: " + " | ".join(parts))[:1600] if parts else ""), more


def cards_for(names: list[str]) -> list[Card]:
    return [c for n in dict.fromkeys(names) if (c := card(n)) is not None]


def by_meaning(text: str, k: int = 3) -> list[Card]:
    """The tools that would really handle this need, best first (0 tokens), decided the SAME way a request is:
    1. the instant shortcut that would run for it (fastpath.match, nothing is executed);
    2. else the router's areas for it, and inside them the tools closest in meaning (description + example phrases).
    Ranking every tool by its description alone answered 'read my screen' with 'lock the screen'."""
    from jarvis.core import config, registry, semantic
    try:
        semantic.ensure_ready()  # the small local model (~0.6 s if it was unloaded; 0 tokens)
        registry.REGISTRY._ensure()
    except Exception:  # noqa: BLE001
        return []
    first: list[str] = []
    try:
        from jarvis.core import fastpath
        it = fastpath.match(text)
        if it is not None and not it.tool.startswith("_") and it.tool not in _SELF_TOOLS:
            first.append(it.tool)
    except Exception:  # noqa: BLE001
        pass
    try:
        from jarvis.core import router
        groups = [g for g in router.route(text).groups if g != "self"]
    except Exception:  # noqa: BLE001
        groups = []
    scored = []
    for n, t in registry.REGISTRY.tools.items():
        if registry.group_of(t) not in groups or n in first or n in _SELF_TOOLS or not t.description:
            continue
        exs = (t.description.split(". ")[0], *config.TOOL_EXAMPLES.get(n, ())[:6])
        if (b := semantic.best_of(text, "toolcard:" + n, {n: exs})) is not None:
            scored.append((b[1], n))
    scored.sort(reverse=True)
    cards = cards_for(first + [n for s, n in scored if s >= 0.5])[:k]
    if first and cards and cards[0].name == first[0]:
        cards[0].direct = True
    return cards


_SELF_TOOLS = {"find_capability", "help_me", "explain_self", "kurama_settings", "about_me"}
