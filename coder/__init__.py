"""KURAMA's coding agent: its own project (owner, 11-06: "a separate folder and backend, so it can be changed or
upgraded on its own; memory shared, its own working process, a temporary memory for each run, linked to KURAMA").

    coder/             this package: the whole agent, nothing of it lives in jarvis/
      engine.py        the run, as a LangGraph graph: understand -> plan -> budget gate -> scaffold -> write ->
                       connect -> check -> fix (max 3) -> report
      understand.py    what to build and where (0 tokens): stack, folder, a question when it can't tell
      planner.py       ONE call: the file tree, each file's job, how they connect, the run command
      budget.py        the cost before spending it; over CODER_ASK_TOKENS (20k) it asks
      scaffold.py      official generators (npm create vite for React) and checked GitHub starters (github.py)
      writer.py        each file with the plan + only the files it uses; hard files -> smart model, easy -> fast
      connect.py       every import / <script> / stylesheet / local module really exists (0 tokens)
      verify.py        format + lint + compile / syntax checks (0 tokens)
      fixloop.py       an error -> only it and the lines around it -> a fix -> check again
      repomap.py       a project's map (files, functions, classes, imports) without the AI
      memory.py        .kurama/project.md (stack, run, files, decisions) + TODO.md, per project
      safety.py        a backup of every file before it changes (undo), a secret guard
      models.py        the AI calls (KURAMA's own LLM layer: same keys, same shared rate limit) + token count
      run.py           the run's state and its temporary memory (data/coder/runs/<id>/, deleted after)
      link.py          the ONLY place that talks to KURAMA: jobs, the Progress section, notifications

It runs as a KURAMA background job (in KURAMA's process: no second Python with its own ~150 MB, and Groq's limit
stays shared), but it only meets KURAMA through link.py and models.py, so it can be moved to its own process later.
KURAMA calls it through jarvis/agents/coding/tools.py: `coder.start(request)`.
"""
from __future__ import annotations

from coder.api import no, pending, start, undo_last, yes

__all__ = ["no", "pending", "start", "undo_last", "yes"]
