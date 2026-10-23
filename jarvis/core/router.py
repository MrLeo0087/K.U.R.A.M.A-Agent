"""Tool-group router: keyword rules first, fast-tier classifier only for unmatched commands.

Returns at most config.ROUTER_MAX_GROUPS groups (only groups that have registered tools).
Pure chat routes to no groups, so no tool schemas are sent. Every decision is logged.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

from jarvis.core import config, llm, registry, store

log = logging.getLogger("jarvis.router")


@dataclass
class Route:
    groups: list[str] = field(default_factory=list)
    method: str = "chat"  # rules | classifier | chat
    reasoning: bool = False
    latency_ms: int = 0


def _pattern(words: tuple[str, ...]) -> re.Pattern:
    alts = sorted((re.escape(w.lower()) for w in words), key=len, reverse=True)
    # \w-based boundaries also work for Devanagari words.
    # "(?!\.\w)": "notes.txt" is a file name, not the word "notes".
    return re.compile(r"(?<![\w'])(?:" + "|".join(alts) + r")(?![\w']|\.\w)")


_RULES: dict[str, re.Pattern] = {}
_REASONING: re.Pattern | None = None
_COMMAND: re.Pattern | None = None
_URL = re.compile(r"https?://|(?<![\w@])(?:www\.)?[a-z0-9-]+\.(?:com|org|net|io|ai|dev|np|in|edu|gov|co)\b")


def _compiled() -> tuple[dict[str, re.Pattern], re.Pattern, re.Pattern]:
    global _REASONING, _COMMAND
    if not _RULES:
        _RULES.update({g: _pattern(ws) for g, ws in config.ROUTER_RULES.items() if ws})
        _REASONING = _pattern(config.REASONING_KEYWORDS)
        verbs = "|".join(sorted(map(re.escape, config.COMMAND_VERBS), key=len, reverse=True))
        _COMMAND = re.compile(
            r"^\s*(?:(?:hey\s+)?jarvis[\s,]+)?(?:please\s+)?(?:(?:can|could|would|will)\s+you\s+"
            r"(?:please\s+)?)?(?:" + verbs + r")\b")
    return _RULES, _REASONING, _COMMAND  # type: ignore[return-value]


def rule_groups(text: str) -> list[str]:
    """Groups whose keywords appear in text, most hits first."""
    rules, _, _ = _compiled()
    low = text.lower()
    hits = {g: len(p.findall(low)) for g, p in rules.items()}
    if config.ROUTER_URL_GROUP and _URL.search(low):  # "open example.com" / "https://..."
        hits[config.ROUTER_URL_GROUP] = hits.get(config.ROUTER_URL_GROUP, 0) + 1
    return [g for g, n in sorted(hits.items(), key=lambda kv: -kv[1]) if n]


_SITE: re.Pattern | None = None
_OPEN_VERB = re.compile(r"(?<![\w'])(?:open|launch|start|go to|kholo|khol|खोल)")


def mentions_site(text: str) -> bool:
    """A URL/domain or a known site name (open_url.SITES) appears in text."""
    global _SITE
    if _SITE is None:
        from jarvis.tools.general.open_url import SITES  # lazy: router stays importable alone
        _SITE = _pattern(tuple(SITES))
    low = text.lower()
    return bool(_URL.search(low) or _SITE.search(low))


def site_over_apps(text: str, groups: list[str]) -> list[str]:
    """"open youtube" -> browser, not apps (cheap rule; "open vs code" keeps apps)."""
    if (config.ROUTER_SITE_OVER_APPS and "apps" in groups and "browser" in groups
            and _OPEN_VERB.search(text.lower()) and mentions_site(text)):
        return [g for g in groups if g != "apps"]
    return groups


def looks_like_command(text: str) -> bool:
    _, _, cmd = _compiled()
    return bool(cmd.search(text.lower()))


def needs_reasoning(text: str) -> bool:
    _, rx, _ = _compiled()
    return bool(rx.search(text.lower()))


CLASSIFIER_PROMPT = (
    "Pick the tool groups needed to handle the user's request. Groups:\n{groups}\n"
    "Reply with only the group names, comma-separated (at most {n}), or 'none' if it is "
    "plain conversation. Append 'reasoning' if it needs multi-step thinking."
)


def classify(text: str, available: list[str]) -> tuple[list[str], bool]:
    """Ask the fast tier which groups apply. Returns ([], False) on any error."""
    lines = "\n".join(f"- {g}: {config.TOOL_GROUP_DESCRIPTIONS.get(g, g)}" for g in available)
    msgs = [{"role": "system",
             "content": CLASSIFIER_PROMPT.format(groups=lines, n=config.ROUTER_MAX_GROUPS)},
            {"role": "user", "content": text}]
    try:
        reply = llm.chat(msgs, tier="fast", purpose="router", max_tokens=200, temperature=0)
    except llm.LLMError as e:
        log.warning("router classifier failed: %s", e)
        return [], False
    out = str(reply).lower()
    found = [g for g in available if re.search(rf"\b{re.escape(g)}\b", out)]
    found.sort(key=lambda g: out.find(g))
    return found, "reasoning" in out


def route(text: str, log_it: bool = True) -> Route:
    t0 = time.monotonic()
    available = registry.groups()
    r = Route(reasoning=needs_reasoning(text))
    matched = rule_groups(text)
    if matched:
        r.method = "rules"
        r.groups = site_over_apps(text, [g for g in matched if g in available])
    elif available and looks_like_command(text):
        r.method = "classifier"
        groups, reasoning = classify(text, available)
        r.groups, r.reasoning = groups, r.reasoning or reasoning
    r.groups = r.groups[: config.ROUTER_MAX_GROUPS]
    r.latency_ms = int((time.monotonic() - t0) * 1000)
    if log_it:
        try:
            store.log_routing(text, r.groups, r.method, r.latency_ms)
        except Exception as e:
            log.warning("could not log routing: %s", e)
    return r
