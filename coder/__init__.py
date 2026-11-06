"""KURAMA's coding agent: a project of its own (a small Claude Code for this laptop), linked to KURAMA.

    coder/
      core/        settings, the state of a run, safety (backups, undo, secret guard)
      llm/         which model for which job, the cost before it starts
      memory/      the project card, learning a project once, the 0-token project map
      tools/       read / grep / edit / write / run / run_project / screenshot / look / …
      runtime/     programs and web pages run for real, tests, git review
      agent/       the agent loop: plan -> one tool per step -> the code checks the work
      builder/     a new project from one sentence (plan, scaffold, write, connect, verify, fix)
      interfaces/  the API KURAMA calls, the only file that touches KURAMA (link.py), the command line

    Flow of a request:  interfaces.api.start() -> new project: builder (plan, your yes, build)
                                               -> change / fix / run in a project: agent.loop (no plan yes)
Run it alone:  python -m coder "make the buttons grey" --project ~/projects/site
"""
from __future__ import annotations

from coder.interfaces.api import (
                       check_page,
                       commit_no,
                       commit_prepare,
                       commit_waiting,
                       commit_yes,
                       continue_project,
                       diffs,
                       handoff,
                       learn_project,
                       look_at_page,
                       make_tests_pass,
                       no,
                       pending,
                       preview_page,
                       reject,
                       review_changes,
                       setup_project,
                       start,
                       tokens_report,
                       undo_last,
                       write_tests,
                       yes,
)

__all__ = ["check_page", "commit_no", "commit_prepare", "commit_waiting", "commit_yes", "continue_project", "diffs",
           "handoff", "learn_project", "look_at_page", "make_tests_pass", "no", "pending", "preview_page", "reject", "review_changes", "setup_project",
           "start", "tokens_report", "undo_last", "write_tests", "yes"]
