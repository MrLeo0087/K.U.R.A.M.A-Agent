"""KURAMA learns which area a request belongs to from how each turn went (0 tokens, all local).

After every turn the previous one is judged, once the user's next message shows how it went:
- the next message is a correction ("no, I meant save the link", "not that", "hoina") said within
  LEARN_WINDOW_S, and the corrected request ran a tool: the earlier wording is learned as belonging to THAT tool's
  area, and as NOT being the shortcut / tool that answered it;
- otherwise, an AI request whose tool ran fine is learned as belonging to that tool's area, but only when the
  wording means something by itself (no "remove it" / "yes" / "food": their meaning lives in the chat before them),
  the tool really did it (no error, no "you said no", no question back) and the next message is not even close to
  a correction. Learning the AI's own wrong picks made them stick forever.
A correction is recognised by MEANING (similarity to example corrections), not by words.

Learned wordings join the semantic router (semantic.scores) and veto a shortcut whose meaning was corrected
before (fastpath.meaning_ok). Stored in data/learned.json (+ their vectors in data/learned.npy), newest
LEARN_MAX kept. Uses the semantic router's model, in a background thread after the reply.
"""
from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
from typing import Any

from jarvis.core import config

log = logging.getLogger("jarvis.learn")
_lock = threading.Lock()
_rows: list[dict] | None = None
_vecs: Any = None
_prev: dict | None = None  # channel -> its last finished turn, judged when the next one on that channel ends
_corr_vecs: Any = None

CORRECTIONS = (
    "no, I meant something else", "not that", "that's wrong", "you did the wrong thing", "no, I said save the link",
    "no no, play it in the music player", "I mean the other one", "that's not what I asked", "wrong file",
    "stop, not this", "no I wanted the video not the audio", "you misunderstood me", "it didn't work, do it again",
    "hoina, maile arkai bhaneko", "galat", "nahi, maine kuch aur kaha tha", "yo hoina",
    "wrong, do it in the other app not this one", "not the browser, use the player", "you should have used the other tool",
    "yesterday you did the wrong thing when I asked you", "earlier you opened the wrong app, that was not right",
)


def _paths():
    return config.DATA_DIR / "learned.json", config.DATA_DIR / "learned.npy"


def _load() -> tuple[list[dict], Any]:
    global _rows, _vecs
    import numpy as np
    if _rows is None:
        jp, vp = _paths()
        try:
            _rows = json.loads(jp.read_text())
            _vecs = np.load(vp).astype(np.float32)
            if len(_vecs) != len(_rows):
                raise ValueError("vectors out of step")
        except (OSError, ValueError):
            _rows, _vecs = [], np.zeros((0, 0), dtype=np.float32)
    return _rows, _vecs


def _embed(text: str) -> Any:
    from jarvis.core import semantic
    return semantic.embedder().embed([text], query=True)[0]


def add(text: str, group: str = "", neg_intent: str = "", source: str = "", tool: str = "") -> None:
    """Learn one wording: it belongs to `group` (may be empty) and/or is NOT `neg_intent`. `tool` = the tool that
    did it: its CURRENT area is used when scoring, so moving a tool to another area moves what was learned too."""
    import numpy as np
    text = " ".join((text or "").split())[:300]
    if not text or not (group or neg_intent):
        return
    v = _embed(text).astype(np.float32)
    with _lock:
        rows, vecs = _load()
        keep = [i for i, r in enumerate(rows) if r["text"].lower() != text.lower()]  # a newer verdict replaces
        rows = [rows[i] for i in keep] + [{"text": text, "group": group, "neg": neg_intent, "src": source,
                                           "ts": time.time(), **({"tool": tool} if tool else {})}]
        vecs = np.vstack([vecs[keep] if len(vecs) and len(keep) else np.zeros((0, len(v)), np.float32), v[None]])
        rows, vecs = rows[-config.LEARN_MAX:], vecs[-config.LEARN_MAX:]
        globals().update(_rows=rows, _vecs=vecs)
        jp, vp = _paths()
        try:
            jp.write_text(json.dumps(rows, ensure_ascii=False))
            np.save(vp, vecs.astype(np.float16))
        except OSError as e:
            log.warning("could not save what was learned: %s", e)
    log.info("learned %r -> %s%s", text[:80], group or "-", f" (not {neg_intent})" if neg_intent else "")


