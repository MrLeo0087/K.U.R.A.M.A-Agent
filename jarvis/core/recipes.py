"""Learned shortcuts and kept answers: KURAMA gets cheaper and more right every day from how its replies went.

Two kinds of rows in data/recipes.json (vectors from the semantic router's model, 0 tokens to use):
- tool: a request the AI solved with ONE safe tool (an area in config.RECIPE_GROUPS) that really did it. Words of
  the request that are also in an argument become a slot ('play song X' -> music(play, query='X hindi song')), so
  'play song kesariya' is the same shortcut with another song; with no slot, only a request with the same meaning
  and no new content words matches. It is a silent candidate until the OWNER approves it: 👍, or praise in the
  next message ("perfect, that's right"). Nothing is ever switched on by silence (owner 11-03: "if I do nothing,
  do nothing"). Only the decision is kept: the tool runs every time.
- taught: the owner's correction said what to do ("no, play it in the music player") and that worked: the FIRST
  wording -> the tool the correction used, on at once (the owner said so).
- answer: a plain AI answer (no tool, nothing about today / now / news) the owner approved, reused for a nearly
  identical question within ANSWER_CACHE_DAYS.
👎, or a complaint in the next message, deletes what served the reply, vetoes the shortcut that answered it (learn:
the router won't pick it for that meaning again) and goes to the top of the trace report. Each use adds the tokens
the AI path had cost to the day's saving (stats()).
Safety: never for a request that points at something on screen ('this', 'that file'), a path-like argument from
the context, a tool that asks yes/no, or an area outside RECIPE_GROUPS (no reminders, money, messages, files,
jobs). fastpath.match tries this after every pattern and meaning shortcut.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from typing import Any

from jarvis.core import config

log = logging.getLogger("jarvis.recipes")
_lock = threading.RLock()
_rows: list[dict] | None = None
_mat: Any = None

_POINTS = re.compile(r"\b(?:this|that|these|those|it|its|here|there|selected|highlighted|current|same|above|"
                     r"previous|last|again|yo|tyo|yaha|yeh|woh|isko|usko)\b", re.I)
_LIVE = re.compile(r"\b(?:today|tonight|now|right\s+now|currently|latest|recent|news|score|scores|price|prices|"
                   r"weather|tomorrow|yesterday|this\s+(?:week|month|year)|aaja|aaj|abhi|ahile|kal|bholi)\b", re.I)
_PERSONAL = re.compile(r"\b(?:my|mine|me|i|i'm|i've|our|us|you\s+know|your\s+memory|remainder|reminders?|list|"
                       r"todo|to-do|spend|spent|budget|contacts?|schedule|files?|folders?)\b", re.I)
_PATHISH = re.compile(r"[/\\]|^~|\.\w{1,5}$")
_BG = "Still working after"


# ------------------------------------------------------------------ storage
def _path():
    return config.DATA_DIR / "recipes.json"


def _load() -> list[dict]:
    global _rows, _mat
    if _rows is None:
        try:
            data = json.loads(_path().read_text(encoding="utf-8"))
            _rows = [r for r in data if isinstance(r, dict) and r.get("vec")] if isinstance(data, list) else []
        except (OSError, ValueError):
            _rows = []
        _mat = None
    return _rows


def _matrix():
    global _mat
    import numpy as np
    rows = _load()
    if _mat is None or len(_mat) != len(rows):
        _mat = np.array([r["vec"] for r in rows], dtype=np.float32) if rows else np.zeros((0, 1), np.float32)
    return _mat


def _save() -> None:
    global _mat
    rows = _load()
    if len(rows) > config.RECIPE_MAX:  # the least useful go first: off before on, then the least used / oldest
        rows.sort(key=lambda r: (bool(r.get("on")), r.get("used", 0), r.get("ts", 0)))
        del rows[:len(rows) - config.RECIPE_MAX]
    _mat = None
    try:
        tmp = _path().with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_path())
    except OSError as e:
        log.warning("could not save learned shortcuts: %s", e)


def reset_cache() -> None:
    """Tests / another data folder: read the file again."""
    global _rows, _mat
    with _lock:
        _rows, _mat = None, None


def _embed(text: str):
    from jarvis.core import semantic
    return semantic.embedder().embed([text], query=True)[0]


# ------------------------------------------------------------------ words and slots
def _tokens(text: str) -> tuple[list[str], list[str]]:
    """The request's words (raw, lower), the assistant's name in front left out."""
    raw = re.findall(r"[\w']+", text or "")
    names = {n.lower() for n in config.ASSISTANT_NAMES} | {"hey", "hi", "ok", "okay"}
    while raw and raw[0].lower() in names:
        raw = raw[1:]
    return raw, [w.lower() for w in raw]


def _content(low: list[str]) -> set[str]:
    from jarvis.core.learn import _REF
    return {w for w in low if w not in _REF and len(w) > 1}


def _same_words(a: str, b: str) -> bool:
    """b says nothing a doesn't (no new content word) and misses at most one of a's."""
    ca, cb = _content(_tokens(a)[1]), _content(_tokens(b)[1])
    return not (cb - ca) and len(ca - cb) <= 1


def _fixed_keys(tool: str) -> set[str]:
    """Arguments with a fixed set of values (action='play'): never a slot, even when the word is in the request."""
    from jarvis.core import registry
    t = registry.REGISTRY.get(tool)
    props = (registry.parameters_of(t).get("properties") or {}) if t is not None else {}
    return {k for k, p in props.items() if isinstance(p, dict) and ("enum" in p or p.get("type") == "boolean")}


def _slots(low: list[str], args: dict, fixed: set[str] = frozenset()) -> tuple[list[str], dict]:
    """Template words (a slot is '\\x00key') and the slots: key -> {pre, post} (the argument = pre + words + post)
    or {num: True}. An argument is a slot when its words (all, or a run of 2+) are words of the request."""
    tmpl: list[str | None] = list(low)
    slots: dict[str, dict] = {}
    for k, v in args.items():
        if isinstance(v, bool) or v is None or k in fixed:
            continue
        if isinstance(v, (int, float)):
            sv = str(int(v)) if float(v).is_integer() else str(v)
            if sv in tmpl:
                tmpl[tmpl.index(sv)] = "\x00" + k
                slots[k] = {"num": True}
            continue
        if not isinstance(v, str) or _PATHISH.search(v.strip()):
            continue  # a path / file name stays as it was (it may come from the screen, not the words)
        vraw = re.findall(r"[\w']+", v)
        vw = [w.lower() for w in vraw]
        best = (0, 0, 0)
        for i in range(len(tmpl)):
            for j in range(len(vw)):
                n = 0
                while i + n < len(tmpl) and j + n < len(vw) and tmpl[i + n] == vw[j + n]:
                    n += 1
                if n > best[0]:
                    best = (n, i, j)
        n, i, j = best
        if n == 0 or (n < len(vw) and n < 2):
            continue
        tmpl[i:i + n] = ["\x00" + k] + [None] * (n - 1)
        slots[k] = {"pre": " ".join(vraw[:j]), "post": " ".join(vraw[j + n:])}
    return [w for w in tmpl if w is not None], slots


def _template_ok(tmpl: list[str]) -> bool:
    """At least one fixed content word ('play X'), never a bare slot that would swallow anything."""
    fixed = [w for w in tmpl if not w.startswith("\x00")]
    return bool(_content(fixed)) and any(w.startswith("\x00") for w in tmpl)


def _fill(r: dict, raw: list[str], low: list[str]) -> dict | None:
    """The row's arguments for this request, or None when its words don't fit the template."""
    parts = []
    for w in r["template"]:
        if w.startswith("\x00"):
            k = w[1:]
            parts.append(rf"(?P<s_{k}>\d+)" if r["slots"][k].get("num") else rf"(?P<s_{k}>[\w' ]{{1,80}}?)")
        else:
            parts.append(re.escape(w))
    m = re.fullmatch(r"\s+".join(parts), " ".join(low))
    if not m:
        return None
    joined_raw = " ".join(raw)
    use_raw = len(joined_raw) == len(" ".join(low))  # same positions: keep the user's capital letters
    args = dict(r["args"])
    for k, s in r["slots"].items():
        a, b = m.span("s_" + k)
        got = (joined_raw[a:b] if use_raw else m.group("s_" + k)).strip()
        if not got:
            return None
        args[k] = int(got) if s.get("num") else " ".join(x for x in (s.get("pre"), got, s.get("post")) if x)
    return args


# ------------------------------------------------------------------ learning from turns
def _candidate(turn: dict, text: str | None = None) -> tuple[str, dict, str] | None:
    """(tool, args, result) when the turn did the request with exactly one allowed, safe tool that really did it.
    text: the wording to check (a correction's tools, learned for the request it corrected)."""
    from jarvis.core import registry
    from jarvis.core.learn import _really_did, standalone
    text = turn.get("text") or "" if text is None else text
    if not standalone(text) or _POINTS.search(text) or len(text) > 160:
        return None
    special, general = [], []
    for t in turn.get("tools") or []:
        name = t.get("name") or ""
        if name == "request_tools":
            continue
        tool = registry.REGISTRY.get(name)
        if tool is None:
            return None
        (general if registry.group_of(tool) == "core" else special).append((t, tool))
    if not special and len(general) == 1:  # only the general tool was traced (its work went to a background job):
        from jarvis.tools.core._hub import underlying  # the specialised tool it ran
        g = general[0][0]
        name, uargs = underlying(g["name"], g.get("args") or {})
        if (tool := registry.REGISTRY.get(name)) is None or registry.group_of(tool) == "core":
            return None
        special = [({**g, "name": name, "args": uargs}, tool)]
    if len(special) != 1 or len(general) > 1:
        return None
    t, tool = special[0]
    result = str(t.get("result") or "")
    if (not t.get("ok") or t.get("outcome") not in (None, "", "allowed") or t.get("safety") == "confirm"
            or registry.safety_of(tool) != "safe" or registry.group_of(tool) not in config.RECIPE_GROUPS
            or not _really_did(result) or (result.startswith(_BG) and not _job_done(result))):
        return None
    args = t.get("args") if isinstance(t.get("args"), dict) else {}
    args = {k: v for k, v in args.items() if not str(k).startswith("_")}
    try:
        json.dumps(args)
    except (TypeError, ValueError):
        return None
    return t["name"], args, result


def _job_done(note: str) -> bool:
    """'Still working after 3 s ... job #67': the tool finished in the background, and well (the owner then judged
    the answer that job announced)."""
    m = re.search(r"job #(\d+)", note)
    if not m:
        return False
    from jarvis.core import store
    rows = store._exec("SELECT status FROM jobs WHERE id = ?", (int(m.group(1)),))
    return bool(rows) and rows[0]["status"] == "done"


def observe(turn: dict) -> None:
    """A finished AI turn: keep its decision as a candidate (or count it again for the same one)."""
    if not config.RECIPES or turn.get("path") != "ai":
        return
    cand = _candidate(turn)
    if cand is None:
        return
    tool, args, _ = cand
    raw, low = _tokens(turn["text"])
    tmpl, slots = _slots(low, args, _fixed_keys(tool))
    if slots and not _template_ok(tmpl):
        tmpl, slots = [], {}
    v = _embed(turn["text"])
    tid = turn.get("id") or ""
    with _lock:
        rows = _load()
        mat = _matrix()
        sims = (mat @ v).tolist() if len(rows) else []
        for r, s in zip(rows, sims):
            if r.get("kind") != "tool" or r.get("tool") != tool:
                continue
            same = (slots and r.get("slots") and r.get("template") == tmpl and r["slots"] == slots
                    and {k: x for k, x in r["args"].items() if k not in slots} ==
                    {k: x for k, x in args.items() if k not in slots}) \
                or (not slots and not r.get("slots") and r["args"] == args and s >= config.RECIPE_SIM)
            if same:
                if tid and tid not in r["traces"]:
                    r["traces"] = (r["traces"] + [tid])[-10:]
                    _save()
                return
        rows.append({"id": uuid.uuid4().hex[:8], "kind": "tool", "text": " ".join(turn["text"].split())[:200],
                     "vec": [round(float(x), 5) for x in v], "tool": tool, "args": args, "template": tmpl,
                     "slots": slots, "on": False, "ok": [], "traces": [tid] if tid else [], "ts": time.time(),
                     "used": 0, "tokens": int(turn.get("tokens") or 0)})
        _save()
    log.info("learned shortcut candidate %r -> %s %s", turn["text"][:60], tool, args)


def _related(text: str, tool: str, args: dict) -> bool:
    """The fix is about the request it corrects: its arguments share a content word with it (the song, the city),
    or its tool's area is one of the request's two closest areas by meaning."""
    from jarvis.core import registry, semantic
    vals = " ".join(str(v) for v in args.values() if isinstance(v, (str, int, float)) and not isinstance(v, bool))
    if _content(_tokens(text)[1]) & _content(_tokens(vals)[1]):
        return True
    t = registry.REGISTRY.get(tool)
    top = [g for g, _ in semantic.scores(text) if g != semantic.CHAT][:2] if semantic.ready() else []
    return t is not None and registry.group_of(t) in top


def is_fix(prev_text: str, fix: dict) -> bool:
    """The correction's own tool call is about the request it corrects (not a new task said after the complaint)."""
    from jarvis.core import registry
    from jarvis.tools.core._hub import underlying
    for t in fix.get("tools") or []:
        x = registry.REGISTRY.get(t.get("name") or "")
        if x is None or t.get("name") == "request_tools":
            continue
        name, args = (t["name"], t.get("args") or {}) if registry.group_of(x) != "core" else \
            underlying(t["name"], t.get("args") or {})
        return _related(prev_text, name, args if isinstance(args, dict) else {})
    return False


def taught(prev: dict, fix: dict) -> bool:
    """The owner corrected `prev` and the correction `fix` did it with one safe tool: prev's wording now means that
    tool (with prev's words as slots), on at once: the owner told KURAMA what to do."""
    if not config.RECIPES or not prev.get("text"):
        return False
    cand = _candidate(fix, text=prev["text"])
    if cand is None or not _related(prev["text"], cand[0], cand[1]):
        return False  # 'that's wrong, anyway open youtube': a new task after the complaint, not the fix of it
    tool, args, _ = cand
    raw, low = _tokens(prev["text"])
    tmpl, slots = _slots(low, args, _fixed_keys(tool))
    if slots and not _template_ok(tmpl):
        tmpl, slots = [], {}
    v = _embed(prev["text"])
    with _lock:
        rows = _load()
        rows[:] = [r for r in rows if r.get("text", "").lower() != " ".join(prev["text"].split())[:200].lower()]
        rows.append({"id": uuid.uuid4().hex[:8], "kind": "tool", "src": "taught",
                     "text": " ".join(prev["text"].split())[:200], "vec": [round(float(x), 5) for x in v],
                     "tool": tool, "args": args, "template": tmpl, "slots": slots, "on": True, "ok": [],
                     "traces": [t for t in (prev.get("id"), fix.get("id")) if t], "ts": time.time(), "used": 0,
                     "tokens": int(prev.get("tokens") or 0) + int(fix.get("tokens") or 0)})
        _save()
    log.info("taught by a correction: %r -> %s %s", prev["text"][:60], tool, args)
    return True


def dropped(trace_id: str) -> int:
    """That request was corrected (or got 👎): forget whatever was learned from it."""
    if not trace_id:
        return 0
    with _lock:
        rows = _load()
        keep = [r for r in rows if trace_id not in r.get("traces", [])]
        n = len(rows) - len(keep)
        if n:
            rows[:] = keep
            _save()
        return n


# ------------------------------------------------------------------ using what was learned
def find(text: str) -> tuple[dict, dict, float] | None:
    """(row, args, similarity) of the best active row for this request, or None."""
    if not config.RECIPES:
        return None
    from jarvis.core import registry, semantic
    with _lock:
        rows = [r for r in _load() if r.get("on")]
    if not rows or not semantic.ready():
        return None
    raw, low = _tokens(text)
    if not low or len(low) > 25:
        return None
    v = _embed(text)
    with _lock:
        all_rows = _load()
        sims = (_matrix() @ v).tolist() if all_rows else []
        pairs = [(r, s) for r, s in zip(all_rows, sims) if r.get("on")]
    best = None
    now = time.time()
    for r, s in pairs:
        if r["kind"] == "tool":
            tool = registry.REGISTRY.get(r["tool"])
            if tool is None or registry.safety_of(tool) != "safe" or registry.group_of(tool) not in config.RECIPE_GROUPS:
                continue
            if r.get("slots"):
                if s < config.RECIPE_SLOT_SIM or (args := _fill(r, raw, low)) is None:
                    continue
            elif s >= config.RECIPE_SIM and _same_words(r["text"], text):
                args = dict(r["args"])
            else:
                continue
        else:
            if s < config.ANSWER_CACHE_SIM or not _same_words(r["text"], text) or _LIVE.search(text) or _PERSONAL.search(text) \
                    or now - r.get("ts", 0) > config.ANSWER_CACHE_DAYS * 86400:
                continue
            args = {}
        if best is None or s > best[2]:
            best = (r, args, s)
    return best


def match(text: str):
    """A fastpath Intent for a learned shortcut / kept answer, or None."""
    from jarvis.core import fastpath, registry
    got = find(text)
    if got is None:
        return None
    r, args, _ = got
    if r["kind"] == "answer":
        ran(r["id"], True)
        a = r["answer"]
        return fastpath.Intent("cached", "_say", "self", {"en": a, "hi": a, "ne": a})
    kind = config.DIRECT_REPLY_TOOLS.get(r["tool"])
    name = kind if isinstance(kind, str) and kind not in ("said", "audio") else "learned"
    label = str(args.get("target") or args.get("name") or "")
    return fastpath.Intent(name, r["tool"], registry.group_of(registry.REGISTRY.get(r["tool"])),
                           {**args, "_recipe": r["id"]}, label)  # fastpath.try_answer reports back through ran()


def ran(rid: str, good: bool) -> bool:
    """A learned row just answered: count it (uses, tokens saved today) or, when its tool failed, count the failure;
    RECIPE_MAX_FAILS in a row switches it off (a tool changed or broke: the AI does it again). Returns good."""
    with _lock:
        r = next((x for x in _load() if x["id"] == rid), None)
        if r is None:
            return good
        if good:
            r["used"], r["last"], r["fails"] = r.get("used", 0) + 1, time.time(), 0
            day = time.strftime("%Y-%m-%d")
            saved = r.setdefault("saved", {})
            saved[day] = saved.get(day, 0) + int(r.get("tokens") or 0)
            for old in sorted(saved)[:-14]:  # two weeks of daily numbers
                saved.pop(old)
        else:
            r["fails"] = r.get("fails", 0) + 1
            if r["fails"] >= config.RECIPE_MAX_FAILS:
                r["on"], r["off"] = False, f"its tool failed {r['fails']} times in a row"
                log.warning("learned shortcut off (failed %d times): %r", r["fails"], r["text"][:60])
        _save()
    return good


def forget_matching(text: str) -> int:
    """The learned row that would answer this request (it answered it wrongly): gone. 0 when none fits."""
    if (hit := find(text)) is None:
        return 0
    with _lock:
        rows = _load()
        rows[:] = [r for r in rows if r["id"] != hit[0]["id"]]
        _save()
    log.info("learned shortcut removed after a bad answer: %r", hit[0]["text"][:60])
    return 1


# ------------------------------------------------------------------ 👍 / 👎
def _cacheable(row: dict) -> bool:
    tools = [t for t in json.loads(row.get("tools") or "[]") if t.get("name") not in ("request_tools", "_say")]
    ans = row.get("answer") or ""
    if _PERSONAL.search(row.get("text") or ""):
        return False  # 'what is in my reminder', 'do you know my name': the answer changes (stale kept answers, 11-04)
    return (row.get("path") == "ai" and not tools and 2 <= len(ans) <= 1500 and not row.get("error")
            and not row.get("asked") and not _LIVE.search(row.get("text") or "") and not _POINTS.search(row.get("text") or "")
            and len(_tokens(row.get("text") or "")[1]) >= 3)


def feedback(trace_id: str, vote: int, note: str = "", veto: bool = True) -> dict:
    """👍 (vote 1) or 👎 (vote -1) on one reply, by button or said in the next message (note = those words).
    veto=False: the reply's tool was the right choice but failed (a bug, not a wrong shortcut). Returns {ok, said}."""
    from jarvis.core import learn, trace
    row = trace.get(trace_id)
    if row is None:
        return {"ok": False, "said": "I can't find that reply any more."}
    trace.set_feedback(trace_id, 1 if vote > 0 else -1, note)
    text = row.get("text") or ""
    tools = json.loads(row.get("tools") or "[]")
    if vote > 0:
        turned_on = 0
        with _lock:
            for r in _load():
                if trace_id in r.get("traces", []):
                    r["on"], turned_on = True, turned_on + 1
            if row.get("path") == "multi":  # the split of the request is kept (0-token plan next time)...
                try:
                    from jarvis.core import planner, taskgraph
                    plan = json.loads(row.get("plan") or "{}")
                    if plan.get("method") == "llm":
                        taskgraph.learn_plan(text, planner.parts(text), plan.get("tasks") or [])
                        turned_on += 1
                except Exception as e:  # noqa: BLE001
                    log.debug("plan not kept: %s", e)
            if row.get("path") == "multi":  # ...and each step that clearly did its task
                for step in _multi_steps(row):
                    if _candidate(step) is not None:
                        observe(step)
                for r in _load():
                    if trace_id in r.get("traces", []):
                        r["on"], turned_on = True, turned_on + 1
            if not turned_on and row.get("path") == "ai":
                cand = _candidate({"text": text, "tools": tools})
                if cand is not None:  # not seen as a candidate yet (learning was off, a restart): learn it now
                    observe({"text": text, "tools": tools, "path": "ai", "id": trace_id, "tokens": row.get("tokens")})
                    for r in _load():
                        if trace_id in r.get("traces", []):
                            r["on"], turned_on = True, turned_on + 1
                elif _cacheable(row) and config.ANSWER_CACHE:
                    v = _embed(text)
                    key = " ".join(text.split())[:200].lower()  # approved twice (button + praise): kept once
                    _load()[:] = [r for r in _load() if not (r["kind"] == "answer" and r["text"].lower() == key)]
                    _load().append({"id": uuid.uuid4().hex[:8], "kind": "answer", "text": " ".join(text.split())[:200],
                                    "vec": [round(float(x), 5) for x in v], "answer": row["answer"], "on": True,
                                    "traces": [trace_id], "ts": time.time(), "used": 0,
                                    "tokens": int(row.get("tokens") or 0)})
                    turned_on = 1
            _save()
        area, tool = learn._area(tools, done=True)
        if area and learn.standalone(text):
            learn.add(text, area, "", "thumbs_up", tool)
        return {"ok": True, "said": "Thanks! I'll answer that the same way, without the AI next time." if turned_on
                else "Thanks, noted."}
    gone = dropped(trace_id) + forget_matching(text)
    learn.unlearn(text, "thumbs_up")  # a 👍 on the same reply before (changed your mind)
    if veto and row.get("path") == "fastpath" and row.get("intent"):
        learn.add(text, "", row["intent"], "thumbs_down")  # that shortcut is wrong for this meaning (meaning_ok)
    log.info("👎 %s %r (%d learned rows removed)", trace_id, text[:60], gone)
    return {"ok": True, "said": "Noted as a bad reply.", "request": text,
            "suggest": suggestions(text, [t.get("name") or "" for t in tools])}


def suggestions(text: str, used: list[str], k: int = 3) -> list[dict]:
    """What the reply could have done instead, in plain words (never tool names): the tools closest in meaning to
    the request, minus the ones it used. The owner taps one after a 👎 (owner 11-04: "I don't know the tool names")."""
    from jarvis.core import registry, semantic
    if not semantic.ready() or not text:
        return []
    R = registry.REGISTRY
    out, seen = [], set(used)
    scored = []
    for n, t in R.tools.items():
        if n in seen or registry.group_of(t) in ("core", *config.AGENT_GROUPS) or not t.description:
            continue
        b = semantic.best_of(text, "tooldesc:" + n, {n: (t.description,)})
        if b:
            scored.append((b[1], n, t.description))
    for _, n, d in sorted(scored, reverse=True)[:k]:
        plain = re.sub(r"\s*\([^)]*\)", "", d)  # no '(+ - * / ^ %...)' bits
        label = re.split(r"[:;]|\.\s|\s+-\s+", plain, maxsplit=1)[0].strip(" ,.")
        if len(label) > 48:
            label = label[:48].rsplit(" ", 1)[0].rstrip(",") + "…"
        out.append({"label": label, "tool": n})
    return out


def late_complaint(text: str, skip: tuple[str, ...] = ()) -> str | None:
    """A complaint long after the reply ('yesterday you opened Firefox when I said open browser'): the one recent
    reply it clearly talks about (closest by meaning, by a margin) gets the 👎. None when it isn't clear."""
    from jarvis.core import semantic, trace
    rows = [r for r in trace.recent(config.LEARN_LATE_DAYS, 300) if r["id"] not in skip and r.get("text")]
    if not rows or not semantic.ready():
        return None
    import numpy as np
    mat = semantic.embedder().embed([f"{r['text']} {(r.get('answer') or '')[:120]}" for r in rows], query=True)
    sims = np.asarray(mat) @ _embed(text)
    order = np.argsort(-sims)
    best = float(sims[order[0]])
    second = float(sims[order[1]]) if len(order) > 1 else 0.0
    if best < config.LEARN_LATE_SIM or best - second < config.LEARN_LATE_MARGIN:
        return None
    tid = rows[int(order[0])]["id"]
    feedback(tid, -1, text, veto=False)  # no block on the built-in shortcut: what it did then may be fixed by now
    log.info("late complaint %r -> 👎 on %s %r", text[:60], tid, rows[int(order[0])]["text"][:60])
    return tid


def _multi_steps(row: dict) -> list[dict]:
    """A 👍 on a multi-step reply: each step (a task of the plan) with the one safe tool that clearly did it (its
    arguments share words with that task only), as turns to learn one by one."""
    from jarvis.core import registry
    try:
        tasks = [t.get("text") or "" for t in (json.loads(row.get("plan") or "{}").get("tasks") or [])]
    except ValueError:
        return []
    tools = [t for t in json.loads(row.get("tools") or "[]")
             if (x := registry.REGISTRY.get(t.get("name") or "")) is not None and registry.group_of(x) != "core"]
    out = []
    for t in tools:
        vals = _content(_tokens(" ".join(str(v) for v in (t.get("args") or {}).values()))[1])
        hits = [(len(vals & _content(_tokens(task)[1])), task) for task in tasks]
        hits.sort(reverse=True)
        if hits and hits[0][0] and (len(hits) == 1 or hits[0][0] > hits[1][0]):
            out.append({"text": hits[0][1], "tools": [t], "path": "ai", "id": row["id"], "tokens": 0})
    return out


# ------------------------------------------------------------------ for the owner
def rows(kind: str = "") -> list[dict]:
    with _lock:
        return [dict(r, vec=None) for r in _load() if not kind or r.get("kind") == kind]


def forget(rid: str = "", everything: bool = False) -> int:
    with _lock:
        rows_ = _load()
        keep = [] if everything else [r for r in rows_ if r["id"] != rid]
        n = len(rows_) - len(keep)
        rows_[:] = keep
        _save()
        return n


def stats() -> dict:
    """Counts and the tokens learned shortcuts saved: today, the last 7 days."""
    today = time.strftime("%Y-%m-%d")
    week = {time.strftime("%Y-%m-%d", time.localtime(time.time() - d * 86400)) for d in range(7)}
    with _lock:
        rs = _load()
        on = [r for r in rs if r.get("on")]
        return {"on": len(on), "waiting": len(rs) - len(on), "answers": sum(r["kind"] == "answer" for r in on),
                "used": sum(r.get("used", 0) for r in rs),
                "saved_today": sum((r.get("saved") or {}).get(today, 0) for r in rs),
                "saved_week": sum(n for r in rs for d, n in (r.get("saved") or {}).items() if d in week)}
