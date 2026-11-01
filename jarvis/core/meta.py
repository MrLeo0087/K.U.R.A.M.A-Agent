"""Freedom routing (P7b): the `request_tools` meta-tool.

When the router finds no group and the message is not small talk, the agent binds ONE compact
meta-tool whose description lists every tool group with a 3-6 word gloss. If the model calls it,
the agent binds those groups' real tools for the next round. A tool-less answer that reads like
"I can't / no tool" is retried once with the meta-tool bound.
"""
from __future__ import annotations

import json
import re

from jarvis.core import config, registry

NAME = "request_tools"
HINT = ("Tool groups are available through request_tools. If one fits the user's request, call it now. "
        "If none fits but it is a real task doable on this computer, request toolsmith. "
        "Otherwise reply kindly in one short sentence that you can't do that yet.")
DO_IT_HINT = "You answered without calling a tool, so nothing happened. If a tool you have fits, call it now."
TOOLSMITH_HINT = ("No tool exists for this task yet: call make_tool now (it asks the user before building "
                  "anything) instead of saying you can't.")
LOADED = "Loaded tools for: {groups}. Call the right tool now."
_cache: dict[tuple[str, ...], dict] = {}

# Inability phrasing (en/hi/ne), checked on the first ~240 chars of a tool-less answer.
_REFUSAL = re.compile(
    r"\b(?:i\s+(?:don'?t|do not)\s+(?:currently\s+|really\s+|yet\s+|actually\s+)?have\s+(?:a\s+way|any\s+way|"
    r"access|the\s+ability|real[- ]time|live|internet|browsing|tools?|a\s+tool|any\s+tools?)|"
    r"there(?:'s| is)\s+no\s+tool|i\s+(?:can'?t|cannot|can not|am unable|'m unable|am not able|'m not able)|"
    r"no\s+(?:tool|way to|access to)|unable to|not able to|i\s+(?:don'?t|do not)\s+know|"
    r"i\s+(?:don'?t|do not)\s+have\s+(?:that|this|any)\s+information|i'?m\s+not\s+sure\s+(?:about|what|where|how)|"
    r"i\s+have\s+no\s+(?:way|access|tool)|beyond my (?:capabilities|abilities)|as an ai)"
    r"|मैं नहीं|नहीं कर सकत|नहीं बता सकत|सक्दिन|सक्दैन|थाहा छैन|पता नहीं", re.I)


# Claiming an action ("I've set a timer", "Sure, opening X") when no tool ran: the action never happened.
_CLAIM = re.compile(
    r"^\W*(?:(?:sure|okay|ok|done|alright|got it)\W+)?(?:i'?ve|i have|i'll|i will|i'm|i am)\s+(?:now\s+|just\s+)?"
    r"(?:set|opened|open|opening|started|start|starting|sent|send|sending|turned|turn|turning|added|add|adding|created|"
    r"scheduled|saved|save|played|play|playing|closed|close|closing|muted|launched|remind|reminded)\b(?!\s+to\b)|"
    r"^\W*(?:sure|okay|ok|alright|got it)\W+(?:opening|starting|setting|sending|turning|playing|closing|launching|muting)\b",
    re.I)


def looks_like_refusal(text: str) -> bool:
    return bool(_REFUSAL.search((text or "")[:240].replace("\u2019", "'")))  # curly apostrophes too


# the state-change verbs (a closed set: what KURAMA's tools do), in every form an answer reports them
_ACT = (r"(?:add|sav|clear|remov|delet|edit|updat|cop|creat|open|clos|mov|renam|start|stopp|install|download|upload|"
        r"replac|fix|connect|unlock|lock|kill|mut|play|paus|schedul|set|sen|writ|chang|empti|turn)")
