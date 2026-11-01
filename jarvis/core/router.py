"""Tool-group router: keyword rules first, fast-tier classifier only for unmatched commands.

Returns at most config.ROUTER_MAX_GROUPS groups (only groups that have registered tools).
Pure chat routes to no groups, so no tool schemas are sent. Every decision is logged.
"""
from __future__ import annotations

import logging
import difflib
import re
import time
from dataclasses import dataclass, field

from jarvis.core import config, llm, registry, semantic, store

log = logging.getLogger("jarvis.router")


@dataclass
class Route:
    groups: list[str] = field(default_factory=list)
    method: str = "chat"  # rules | classifier | chat | meta | fastpath
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


# Hindi/Nepali command verbs (stems): open, tell, show, do, run, close, put on, play, give, make...
_DEVA_CMD = re.compile(r"(?:खोल|बताउ|बताओ|बताइ|बता द|देखाउ|दिखा|गर्नु|गरिदे|गर|करो|कर द|चलाउ|चलाओ|बन्द|"
                       r"बंद|लगाउ|लगाओ|बजाउ|बजाओ|दिनु|दो|बनाउ|बनाओ|सुनाउ|सुनाओ|लेख|लिख|खोज|ढूंढ)")


def looks_like_command(text: str) -> bool:
    _, _, cmd = _compiled()
    if _DEVA_CMD.search(text):  # Hindi/Nepali imperative (keyword lists are thin there)
        return True
    return bool(cmd.search(text.lower()))


def needs_reasoning(text: str) -> bool:
    _, rx, _ = _compiled()
    return bool(rx.search(text.lower()))


# Obvious small talk: no tools and no request_tools meta-tool (cheap regex, 0 tokens).
_SMALL = (r"hi+|hello+|hey+|yo|namaste|namaskar|नमस्ते|नमस्कार|good (?:morning|afternoon|evening|night)|"
          r"thanks?(?: you)?(?: so much| a lot| very much)?|thank you|thx|ty|ok(?:ay)?|cool|nice|great|"
          r"awesome|perfect|bye|goodbye|good ?bye|see you(?: later)?|sorry|how are you(?: doing)?(?: today)?|"
          r"how(?:'s| is) it going|what'?s up|sup|how do you do|nice to meet you|who are you|"
          r"what(?:'s| is) your name|yes|no|yeah|yep|nope|sure|dhanyabad|dhanyavad|dhanyavaad|धन्यवाद|"
          r"शुक्रिया|kasto cha|k cha|कस्तो छ|के छ|कैसे हो|आप कैसे हैं|thik cha|ठीक छ|haha|lol")
_SMALL_TALK = re.compile(r"^(?:[\s,!.?]*(?:(?:hey\s+)?(?:jarvis|kurama)|" + _SMALL + r")\b)+[\s,!.?]*$", re.I)


def is_small_talk(text: str) -> bool:
    return bool(_SMALL_TALK.match(text.strip()))


# "who is X" / "what is X" with no other match -> web (not "what is the time / your name / this").
_WEB_QUESTION = re.compile(
    r"^\s*(?:(?:hey\s+)?(?:jarvis|kurama)[\s,]+)?(?:(?:can|could)\s+you\s+tell\s+me\s+|do\s+you\s+know\s+|tell\s+me\s+)?"
    r"(?:who|what)(?:\s+(?:is|was|are|were)|'s|'re)\s+(?!(?:the\s+)?(?:time|date|day|weather|your|you|my|me|"
    r"this|that|it|up|i)\b)[^\d\s(]", re.I)
_EXPLICIT_WEB = re.compile(r"\b(?:google|web|internet|online|wikipedia|wiki|news|headlines|who (?:is|was)|"
                           r"duckduckgo)\b", re.I)
_LOCAL_GROUPS = frozenset(("files", "knowledge", "memory", "git", "dev", "usage", "jobs", "clipboard",
                           "windows", "apps", "system", "watch"))
_PROJECT_Q = re.compile(r"\b(?:what|explain|describe|summari[sz]e|tell me about|overview|purpose|how does)\b"
                        r".*\b(?:this|the|my|our)\s+(?:project|repo|repository|codebase|code\s*base|code)\b", re.I)


_GIT_ACTION = re.compile(r"\b(?:git (?:status|log|diff)|branch|checkout|(?<!-)(?<!last )commit (?:it|this|them|that|"
                         r"the changes|my changes|everything|all)|and commit|then commit)\b", re.I)


# "generate/create/make a requirements.txt", "requirements banao": devutils.
_GEN_REQ = re.compile(
    r"\b(?:generate|create|make|write|build|produce|regenerate|auto-?generate)\s+(?:(?:a|an|the|new|my|me|fresh|"
    r"pinned|proper|updated)\s+){0,3}requirements\b|\brequirements(?:\.txt)?(?:\s+(?:file|फाइल))?\s+(?:banao|"
    r"bana\s+do|banau|banaideu|banaidinu|generate|create|बनाओ|बना\s+दो|बनाउ|बनाइदेउ|बनाऊ|बनाइदिनु|तयार)", re.I)
_BROAD = re.compile(r"\b(?:this|my|the|a)?\s*(?:project|projects|repo|repository|code|training|runs?|"
                    r"experiments?|results?)\b")
_DEVUTILS_DROP = frozenset(("knowledge", "files", "filesearch", "codequality"))


