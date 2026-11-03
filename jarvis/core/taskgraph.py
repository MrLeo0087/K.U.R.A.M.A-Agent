"""Task graph (Phase 2 of the memory + multitasking rebuild): a planned request runs as STEPS with real inputs and
outputs, not as separate mini-chats that pass each other a sentence.

  plan    planner.plan -> steps [{"text", "kind", "depends_on"}] (filler like "let's work .." dropped; a request seen
          before by meaning reuses its learned plan: 0 tokens)
  run     the agent's LangGraph loop: schedule -> every READY step at once (Send) -> schedule ... -> finish.
          A step gets what the steps it needs MADE (their files/folders/images become the freshest things in working
          memory, so "open it", "this folder", "that image" resolve to them) plus their answers. It tries the
          0-token shortcut first, else one AI call with only its own tools and NO chat history.
  check   judge(): a step that claims an action no tool did, whose tools all failed, or that said it couldn't, FAILED.
          One re-plan call (fast tier, ~150 tokens) may give a corrected step, tried once. Steps that need a failed
          step are skipped, with the reason. Steps that need a background job (an essay, a picture) become a
          follow-up job that runs on its real output.
  windows a "close X" step closes only the windows the plan opened; X open before the request -> it asks.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import re
from typing import Any, Iterator, Literal

from pydantic import BaseModel, Field

from jarvis.core import config

log = logging.getLogger(__name__)

INPUTS = "\n(Results of the earlier steps it needs, use them: {items})"
INPUTS_MAX = 1500
SKIPPED = "I skipped \"{text}\" because \"{need}\" didn't work."

# --- windows that existed before the plan (close_app reads it) ---
_WINDOWS: contextvars.ContextVar[frozenset | None] = contextvars.ContextVar("kurama_plan_windows", default=None)


def window_ids() -> list[str]:
    try:
        from jarvis.tools.general import _apps
        return [w["id"] for w in _apps.list_windows()]
    except Exception:  # noqa: BLE001  (no wmctrl / no display: nothing to protect)
        return []


@contextlib.contextmanager
def plan_windows(ids: list[str] | None) -> Iterator[None]:
    token = _WINDOWS.set(frozenset(ids) if ids is not None else None)
    try:
        yield
    finally:
        _WINDOWS.reset(token)


def windows_before() -> frozenset | None:
    """Window ids open before this multi-step request started (None outside a plan)."""
    return _WINDOWS.get()


# --- one step ---
def inputs_text(inputs: list[dict]) -> str:
    if not inputs:
        return ""
    items = []
    for r in inputs:
        files = f" Files: {', '.join(r['things'])}." if r.get("things") else ""
        items.append(f"step {r['idx'] + 1} ({r['text'][:80]}) -> {' '.join(str(r.get('answer', '')).split())[:400]}{files}")
    return INPUTS.format(items="; ".join(items))[:INPUTS_MAX]


def judge(answer: str, got: dict, bad: tuple[str, ...]) -> str:
    """'ok' | 'failed' | 'waiting' (a background job it started will make the result)."""
    from jarvis.core import meta
    a = (answer or "").strip()
    calls = got.get("calls") or []
    if not a or a.startswith(bad):
        return "failed"
    if calls and not any(ok for _, ok in calls):
        return "failed"
    if not calls and meta.claims(a):
        return "failed"  # "Made it - new_project2 is in Downloads" with no tool: nothing was made
    if got.get("jobs"):
        return "waiting"
    return "ok"


class Fix(BaseModel):
    """What to do about a failed step."""
    action: Literal["retry", "stop"] = "stop"
    text: str = Field("", description="the corrected step, in the user's words, when action=retry")


REPLAN_PROMPT = ("One step of the user's request failed. If a different way can still reach the same goal (another "
                 "name, the right folder or path, a simpler action), give that ONE corrected step (action=retry). If it "
                 "can't work or needs the user to decide, action=stop.")


def replan(step: str, answer: str, request: str) -> str:
    """A corrected step for a failed one ('' = stop). One small fast-tier call; any error = stop."""
    from jarvis.core import llm
    msgs = [{"role": "system", "content": REPLAN_PROMPT},
            {"role": "user", "content": f"Request: {request[:300]}\nStep: {step[:200]}\nWhat happened: {answer[:300]}"}]
    try:
        fix = llm.structured(msgs, Fix, tier="fast", purpose="replan", max_tokens=config.TASK_REPLAN_MAX_TOKENS,
                             priority="interactive")
    except Exception as e:  # noqa: BLE001
        log.info("re-plan failed: %s", e)
        return ""
    text = " ".join((fix.text or "").split())
    return text if fix.action == "retry" and text and text.lower() != step.lower() else ""


# --- the end: skipped steps, follow-ups after jobs ---
def settle(tasks: list[dict], done: dict[int, dict]) -> dict[int, dict]:
    """Every step's final state: the ones that ran, plus 'skipped' (a step it needs failed) or 'after' (a step it
    needs is a background job: it runs in a follow-up when that job is done)."""
    out = dict(done)
    for i, t in enumerate(tasks):
        if i in out:
            continue
        needs = [out[n] for n in t.get("depends_on", []) if n in out]
        bad = next((n for n in needs if n["status"] in ("failed", "skipped") and n["idx"] not in set(t.get("soft") or ())),
                   None)  # a soft link (order only) never skips it
        waits = [n for n in needs if n["status"] in ("waiting", "after") and n["idx"] not in set(t.get("soft") or ())]
        wait = waits[0] if waits else None
        jobs_ = sorted({j for n in waits for j in (n.get("jobs") or [n.get("job")]) if j})  # EVERY job it needs:
        # 'send image and poem' waited for the image job only and sent without the poem (11-04 00:11)
        if bad is not None:
            out[i] = {"idx": i, "text": t["text"], "status": "skipped",
                      "answer": SKIPPED.format(text=t["text"], need=bad["text"]), "things": []}
        elif wait is not None:
            out[i] = {"idx": i, "text": t["text"], "status": "after", "job": jobs_[0] if jobs_ else wait.get("job"),
                      "jobs": jobs_, "answer": "", "things": []}
        else:  # never ready (should not happen): say so instead of dropping it
            out[i] = {"idx": i, "text": t["text"], "status": "failed", "things": [],
                      "answer": f"Sorry, I couldn't get to this part: {t['text']}."}
    return out


# --- filler ---
def filler(text: str) -> bool:
    """A part of a multi-task request that asks for nothing ("let's work ..", "ok so", "hmm"): no step, no AI call.
    Short, not a command, and filler by meaning (config.FILLER_EXAMPLES vs NOT_FILLER_EXAMPLES)."""
    from jarvis.core import planner, semantic
    t = " ".join((text or "").split()).strip(" .!?,")
    if not t:
        return True
    if len(t.split()) > 4 or planner.is_command(t) or planner.refers_back(t):
        return False
    if not semantic.ready():
        return False
    best = semantic.best_of(t, "filler", {"filler": config.FILLER_EXAMPLES, "request": config.NOT_FILLER_EXAMPLES})
    return bool(best) and best[0] == "filler" and best[1] >= config.FILLER_MIN


# --- learned plans: a request seen before (by meaning) reuses its steps' links, 0 tokens ---
def _plans_path():
    return config.DATA_DIR / "learned_plans.json"


def _load_plans() -> list[dict]:
    try:
        return json.loads(_plans_path().read_text())
    except (OSError, ValueError):
        return []


def _vec(text: str) -> Any:
    from jarvis.core import semantic
    if not semantic.ready():
        return None
    import numpy as np
    v = np.asarray(semantic.embedder().embed([text], query=True)[0], dtype=np.float32)
    return v / (np.linalg.norm(v) or 1.0)


def learn_plan(text: str, clauses: list[str], tasks: list[dict]) -> None:
    """A plan the AI made that WORKED, with one step per clause of the request: keep its links (depends_on, kind)."""
    if len(tasks) != len(clauses) or len(tasks) < 2:
        return
    try:
        v = _vec(text)
        if v is None:
            return
        rows = [r for r in _load_plans() if r.get("text") != text]
        rows.append({"text": text[:300], "n": len(tasks), "vec": [round(float(x), 5) for x in v],
                     "links": [{"kind": t.get("kind", "quick"), "depends_on": t.get("depends_on", [])} for t in tasks]})
        _plans_path().write_text(json.dumps(rows[-config.TASK_PLANS_KEEP:]))
    except Exception as e:  # noqa: BLE001
        log.debug("could not learn plan: %s", e)


def learned_plan(text: str, clauses: list[str]) -> list[dict] | None:
    """Steps for a request whose meaning matches a learned plan with the same number of parts (None otherwise)."""
    rows = [r for r in _load_plans() if r.get("n") == len(clauses)]
    if not rows:
        return None
    try:
        import numpy as np
        v = _vec(text)
        if v is None:
            return None
        sims = np.asarray([r["vec"] for r in rows], dtype=np.float32) @ v
        k = int(sims.argmax())
        if float(sims[k]) < config.TASK_PLAN_MATCH:
            return None
    except Exception as e:  # noqa: BLE001
        log.debug("learned plan lookup failed: %s", e)
        return None
    out = []
    for i, (c, link) in enumerate(zip(clauses, rows[k]["links"])):
        d = {"text": c, "kind": link.get("kind", "quick")}
        if deps := [d_ for d_ in link.get("depends_on", []) if isinstance(d_, int) and 0 <= d_ < i]:
            d["depends_on"] = deps
        out.append(d)
    return out


def jobs_in(text: str) -> list[int]:
    return [int(m) for m in re.findall(r"\bjob #(\d+)", text or "")]
