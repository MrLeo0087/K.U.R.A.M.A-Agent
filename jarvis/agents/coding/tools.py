"""The coding agent's one tool for the AI (group coding_agent: offered only while the agent is on)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="coding_agent", safety="safe", max_chars=2500,
      description="Coding agent: fix the last crash (or a pasted error) as a reviewed change; bridge = copy a ready "
                  "prompt for ChatGPT/Gemini/Claude (task, error, files, project tree); apply = put the copied AI "
                  "answer's code into the files; project = create a new runnable project; undo = put back my last "
                  "change; yes / no = answer a waiting change.")
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
    if action == "project":
        return project.start(request)
    if action == "undo":
        return changes.undo()
    if action == "yes":
        return changes.apply()
    if action == "no":
        return changes.cancel()
    last = terminal.last()
    return terminal.run_again(last["command"], last["cwd"]) if last else "Nothing failed recently to run again."