_DONE = re.compile(r"\b(?:i'?ve|i have)\s+(?:now\s+|just\s+|already\s+)?" + _ACT + r"\w*\b|"
                   r"\b(?:has|have)\s+(?:now\s+)?been\s+" + _ACT + r"\w*\b|"
                   # "Chat cleared.", "Added to your list.", "Edited test.py ...", "Saved the URL ... as notion"
                   r"^\W*(?:(?!(?:is|are|was|were|be|been|gets?|got)\b)[\w-]+[,:]?\s+){0,3}(?:added|saved|cleared|removed|deleted|edited|updated|copied|created|"
                   r"opened|closed|moved|renamed|installed|downloaded|uploaded|replaced|written|sent|emptied)\b(?!\s+(?:by|to\s+be))|"
                   # "The link is saved as notion", "Your reminder was set"
                   r"\b(?:your|the|it|this|that|all|everything)\b[^.!?\n]{0,40}?\b(?:is|are|was|were)\s+(?:now\s+|successfully\s+)?(?:saved|added|cleared|removed|deleted|copied|"
                   r"created|renamed|updated|edited|sent|set|emptied|downloaded|installed|closed|opened|minimized|started|"
                   r"stopped|muted|paused|moved|switched|turned\s+(?:on|off))\b(?!\s+(?:by|when|if|with|using|from|through|via))|"
                   # "The path is now in your clipboard", "Your link store is now empty"
                   r"\b(?:is|are)\s+now\s+(?:in\s+your|empty|clear|gone|on|off|open|closed|saved|set|playing|muted|"
                   r"running|downloading|installed|active|visible|showing|minimized|closed)\b|"
                   # "You're now on the home screen", "Opening https://nepalgon.com." (traces 11-01 09:35)
                   r"\byou(?:'re|\s+are)\s+now\s+(?:on|in|at|back)\b|"
                   r"^\W*(?:opening|closing|launching|switching|showing|minimizing|muting|playing)\s+(?!(?:a|an|some|any)\b)\S|"
                   # "I'm writing 'yes' into main.txt right now", "Writing ... in the background"
                   r"^\W*(?:sure\W+|okay\W+)?(?:i'?m|i am)?\s*(?:now\s+)?(?:writing|saving|copying|deleting|removing|"
                   r"clearing|downloading|sending|creating|moving|editing|updating)\b", re.I)


def claims(text: str) -> bool:
    """The answer says an action was done ("I've opened...", "Sure, playing...", "the link has been removed")."""
    t = (text or "")[:240].replace("\u2019", "'")
    return bool(_CLAIM.search(t) or _DONE.search(t))


def needs_tool(text: str) -> bool:
    """A tool-less answer that refuses, or claims an action no tool did: retried once with request_tools."""
    t = (text or "")[:240].replace("\u2019", "'")
    return looks_like_refusal(t) or bool(_CLAIM.search(t) or _DONE.search(t))


def gloss(group: str) -> str:
    if group == "skills":  # saved toolsmith skills: their names say what they do
        return ", ".join(t.name for t in registry.schemas_for(["skills"])[:6])
    if group in config.TOOL_GROUP_GLOSS:
        return config.TOOL_GROUP_GLOSS[group]
    return " ".join(config.TOOL_GROUP_DESCRIPTIONS.get(group, group).split()[:4]).rstrip(",;")


def schema(groups: list[str] | None = None) -> dict:
    """OpenAI-format tool dict (cached per group set). Group names live only in the description (no enum:
    it would repeat all 23 names); pick() validates. About 150 prompt tokens."""
    avail = tuple(sorted(groups if groups is not None else registry.groups()))
    if avail not in _cache:
        listing = ", ".join(f"{g}({gl})" if (gl := gloss(g)) else g for g in avail)
        _cache[avail] = {"type": "function", "function": {
            "name": NAME,
            "description": f"Load tool groups: {listing}",
            "parameters": {"type": "object", "properties": {
                "groups": {"type": "array", "items": {"type": "string"},
                           "description": f"1-{config.ROUTER_MAX_GROUPS} groups"},
                "reason": {"type": "string"}},
                "required": ["groups", "reason"]}}}
    return _cache[avail]


def estimate_tokens(groups: list[str] | None = None) -> int:
    return len(json.dumps(schema(groups), ensure_ascii=False)) // 4 + 1


def tool_name(t: object) -> str:
    """Name of a LangChain tool or an OpenAI-format dict."""
    if isinstance(t, dict):
        return (t.get("function") or {}).get("name", "")
    return getattr(t, "name", "")


def is_meta(t: object) -> bool:
    return tool_name(t) == NAME


def pick(args: object) -> list[str]:
    """Valid, de-duplicated groups from a request_tools call (at most ROUTER_MAX_GROUPS)."""
    raw = args.get("groups") if isinstance(args, dict) else None
    if isinstance(raw, str):
        raw = [x for x in re.split(r"[,\s]+", raw) if x]
    avail = set(registry.groups())
    out: list[str] = []
    for g in raw or []:
        g = str(g).strip().lower()
        if g in avail and g not in out:
            out.append(g)
    return out[: config.ROUTER_MAX_GROUPS]
