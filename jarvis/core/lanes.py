"""Lanes (master plan phase 1, the good idea from KURAMA Version_4, by meaning instead of an AI call): every request
is general (chat / knowledge / feelings: no tools), search (live data), create (new content) or auto (an action on
the laptop or a service). 0 tokens: the shared embedding model against config.LANE_EXAMPLES (~10 ms).

Only a CONFIDENT general changes the route (no tools, the small fast model, one call); the other lanes are recorded
for the trace and the executors. Unsure = the old routing, unchanged."""
from __future__ import annotations

import logging
import threading

from jarvis.core import config

log = logging.getLogger(__name__)
_lock = threading.Lock()
_mat: tuple[list[str], object] | None = None  # (lane per example row, example embeddings)


def scores(text: str) -> dict[str, float]:
    """Best similarity per lane ({} when the meaning model isn't loaded / failed)."""
    from jarvis.core import semantic
    t = " ".join((text or "").split())
    if not t or not semantic.ready():
        return {}
    global _mat
    try:
        with _lock:
            if _mat is None:
                rows = [(lane, ex) for lane, exs in config.LANE_EXAMPLES.items() for ex in exs]
                _mat = ([lane for lane, _ in rows], semantic.embedder().embed([ex for _, ex in rows], query=True))
        lanes, mat = _mat
        sims = (mat @ semantic.embedder().embed([t], query=True)[0]).tolist()
    except Exception as e:  # noqa: BLE001 - no lane: the old routing decides
        log.debug("lane scores failed: %s", e)
        return {}
    best: dict[str, float] = {}
    for lane, s in zip(lanes, sims):
        best[lane] = max(best.get(lane, -1.0), s)
    return best


def lane(text: str) -> tuple[str, float]:
    """(lane, how sure): the best lane and its margin over the runner-up; ('', 0) without the model."""
    s = scores(text)
    if not s:
        return "", 0.0
    ranked = sorted(s.items(), key=lambda kv: -kv[1])
    top, val = ranked[0]
    margin = val - (ranked[1][1] if len(ranked) > 1 else 0.0)
    if val < config.LANE_MIN:
        return "unclear", margin
    return top, margin


def is_general(text: str) -> bool:
    """A confident general request: chat, knowledge, opinion, feelings. Answered by ONE small-model call."""
    name, margin = lane(text)
    return name == "general" and margin >= config.LANE_GENERAL_MARGIN
