"""code_nav: jump to the real code of the highlighted function/class (project or installed library), 0 tokens (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="codequality", safety="safe", description="Highlighted code: find = open where a function/class is "
      "defined (project or library) in VS Code; help = its real arguments/docs and whether the call is right; run = run "
      "it and show the output.")
def code_nav(action: Literal["find", "help", "run"] = "find", name: str = "", request: str = "") -> str:
    """Code navigation and library help.

    Args:
        action: find (go to where it is defined), help (arguments, docs, is my call correct, suggestions) or run
            (run the highlighted code in a temp folder and show what it prints).
        name: the function/class name or call; empty = the text highlighted in VS Code.
        request: the user's question (for help: 'is this correct', 'suggest a better way'...).
    """
    from jarvis.core import assist, codenav, rewrite, timemachine

    text = name.strip()
    if not text:
        g = rewrite.grab()
        if isinstance(g, str):
            here = assist.open_file_in_editor() if action == "run" else None
            if here and here.is_file():  # 'run my code' with nothing highlighted = the saved file open in VS Code
                from jarvis.core import coderun
                return coderun.run(here.read_text(errors="replace"), timemachine.vscode_folder(), here, whole=True)
            return "Highlight the function name (or the line) in VS Code first, then ask again."
        text = g.text
    if action == "run":
        from jarvis.core import coderun
        if coderun.only_definitions(text):  # just a function: write + offer a run block that calls it
            from jarvis.tools.general.text_assist import text_assist
            return text_assist(action="use")
        return coderun.run(text, timemachine.vscode_folder(), assist.open_file_in_editor())
    if action == "help":
        from jarvis.core import libhelp
        return libhelp.help_for(text, request, timemachine.vscode_folder(), assist.open_file_in_editor())
    return codenav.go(text, timemachine.vscode_folder(), assist.open_file_in_editor())
