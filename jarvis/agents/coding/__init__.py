"""The coding agent (owner: "separate from KURAMA, only when I turn it on"). While on:
- the VS Code extension reports failed terminal commands -> "Crashed: ... Want me to fix it?" (terminal.py)
- "fix it" -> the fix as a reviewed change, yes applies it and runs the command again (fixer.py, changes.py)
- "ask ChatGPT / Gemini about this" -> one ready prompt copied (+ the site opened); "apply the answer" puts the
  copied answer's code into the right files (bridge.py, 0 tokens)
- "make a new project: ..." -> files + requirements + venv + VS Code + a first run (project.py)
- "undo that" -> the last change put back (changes.py)
Its requests are understood by meaning (EXAMPLES, local model, 0 tokens); everything else still works as usual.
"""
from __future__ import annotations

from jarvis.agents import AgentSpec

EXAMPLES: dict[str, tuple[str, ...]] = {
    "fix": ("fix it", "fix this error", "fix the crash", "why did it crash", "solve this error", "it crashed, fix it",
            "repair the bug", "make it work", "debug this", "what is this error and fix it"),
    "bridge": ("ask chatgpt about this", "ask gemini to fix this", "make a prompt for chatgpt", "send this to claude",
               "prepare this for chatgpt", "copy the prompt for gemini", "this is too big, ask chatgpt"),
    "apply": ("apply the answer", "apply chatgpt's answer", "put the copied answer in the files", "use this answer",
              "apply what gemini said", "apply the copied code"),
    "project": ("make a new project", "create a fastapi project for a todo app", "set up a flask app",
                "create a rock paper scissors game in html css and javascript", "create a react project",
                "build a snake game in pygame", "add a scoreboard to this project", "create a new file app.js here",
                "start a new python project that scrapes news", "build me a small app", "create a project for",
                "setup a cnn model training project", "create a pytorch project to train an image classifier",
                "make a machine learning project", "set up a project to train a model on mnist",
                "build a streamlit dashboard project", "start a data analysis project with pandas",
                "create a rag chatbot project", "new project for a telegram bot"),
    "undo": ("undo that", "undo your change", "put the old code back", "revert what you did", "undo the fix",
             "undo the project", "undo everything you built"),
    "tests": ("write tests for this project", "make unit tests for this code", "create pytest tests",
              "add tests for game.py", "generate test cases for my project"),
    "pass": ("make the tests pass", "fix the failing tests", "run the tests and fix them", "the tests fail, fix it"),
    "review": ("review my changes", "check my code changes for bugs", "code review my uncommitted work",
               "is my change ok before i commit"),
    "commit": ("commit this", "commit my changes", "write a commit message", "make a git commit"),
    "diffs": ("show me what you changed", "show the changes side by side", "open the diff", "what did you change"),
    "reject": ("reject app.js", "put back style.css", "i don't want the change in main.py", "reject that file"),
    "run": ("run it again", "run the project", "run it"),
}

def _start() -> None:
    """While on, the meaning model stays loaded (its requests are understood by meaning, never a cold wait)."""
    import threading

    from jarvis.core import semantic

    def warm() -> None:
        semantic.scores("fix it")
        if semantic._embedder is not None:
            semantic._embedder.idle_s = 0.0  # 0 = never unload
    threading.Thread(target=warm, daemon=True, name="coding-agent-warm").start()


def _stop() -> None:
    from jarvis.core import semantic
    if semantic._embedder is not None:
        semantic._embedder.idle_s = semantic._idle_for(semantic.mode())
        if semantic._embedder.loaded:
            semantic._embedder._arm()  # the normal idle time counts from now


SPEC = AgentSpec(
    name="coding", title="Coding agent", groups=("coding_agent",),
    prompt=("Coding agent ON: the user is coding. Use the tool named `coding`: action=fix for errors, bridge for a "
            "prompt for ChatGPT/Gemini, project to create a new project (request = what to build), undo, run. There "
            "is no other project/fix tool. Never claim a change: changes are shown and wait for the user's yes."),
    examples=EXAMPLES, start=_start, stop=_stop, aliases=("code", "coder", "programming"),
    welcome=lambda: _welcome(), status=lambda: _status())


def _welcome() -> str:
    from jarvis.core import config
    msg = ("Coding agent on. Run your code in the VS Code terminal: if it crashes I'll tell you and fix it. "
           "Say 'stop coding agent' (or General) when you're done.")
    try:  # a VS Code window still running the old extension can't see the terminal: say how to fix that
        from jarvis.core import editor
        if [s for s in editor.states() if int(s.get("ext") or 0) < config.EDITOR_EXT_MIN]:
            msg += " (Reload your VS Code window once — Ctrl+Shift+P → Reload Window — so I can see crashes.)"
    except Exception:  # noqa: BLE001
        pass
    return msg


def _status() -> dict:
    from jarvis.agents.coding import terminal
    return {"events": terminal.events()}
