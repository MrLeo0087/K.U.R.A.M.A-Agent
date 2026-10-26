"""Semantic router: picks tool groups by MEANING, not keywords (0 LLM tokens).

Every group gets a few short "documents": its description, each tool's description, its example requests
(config.ROUTER_EXAMPLES) and its multi-word keyword phrases. They are embedded once with the same small ONNX
model as the knowledge index (fastembed bge-small, in a child process that unloads when idle) and cached in
data/semantic_router.npz (rebuilt when any document changes). A request is embedded (~10 ms warm) and scored
against every document; a group's score is its best document. Non-English text (Nepali/Hindi script) is left to
the keyword rules and the LLM classifier, because the model is English-only.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
from typing import Any

from jarvis.core import config

log = logging.getLogger("jarvis.semantic")

_lock = threading.Lock()
_index: tuple[str, list[str], Any] | None = None  # (docs hash, group per row, matrix)
_embedder: Any = None
CHAT = "_chat"  # pseudo-group: plain conversation, no tools


def _docs() -> list[tuple[str, str]]:
    from jarvis.core import registry

    docs: list[tuple[str, str]] = []
    groups = set(registry.groups())
    for g in sorted(groups):
        if d := config.TOOL_GROUP_DESCRIPTIONS.get(g):
            docs.append((g, d))
        docs += [(g, ex) for ex in config.ROUTER_EXAMPLES.get(g, ())]
        docs += [(g, k.strip()) for k in config.ROUTER_RULES.get(g, ()) if " " in k.strip() and k.isascii()]
    for t in registry.REGISTRY.tools.values():
        g = registry.group_of(t)
        if g in groups and t.description:
            docs.append((g, t.description.split(". ")[0][:200]))
        if g in groups:  # many ways people ask for this tool, so free phrasing finds it (0 tokens)
            docs += [(g, ex) for ex in config.TOOL_EXAMPLES.get(t.name, ())]
    docs += [(CHAT, ex) for ex in config.ROUTER_CHAT_EXAMPLES]
    seen: set[tuple[str, str]] = set()
    return [d for d in docs if not (d in seen or seen.add(d))]


def embedder() -> Any:
    global _embedder
    if _embedder is None:
        from jarvis.core.memory import Embedder
        # kept loaded much longer than the knowledge index's: reloading the model took 3-18 s and made every
        # free-phrased request after a 2-minute pause feel stuck (~120 MB while loaded, in a child process)
        _embedder = Embedder(idle_s=_idle_for(mode()))
    return _embedder


def _load() -> tuple[list[str], Any]:
    """(group per row, L2-normalized matrix), from the cache file when the documents haven't changed."""
    global _index
    import numpy as np

    docs = _docs()
    key = hashlib.sha1("\n".join(f"{g}\t{t}" for g, t in docs).encode()).hexdigest()[:16]
    if _index and _index[0] == key:
        return _index[1], _index[2]
    path = config.DATA_DIR / "semantic_router.npz"
    mat = None
    try:
        z = np.load(path, allow_pickle=False)
        if str(z["key"]) == key:
            mat = z["mat"].astype(np.float32)
    except (OSError, KeyError, ValueError):
        pass
    if mat is None:
        mat = embedder().embed([t for _, t in docs]).astype(np.float16)
        try:
            np.savez(path, key=np.array(key), mat=mat)
        except OSError as e:
            log.warning("could not cache the semantic router: %s", e)
        mat = mat.astype(np.float32)
        log.info("semantic router: embedded %d documents", len(docs))
    _index = (key, [g for g, _ in docs], mat)
    return _index[1], _index[2]


# The user's choice in the dashboard (Settings -> Memory): "always" (stay loaded = fastest), "auto" (load when a
# request needs it, free after SEMANTIC_AUTO_IDLE_S), "off" (never load it: keyword rules + the AI pick tools).
MODES = ("always", "auto", "off")
_mode_cache: tuple[float, str] = (0.0, "")