def unlearn(text: str, source: str) -> int:
    """Drop what was learned from this exact wording by one source (a 👍 later followed by 👎 on the same reply)."""
    import numpy as np
    text = " ".join((text or "").split())[:300].lower()
    with _lock:
        rows, vecs = _load()
        keep = [i for i, r in enumerate(rows) if not (r["text"].lower() == text and r.get("src") == source)]
        if len(keep) == len(rows):
            return 0
        rows2 = [rows[i] for i in keep]
        vecs2 = vecs[keep] if len(keep) else np.zeros((0, vecs.shape[1] if vecs.ndim == 2 else 0), np.float32)
        globals().update(_rows=rows2, _vecs=vecs2)
        jp, vp = _paths()
        try:
            jp.write_text(json.dumps(rows2, ensure_ascii=False))
            np.save(vp, vecs2.astype(np.float16))
        except OSError as e:
            log.warning("could not save what was learned: %s", e)
        return len(rows) - len(keep)


def group_scores(q: Any) -> dict[str, float]:
    """Best similarity of a request vector to the learned wordings of each area."""
    with _lock:
        rows, vecs = _load()
        if not rows:
            return {}
        sims = (vecs @ q).tolist()
    best: dict[str, float] = {}
    for r, s in zip(rows, sims):
        g = _group_now(r)
        if g and s > best.get(g, -1.0):
            best[g] = s
    return best


def _group_now(row: dict) -> str:
    """The learned wording's area today: its tool's current group (areas get reorganised), else the stored one."""
    if row.get("tool") and row.get("group"):
        from jarvis.core import registry
        if (t := registry.REGISTRY.get(row["tool"])) is not None and (g := registry.group_of(t)) not in ("core", ""):
            return g
    return row.get("group", "")


def vetoed(q: Any, intent: str) -> bool:
    """A correction said this meaning is not `intent` (an almost identical wording)."""
    with _lock:
        rows, vecs = _load()
        if not rows:
            return False
        sims = (vecs @ q).tolist()
    return any(r["neg"] == intent and s >= config.LEARN_VETO_SIM for r, s in zip(rows, sims))


def is_correction(text: str) -> bool:
    return correction_score(text) >= config.LEARN_CORRECTION_SIM


_REF = frozenset("it this that these those them they me my mine you your i we us he she the a an to of in on at for "
                 "and or with please yes no ok okay now again so is are was be do does did can could will would "
                 "just one here there".split())


def standalone(text: str) -> bool:
    """The wording carries its own meaning: 3+ words, 2+ of them content words ('remove it', 'give me that',
    'food', 'yes' only mean something after the turn before them, so they are never learned)."""
    words = [w.lower() for w in re.findall(r"[^\W\d_]{2,}", text or "")]
    return len(words) >= 3 and sum(w not in _REF for w in words) >= 2


def _really_did(result: str) -> bool:
    r = str(result or "").strip()
    return not re.match(r"\W*(?:error|the user declined|the user already|i couldn'?t|i can'?t|sorry)", r, re.I) \
        and not r.rstrip().endswith("?")  # a question back ("How much should the budget be?") is not done


# Plain next requests, so a new command is never taken for a correction of the one before: "pause music" then "play
# song" scored 0.82 against "no no, play it in the music player" and taught KURAMA that "pause music" was WRONG (its
# shortcut was vetoed and every later "pause music" cost ~1,000 tokens; traces 11-01 21:05-21:14).
NOT_CORRECTIONS = (
    "play song", "play the next song", "play other song", "play some hindi song", "pause music", "continue music",
    "stop the music", "open youtube", "set volume to 100", "what time is it", "send it to telegram",
    "open it in vs code", "create a folder", "now open the folder", "next", "thank you",
    "save this link as whatsapp", "save this page as youtube", "save this link", "now save it to telegram",
)  # 11-03: 'Save this link as a WhatsApp' after 'Open web WhatsApp' matched "I said save the link" and blocked 'open' 
_not_vecs: Any = None

