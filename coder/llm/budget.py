"""What a run will cost, before it is spent: each file's output by its difficulty, plus what it is shown (the plan,
the files it uses), plus a reserve for fixes. Over settings.ASK_TOKENS (20k, owner) the agent asks first."""
from __future__ import annotations

from coder.core import settings
from coder.core.run import Run


def estimate(run: Run) -> int:
    out = sum(settings.TOKENS[f.level] for f in run.files)
    plan_size = 150 + 40 * len(run.files) + len(run.notes) // 4
    shown = sum(plan_size + min(len(f.uses), 3) * settings.FILE_CONTEXT_CHARS // 4 for f in run.files)
    reserve = 2500  # one or two small fixes
    return int(out + shown + reserve + run.tokens)  # (+ what the plan already cost)


def too_big(run: Run) -> bool:
    return estimate(run) > settings.ASK_TOKENS
