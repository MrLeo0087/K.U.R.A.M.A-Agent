"""The coding agent's one tool for the AI (group coding_agent: offered only while the agent is on)."""
from __future__ import annotations

import re
from typing import Literal

from jarvis.core.registry import tool


HELP = """CODING AGENT (/code <what> — or just say it while the coding agent is on)

Build
/code <what to build> — plan it (in the workspace), build it after your yes. e.g. /code a snake game in pygame
/code new <what> — the same
/code yes | no — build the waiting plan / drop it ("use Tailwind", "drop X" = a new plan)
/code continue — the project's next TODO item
/code claude — let Claude Code build the waiting plan (no Groq tokens)

Understand
/code learn — read the open project once (map + one small AI call) and write its project card

Check and fix
/code fix — fix the last crash in the VS Code terminal
/code tests [file.py] — write tests and run them
/code pass — make the failing tests pass
/code preview — open the web page (errors are collected)
/code check — fix the errors the page showed
/code look — a design look at the page
/code review — review your uncommitted changes
/code commit — a commit message (commits after yes)

Safety
/code diffs — what I changed, side by side in VS Code
/code reject <file> — that one file back
/code undo [project] — undo my last change / the whole last build
/code setup — make a .venv, install requirements.txt, run it and fix what breaks
/code tokens — tokens used per project
/code bridge — a ready prompt for ChatGPT / Gemini / Claude; /code apply — put its answer into the files

Plain words work too: "create a portfolio website", "add a dark mode to this project", "make the tests pass"."""


@tool(group="coding_agent", safety="safe", max_chars=2500,
      description="Coding agent: project = build something (a new project, a new file of code, or a feature added to "
                  "the open project: request = what, with the user's words for where/stack) -> a plan, then built "
                  "after yes; fix the last crash (or a pasted error) as a reviewed change; bridge = copy a ready "
                  "prompt for ChatGPT/Gemini/Claude; apply = put the copied AI answer's code into the files; undo = "
                  "put back my last change (request 'project' = the last build); yes / no = answer a waiting plan "
                  "or change; tests = write pytest tests (request: a file name or empty); pass = run the tests and fix "
                  "the code until they pass; review = review the uncommitted changes; commit = write a commit message "
                  "(commits after yes); diffs = show the last build's changes side by side; reject = put one file "
                  "back (request = its name); preview = open the web page with error collection; check_page = fix "
                  "the errors the page showed; look = the vision model's look at the page's design; continue = the "
                  "project's next TODO item; handoff = let Claude Code build the waiting plan; tokens = tokens used "
                  "per project; learn = read an existing project once and write its project card; help = everything "
                  "the coding agent can do. 'after that, <request>' while a build runs = queued.")
def coding(action: Literal["fix", "bridge", "apply", "project", "undo", "yes", "no", "run", "tests", "pass", "review",
                           "commit", "diffs", "reject", "preview", "check_page", "look", "continue", "handoff",
                           "tokens", "learn", "help", "new", "check", "claude", "setup"], request: str = "",
           site: str = "", error: str = "") -> str:
    """The coding agent.

    Args:
        action: fix, bridge, apply, project, undo, yes, no, run (run the last failed command again).
        request: fix: what the user said about it; bridge: the task for the big AI; project: what to build.
        site: bridge: chatgpt, gemini or claude to open it too (empty = only copy).
        error: fix: a pasted error text (empty = the last crash in the VS Code terminal).
    """
    from jarvis import agents
    from jarvis.agents.coding import bridge, changes, fixer, project, terminal
    action = {"new": "project", "check": "check_page", "claude": "handoff"}.get(action, action)  # /code words
    if action == "help" and (request or "").strip():  # '/code a snake game in pygame': build it
        action = "project"
    if action == "help":
        return HELP
    if agents.current() != "coding":  # a /code command switches the coding agent on (it stays while you code)
        agents.switch("coding")
    agents.touch()
    if action == "fix":
        said = f"{request} {error}".strip()
        crashed = terminal.last(1800) is not None or re.search(r"Traceback|Error:|error:|Exception|line \d+", error or "")
        if not crashed and len(said.split()) >= 4 and not re.fullmatch(r"\s*(?:fix|fix it|fix this|fix the error)\W*", said, re.I):
            # no crash: a change the owner describes ('the signs don't show', 'keep 9+8 on one screen') ->
            # planned and made in the project being worked on (11-06: "I can't tell which file this error comes from")
            import coder as _coder
            return _coder.start(said)
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
    if action == "learn":
        return coder.learn_project()
    if action == "setup":
        return coder.setup_project()
    if action in ("tests", "pass", "review", "commit", "diffs", "reject", "preview", "check_page", "look", "continue",
                  "handoff", "tokens"):
        return {"tests": lambda: coder.write_tests(request), "pass": coder.make_tests_pass,
                "preview": coder.preview_page, "check_page": coder.check_page,
                "look": lambda: coder.look_at_page(request),
                "continue": coder.continue_project, "handoff": coder.handoff, "tokens": coder.tokens_report,
                "review": coder.review_changes, "commit": coder.commit_prepare, "diffs": coder.diffs,
                "reject": lambda: coder.reject(request)}[action]()
    if action == "yes":
        if coder.pending() is not None:  # "the plan is in the workspace, say yes to build it"
            return coder.yes()
        if coder.commit_waiting():
            return coder.commit_yes()
        if (c := changes.take_cost()) is not None:  # "this needs ~6k tokens, go ahead?" -> yes
            return (fixer.fix(**c["kwargs"], confirmed=True) if c["action"] == "fix"
                    else project.start(**c["kwargs"], confirmed=True))
        return changes.apply()
    if action == "no":
        if coder.pending() is not None:
            return coder.no()
        if coder.commit_waiting():
            return coder.commit_no()
        if changes.take_cost() is not None:
            return "Okay, I didn't do it (no tokens used)."
        return changes.cancel()
    last = terminal.last()
    return terminal.run_again(last["command"], last["cwd"]) if last else "Nothing failed recently to run again."
