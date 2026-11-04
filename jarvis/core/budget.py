"""Daily token budget tracker backed by the SQLite llm_calls log."""
from __future__ import annotations

from jarvis.core import config, store


def limit(model: str) -> int | None:
    """Daily budget for model, or None if unlimited."""
    return config.DAILY_TOKEN_BUDGET.get(model)


def used(model: str) -> int:
    return store.tokens_today(model)


def remaining(model: str | None = None) -> int | dict[str, int]:
    """Tokens left today for model; with no model, a dict for every budgeted model."""
    if model is None:
        return {m: _left(m) for m in config.DAILY_TOKEN_BUDGET}
    return _left(model)


def _left(model: str) -> int:
    cap = limit(model)
    if cap is None:
        return 10**12
    return max(0, cap - used(model))


def allow(model: str, needed: int = 0) -> bool:
    """True if model still has more than `needed` tokens left today."""
    if limit(model) is None:
        return True
    return _left(model) > needed


def summary() -> str:
    parts = [f"{m}: {used(m)}/{cap}" for m, cap in config.DAILY_TOKEN_BUDGET.items()]
    return " | ".join(parts)
