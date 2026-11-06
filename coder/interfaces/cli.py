"""The command line: the coding agent without KURAMA's window (the same agent, run in this terminal).

    python -m coder "make the buttons grey" --project ~/projects/site      a change (the agent loop)
    python -m coder "a snake game in pygame" --new --project ~/projects    a new project (plan, then build)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


class Console:
    """The job context the agent reports to: here, lines in the terminal."""
    class job:  # noqa: N801 - mirrors KURAMA's job object (job.id)
        id = 0

    def progress(self, text: str) -> None:
        print("  " + text, flush=True)

    def check(self) -> None:  # (Ctrl+C stops it)
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m coder", description="KURAMA's coding agent")
    ap.add_argument("task", help="what to do, in your own words")
    ap.add_argument("--project", default=".", help="the project folder (a new project goes INTO this folder)")
    ap.add_argument("--new", action="store_true", help="make a new project (plan, then build) instead of a change")
    a = ap.parse_args(argv)
    root = Path(a.project).expanduser().resolve()
    try:  # KURAMA's store (the Progress checklist, the shared memory) when KURAMA is here
        from jarvis.core import store
        store.init()
    except Exception:  # noqa: BLE001 - the agent still works without it
        pass
    from coder.core.run import new
    if a.new:
        from coder.builder import engine, understand
        run = new(a.task, root / understand.slug(a.task))
        run.stack, run.kind = understand.stack_of(a.task), "new"
        engine.plan_job(run)(Console())
        from coder.builder import planner
        print(planner.text(run))
        if input("Build it? [y/N] ").strip().lower() not in ("y", "yes"):
            return 0
        engine.build_job(run)(Console())
    else:
        if not root.is_dir():
            print(f"{root} isn't a folder", file=sys.stderr)
            return 2
        from coder.agent import loop
        run = new(a.task, root)
        run.kind = "add"
        loop.task_job(run, a.task)(Console())
    print(f"tokens: {run.tokens / 1000:.1f}k")
    return 0
