"""The coding agent's one tool for the AI (group coding_agent: offered only while the agent is on)."""
from __future__ import annotations

import re
from typing import Literal

from jarvis.core.registry import tool


@tool(group="coding_agent", safety="safe", max_chars=2500,
      description="Coding agent: project = build something (a new project, a new file of code, or a feature added to "
                  "the open project: request = what, with the user's words for where/stack) -> a plan, then built "
                  "after yes; fix the last crash (or a pasted error) as a reviewed change; bridge = copy a ready "
                  "prompt for ChatGPT/Gemini/Claude; apply = put the copied AI answer's code into the files; undo = "
                  "put back my last change (request 'project' = the last build); yes / no = answer a waiting plan "
                  "or change.")
def coding(action: Literal["fix", "bridge", "apply", "project", "undo", "yes", "no", "run"], request: str = "",
           site: str = "", error: str = "") -> str:
    """The coding agent.

    Args:
        action: fix, bridge, apply, project, undo, yes, no, run (run the last failed command again).
        request: fix: what the user said about it; bridge: the task for the big AI; project: what to build.
        site: bridge: chatgpt, gemini or claude to open it too (empty = only copy).
        error: fix: a pasted error text (empty = the last crash in the VS Code terminal).
    """
    from jarvis.agents import touch
    from jarvis.agents.coding import bridge, changes, fixer, project, terminal
    touch()
    if action == "fix":
        return fixer.fix(error, request)
    if action == "bridge":
        return bridge.pack(request, site)
    if action == "apply":
        return bridge.apply_answer(request)
    import coder  # the coding agent's own project (coder/): plans, builds, checks, fixes
    if action == "project":
        return coder.start(request)
    if action == "undo":
        if re.search(r"\b(?:project|build|built|everything|all of it|whole)\b", request or "", re.I):
            return coder.undo_last()
        return changes.undo()
    if action == "yes":
        if coder.pending() is not None:  # "the plan is in the workspace, say yes to build it"
            return coder.yes()
        if (c := changes.take_cost()) is not None:  # "this needs ~6k tokens, go ahead?" -> yes
            return (fixer.fix(**c["kwargs"], confirmed=True) if c["action"] == "fix"
                    else project.start(**c["kwargs"], confirmed=True))
        return changes.apply()
    if action == "no":
        if coder.pending() is not None:
            return coder.no()
        if changes.take_cost() is not None:
            return "Okay, I didn't do it (no tokens used)."
        return changes.cancel()
    last = terminal.last()
    return terminal.run_again(last["command"], last["cwd"]) if last else "Nothing failed recently to run again."