# The owner saying the reply was RIGHT (a spoken 👍). Plain "thanks" / "ok" are politeness, not a verdict.
PRAISES = (
    "good job", "well done", "perfect, that's exactly what I wanted", "that's right, you did it correctly",
    "yes, that is correct", "great, that was the right thing to do", "nice work kurama", "exactly, keep doing it like this",
    "you did really good", "awesome, that's the right answer", "correct, remember to do it this way",
    "ramro garyau", "ekdam thik cha", "bahut badhiya", "sahi kiya", "shabash", "perfect", "excellent", "great job",
    "that's perfect, thank you", "brilliant, exactly right",
)
NOT_PRAISES = (
    "thanks", "thank you", "ok", "okay", "next", "good morning", "good night", "how are you", "open youtube",
    "play a song", "what time is it", "good", "nice to meet you", "is that right?", "are you sure?",
    "yes", "yeah", "yes please", "sure", "yes do it", "ok go ahead", "haan", "ho",  # answers to KURAMA's question
)
_praise_vecs: Any = None
_nopraise_vecs: Any = None


def praise_score(text: str) -> float:
    """How much the message (or its first part: 'perfect, now open youtube') says the reply before was right."""
    global _praise_vecs, _nopraise_vecs
    from jarvis.core import planner, semantic
    t = " ".join((text or "").split())
    if not t or len(t.split()) > 25:
        return 0.0
    if _praise_vecs is None:
        _praise_vecs = semantic.embedder().embed(list(PRAISES), query=True)
        _nopraise_vecs = semantic.embedder().embed(list(NOT_PRAISES), query=True)
    best = 0.0
    for part in {t, (planner.split_clauses(t) or [t])[0]}:
        q = _embed(part)
        p, n = float((_praise_vecs @ q).max()), float((_nopraise_vecs @ q).max())
        if p > n + config.LEARN_CORRECTION_MARGIN:
            best = max(best, p)
    return best


def correction_score(text: str) -> float:
    """How much the message is a CORRECTION ('no, I meant...', 'wrong file'): its closeness to the example
    corrections, or 0 when it is closer to a plain next request (contrast, not a lone threshold)."""
    global _corr_vecs, _not_vecs
    from jarvis.core import semantic
    if not text.strip():
        return 0.0
    if _corr_vecs is None:
        _corr_vecs = semantic.embedder().embed(list(CORRECTIONS), query=True)
        _not_vecs = semantic.embedder().embed(list(NOT_CORRECTIONS), query=True)
    q = _embed(text)
    corr, plain = float((_corr_vecs @ q).max()), float((_not_vecs @ q).max())
    return corr if corr > plain - config.LEARN_CORRECTION_MARGIN else 0.0  # 'no I meant play the song' ties


def complaint_score(text: str) -> float:
    """correction_score of the whole message or of one of its parts ('that's wrong, anyway open youtube';
    'earlier you opened firefox when I said open browser, that was wrong'); one-word parts never count alone (a
    bare 'no' answers KURAMA's question)."""
    from jarvis.core import planner
    t = " ".join((text or "").split())
    parts = {p for p in planner.split_clauses(t) if len(p.split()) >= 2} if len(t.split()) <= 30 else set()
    return max([correction_score(t)] + [correction_score(p) for p in parts - {t}])


def _area(tools: list[dict], done: bool = False) -> tuple[str, str]:
    """(area, tool) of the first specialised tool that ran fine (done: and really did the thing)."""
    from jarvis.core import registry
    for t in tools:
        ok = t.get("ok") and (not done or _really_did(t.get("result")))
        tool = registry.REGISTRY.get(t.get("name") or "") if ok else None
        if tool is not None and (g := registry.group_of(tool)) not in ("core", "self", ""):
            return g, t["name"]
    return "", ""