def mode() -> str:
    global _mode_cache
    import time as _t
    if _t.monotonic() - _mode_cache[0] < 5:
        return _mode_cache[1]
    try:
        from jarvis.core import store
        m = store.kv_get("semantic_mode") or config.SEMANTIC_MODE
    except Exception:  # noqa: BLE001
        m = config.SEMANTIC_MODE
    m = m if m in MODES else "auto"
    _mode_cache = (_t.monotonic(), m)
    return m


def set_mode(m: str) -> str:
    global _mode_cache
    from jarvis.core import store
    if m not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    store.kv_set("semantic_mode", m)
    _mode_cache = (0.0, "")
    if _embedder is not None:
        _embedder.idle_s = _idle_for(m)
        if m == "off":
            _embedder.unload()
        elif _embedder.loaded:
            _embedder._arm()  # the new idle time counts from now
    return m


def _idle_for(m: str) -> float:
    return 0.0 if m == "always" else config.SEMANTIC_AUTO_IDLE_S  # 0 = never unload


def status() -> dict:
    e = _embedder
    loaded = bool(e is not None and e.loaded)
    mb = 0
    if loaded:
        try:
            import psutil
            proc = getattr(e._model, "proc", None)
            mb = round(psutil.Process(proc.pid).memory_info().rss / 1048576) if proc else 0
        except Exception:  # noqa: BLE001
            mb = 0
    return {"mode": mode(), "loaded": loaded, "mb": mb}


def free_now() -> None:
    if _embedder is not None:
        _embedder.unload()


def warm() -> None:
    """Load the model + index now (server start / wake-up), so the first real request is fast."""
    if config.SEMANTIC_ROUTER and mode() == "always":
        try:
            scores("open youtube")
        except Exception as e:  # noqa: BLE001
            log.warning("semantic warm-up failed: %s", e)


def scores(text: str) -> list[tuple[str, float]]:
    """Every group with its best similarity to the request, best first ([] when unavailable)."""
    if not config.SEMANTIC_ROUTER or not text.strip() or not re.search(r"[A-Za-z]{3}", text) or mode() == "off":
        return []
    if re.search(r"[ऀ-ॿ]", text):  # Devanagari: the English model would guess
        return []
    try:
        with _lock:
            groups, mat = _load()
            q = embedder().embed([text], query=True)[0]
    except Exception as e:  # model missing/offline: the keyword rules and the classifier still work
        log.warning("semantic router unavailable: %s", e)
        return []
    best: dict[str, float] = {}
    for g, s in zip(groups, (mat @ q).tolist()):
        if s > best.get(g, -1.0):
            best[g] = s
    return sorted(best.items(), key=lambda kv: kv[1], reverse=True)


def match(text: str, k: int | None = None) -> list[str]:
    """Confident groups for the request: the best one when it clears SEMANTIC_MIN, plus runners-up within
    SEMANTIC_MARGIN of it (at most k)."""
    ranked = scores(text)
    chat = next((s for g, s in ranked if g == CHAT), 0.0)
    ranked = [(g, s) for g, s in ranked if g != CHAT]
    if not ranked or ranked[0][1] < config.SEMANTIC_MIN or ranked[0][1] < chat + config.SEMANTIC_OVER_CHAT:
        return []
    top = ranked[0][1]
    return [g for g, s in ranked if s >= top - config.SEMANTIC_MARGIN][: k or config.ROUTER_MAX_GROUPS]


def extra(text: str, have: list[str]) -> str | None:
    """A group the keyword rules missed but the meaning clearly wants (sure enough to add), or None.
    Only while the model is already loaded: a keyword hit never waits for the model to start."""
    if not config.SEMANTIC_ROUTER or _embedder is None or not _embedder.loaded:
        return None
    ranked = scores(text)
    chat = next((s for g, s in ranked if g == CHAT), 0.0)
    ranked = [(g, s) for g, s in ranked if g != CHAT]
    if ranked and ranked[0][0] not in have and ranked[0][1] >= config.SEMANTIC_ADD_MIN \
            and ranked[0][1] >= chat + config.SEMANTIC_OVER_CHAT:
        return ranked[0][0]
    return None
