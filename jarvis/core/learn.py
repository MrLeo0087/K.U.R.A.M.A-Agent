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
import re
import threading
import time
from typing import Any

from jarvis.core import config

log = logging.getLogger("jarvis.learn")
_lock = threading.Lock()
_rows: list[dict] | None = None
_vecs: Any = None
_prev: dict | None = None  # the last finished turn, judged when the next one ends
_corr_vecs: Any = None

CORRECTIONS = (
    "no, I meant something else", "not that", "that's wrong", "you did the wrong thing", "I said save the link",
    "no no, play it in the music player", "I mean the other one", "that's not what I asked", "wrong file",
    "stop, not this", "no I wanted the video not the audio", "you misunderstood me", "it didn't work, do it again",
    "hoina, maile arkai bhaneko", "galat", "nahi, maine kuch aur kaha tha", "yo hoina",
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


def add(text: str, group: str = "", neg_intent: str = "", source: str = "") -> None:
    """Learn one wording: it belongs to `group` (may be empty) and/or is NOT `neg_intent`."""
    import numpy as np
    text = " ".join((text or "").split())[:300]
    if not text or not (group or neg_intent):
        return
    v = _embed(text).astype(np.float32)
    with _lock:
        rows, vecs = _load()
        keep = [i for i, r in enumerate(rows) if r["text"].lower() != text.lower()]  # a newer verdict replaces
        rows = [rows[i] for i in keep] + [{"text": text, "group": group, "neg": neg_intent, "src": source,
                                           "ts": time.time()}]
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


def group_scores(q: Any) -> dict[str, float]:
    """Best similarity of a request vector to the learned wordings of each area."""
    with _lock:
        rows, vecs = _load()
        if not rows:
            return {}
        sims = (vecs @ q).tolist()
    best: dict[str, float] = {}
    for r, s in zip(rows, sims):
        if r["group"] and s > best.get(r["group"], -1.0):
            best[r["group"]] = s
    return best


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


def correction_score(text: str) -> float:
    global _corr_vecs
    from jarvis.core import semantic
    if not text.strip():
        return 0.0
    if _corr_vecs is None:
        _corr_vecs = semantic.embedder().embed(list(CORRECTIONS), query=True)
    return float((_corr_vecs @ _embed(text)).max())


def _area(tools: list[dict], done: bool = False) -> str:
    """The area (tool group) of the first specialised tool that ran fine (done: and really did the thing)."""
    from jarvis.core import registry
    for t in tools:
        ok = t.get("ok") and (not done or _really_did(t.get("result")))
        tool = registry.REGISTRY.get(t.get("name") or "") if ok else None
        if tool is not None and (g := registry.group_of(tool)) not in ("core", "self", ""):
            return g
    return ""


def on_turn(turn: dict) -> None:
    """A turn finished (text, ts, path, intent, tools): judge the previous one now that this one shows how it went."""
    if not config.LEARN or not config.SEMANTIC_ROUTER:
        return
    threading.Thread(target=_judge, args=(turn,), daemon=True, name="learn").start()


def _judge(turn: dict) -> None:
    global _prev
    prev, _prev = _prev, turn
    if not prev or not prev.get("text"):
        return
    try:
        recent = turn["ts"] - prev["ts"] < config.LEARN_WINDOW_S
        corr = correction_score(turn["text"]) if recent else 0.0
        if corr >= config.LEARN_CORRECTION_SIM:
            # the right action that FAILED ("I couldn't find...") is a bug to fix, not a wrong choice to unlearn
            failed = any(re.match(r"\W*(?:error|i couldn'?t|i can'?t|sorry|i'm sorry)", str(t.get("result") or ""), re.I)
                         for t in prev["tools"])
            neg = "" if failed else prev.get("intent") or ""
            if area := _area(turn["tools"]):
                add(prev["text"], area, neg, "correction")
            elif prev.get("path") == "fastpath" and neg:
                add(prev["text"], "", prev["intent"], "correction")
        elif prev.get("path") == "ai" and corr < config.LEARN_WORKED_MAX_CORR and standalone(prev["text"]) \
                and (area := _area(prev["tools"], done=True)):
            add(prev["text"], area, "", "worked")
    except Exception as e:  # noqa: BLE001 - learning must never break KURAMA
        log.warning("learning failed: %s", e)