_queue: "queue.Queue[dict]" = queue.Queue()
_worker: threading.Thread | None = None


def _work() -> None:
    while True:
        _judge(_queue.get())


def on_turn(turn: dict) -> None:
    """A turn finished (text, ts, path, intent, tools): judge the previous one now that this one shows how it went.
    ONE worker judges the turns in the order they ended (a thread each could judge a quick 'perfect' before the
    reply it was about, and praise the reply before that one)."""
    global _worker
    if not config.LEARN or not config.SEMANTIC_ROUTER:
        return
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, daemon=True, name="learn")
            _worker.start()
    _queue.put(turn)


def _judge(turn: dict) -> None:
    """Learn ONLY from what the owner says about the reply before (owner 11-03: "if I do nothing, do nothing"):
    a complaint = 👎 (and, when this turn did it right, its tool for that wording: taught), praise = 👍. Silence
    teaches nothing (the old "it worked" learning only with LEARN_SILENT). Each channel judges its own replies (a
    Telegram 'galat' is never about the laptop's last reply), and spoken words count only when they were heard
    clearly (stt.heard_well). A complaint after the window finds the reply it talks about (recipes.late_complaint)."""
    global _prev
    if not isinstance(_prev, dict):
        _prev = {}
    ch = turn.get("channel") or ""
    prev, _prev[ch] = _prev.get(ch), turn
    from jarvis.core import recipes, stt
    try:
        from jarvis.core import fastpath
        clear = turn.get("mode") not in ("voice", "talk") or stt.heard_well(turn["text"])
        answer = fastpath._bare_yes_no(turn["text"])  # 'no' / 'no thanks' answer KURAMA's question ('do you want
        #   more?'): a bare 'no' scored 0.84 as a complaint and would have 👎'd the question (praise stays praise)
        recent = bool(prev and prev.get("text")) and turn["ts"] - prev["ts"] < config.LEARN_WINDOW_S
        corr = complaint_score(turn["text"]) if clear and not answer else 0.0
        if corr >= config.LEARN_CORRECTION_SIM and not recent and len(turn["text"].split()) >= 4:
            recipes.late_complaint(turn["text"], skip=(turn.get("id") or "",))  # it must say WHAT was wrong
            return
        if not prev or not prev.get("text"):
            return
        if recent and corr >= config.LEARN_CORRECTION_SIM:
            # the right action that FAILED ("I couldn't find...") is a bug to fix, not a wrong choice to unlearn
            failed = any(re.match(r"\W*(?:error|i couldn'?t|i can'?t|sorry|i'm sorry)", str(t.get("result") or ""), re.I)
                         for t in prev["tools"])
            neg = "" if failed else prev.get("intent") or ""
            recipes.feedback(prev.get("id") or "", -1, turn["text"], veto=not failed)  # a spoken 👎
            area, tool = _area(turn["tools"], done=True)
            if area and recipes.is_fix(prev["text"], turn):  # checked BEFORE learning anything: 'that's wrong,
                add(prev["text"], area, neg, "correction", tool)  # anyway open youtube' is a new task, not the fix
                recipes.taught(prev, turn)  # "no, play it in the music player": that wording means that now
            elif prev.get("path") == "fastpath" and neg:
                add(prev["text"], "", prev["intent"], "correction")
        elif recent and clear and praise_score(turn["text"]) >= config.LEARN_PRAISE_SIM:
            recipes.feedback(prev.get("id") or "", 1, turn["text"])  # a spoken 👍: "perfect, that's right"
        elif config.LEARN_SILENT and prev.get("path") == "ai" and (corr if recent else 0.0) < config.LEARN_WORKED_MAX_CORR \
                and standalone(prev["text"]) and (found := _area(prev["tools"], done=True))[0]:
            add(prev["text"], found[0], "", "worked", found[1])
    except Exception as e:  # noqa: BLE001 - learning must never break KURAMA
        log.warning("learning failed: %s", e)