def devutils_refine(text: str, groups: list[str]) -> list[str]:
    """devutils phrases win over the broad groups they overlap (dev "notebook", git "diff", knowledge
    "this project"); other groups stay only if they still match once the devutils words are removed."""
    if _GEN_REQ.search(text):
        groups = ["devutils"] + [g for g in groups if g != "devutils"]
    if "devutils" not in groups or len(groups) == 1:
        return groups
    rules, _, _ = _compiled()
    rest = _GEN_REQ.sub(" ", rules["devutils"].sub(" ", text.lower())) if "devutils" in rules else text.lower()
    keep = set(rule_groups(_BROAD.sub(" ", rest)))
    return [g for g in groups if g == "devutils" or (g in keep and g not in _DEVUTILS_DROP)
            and (g != "git" or _GIT_ACTION.search(text))]


def refine(text: str, groups: list[str]) -> list[str]:
    """Cheap post-rules: "search my notes" / "latest commit" stay local (drop web unless the text says
    google/web/news...); "what is this project about" -> knowledge only."""
    groups = devutils_refine(text, groups)
    if "web" in groups and len(groups) > 1 and _LOCAL_GROUPS.intersection(groups) \
            and not _EXPLICIT_WEB.search(text):
        groups = [g for g in groups if g != "web"]
    if "knowledge" in groups and len(groups) > 1 and _PROJECT_Q.search(text):
        groups = ["knowledge"]
    if "codequality" in groups and len(groups) > 1:  # "review my code / last commit", "pre-commit" (P8a)
        groups = [g for g in groups if g not in ("knowledge", "files") and (g != "git" or _GIT_ACTION.search(text))]
    return groups


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


_vocab: set[str] | None = None


def _known_words() -> set[str]:
    """Words of KURAMA's own areas (router examples, rules, area descriptions): the targets of typo fixes."""
    global _vocab
    if _vocab is None:
        src = [d for exs in config.ROUTER_EXAMPLES.values() for d in exs]
        src += [k for ks in config.ROUTER_RULES.values() for k in ks]
        src += list(config.TOOL_GROUP_DESCRIPTIONS.values())
        _vocab = {w for d in src for w in re.findall(r"[a-z]{3,}", d.lower())}
    return _vocab


_english: frozenset[str] | None = None


def _is_english(word: str) -> bool:
    """A real English word ('there', 'lecture') is never 'fixed' (the system dictionary, loaded on first need)."""
    global _english
    if _english is None:
        try:
            with open("/usr/share/dict/words", encoding="utf-8", errors="ignore") as fh:
                _english = frozenset(w.strip().lower() for w in fh if len(w.strip()) >= 5 and w.strip().isalpha())
        except OSError:
            _english = frozenset()
    return word in _english


def fix_typos(text: str) -> str:
    """'Set alram', 'any traning', 'open youtbe', 'my budjet', 'complete downlaod': a word that is not one of KURAMA's
    area words but is very close to one is read as it (for routing only; the AI still sees what you wrote). Names
    (Pokhara, Tara) are close to none of them and stay."""
    vocab = _known_words()

    def fix(m: re.Match) -> str:
        w = m.group(0)
        low = w.lower()
        if len(low) < 5 or low in vocab or _is_english(low):
            return w
        hit = difflib.get_close_matches(low, vocab, n=1, cutoff=0.8)
        return hit[0] if hit and abs(len(hit[0]) - len(low)) <= 1 else w
    return re.sub(r"[A-Za-z]+", fix, text or "")


def route(text: str, log_it: bool = True) -> Route:
    t0 = time.monotonic()
    text = fix_typos(text)
    available = registry.groups()
    r = Route(reasoning=needs_reasoning(text))
    if semantic.ready() and not is_small_talk(text) and (sem := [g for g in semantic.match(text) if g in available]):
        # by meaning first (model loaded: ~10 ms); word-rule areas only fill the free places as extra candidates —
        # the AI still picks the action by meaning
        extra = [g for g in refine(text, site_over_apps(text, [g for g in rule_groups(text) if g in available]))
                 if g not in sem]
        r.method, r.groups = "semantic", (sem[:2] + extra + sem[2:])[: config.ROUTER_MAX_GROUPS]
        matched = []
    else:
        matched = rule_groups(text)  # model not loaded yet / meaning unclear / Nepali-Hindi script: the word rules
        semantic.warm_soon()
    if r.groups:
        pass
    elif matched:
        r.method = "rules"
        r.groups = refine(text, site_over_apps(text, [g for g in matched if g in available]))
        if len(r.groups) < config.ROUTER_MAX_GROUPS and (more := semantic.extra(text, r.groups)) in available:
            r.groups.append(more)  # the meaning wants a group the keywords missed
        for g in list(r.groups):  # "link" -> browser: the link store (now its own area) comes too
            if (n := config.ROUTER_RULE_NEIGHBORS.get(g)) and n in available and n not in r.groups:
                r.groups.insert(r.groups.index(g) + 1, n)
    elif "web" in available and _WEB_QUESTION.search(text):
        r.method, r.groups = "rules", ["web"]
    elif available and not is_small_talk(text) and (sem := [g for g in semantic.match(text) if g in available]):
        r.method, r.groups = "semantic", sem  # by meaning, 0 tokens (was the LLM classifier)
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
