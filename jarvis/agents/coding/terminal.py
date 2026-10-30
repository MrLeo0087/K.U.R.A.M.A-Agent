"""The VS Code terminal while the coding agent is on: the editor-link extension reports every command that FAILED
(command, folder, exit code, the last part of its output). The failure is kept, announced in KURAMA ("Crashed:
KeyError in test.py line 12 — fix it?") and is what "fix it" means. After a fix KURAMA can run the same command
again in the same terminal. Nothing is recorded while the agent is off (the extension checks the agent marker).
"""
from __future__ import annotations

import re
import time

from jarvis.core import config

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)|\r")
_last: dict = {}
_events: list[dict] = []  # announcements for the dashboard (status payload), newest last
ACTIONS = [{"label": "Fix it", "say": "fix it"}, {"label": "Ask ChatGPT", "say": "ask chatgpt about this error"},
           {"label": "Ask Gemini", "say": "ask gemini about this error"},
           {"label": "Ask Claude", "say": "ask claude about this error"}]  # buttons under the announcement


def clean(output: str) -> str:
    """Terminal output without colour codes, the last AGENT_OUTPUT_MAX characters."""
    out = _ANSI.sub("", output or "")
    return out[-config.AGENT_OUTPUT_MAX:]


def record(command: str, cwd: str, exit_code: int | None, output: str, window: str = "") -> dict:
    """A failed command from the extension; returns the announcement (empty text = not worth announcing)."""
    from jarvis.agents import touch
    from jarvis.core import errmem
    out = clean(output)
    p = errmem.parse(out)
    where = ""
    if frames := errmem.user_frames(p.get("frames") or []):
        f, line, _ = frames[-1]
        where = f" in {f.rsplit('/', 1)[-1]} line {line}"
    _last.clear()
    _last.update(command=(command or "").strip(), cwd=cwd or "", code=exit_code, output=out, error=p.get("error", ""),
                 ts=time.time(), window=window)
    touch()
    if exit_code in (130, 2, 127) and not p.get("error"):  # Ctrl+C / a mistyped shell command: no announcement
        return {"text": ""}
    what = p.get("error") or f"`{_last['command'][:60]}` failed (exit code {exit_code})"
    known = errmem.lookup(p["error"]) if p.get("error") else None
    hint = " I've seen this one before." if known else ""
    ev = {"id": int(time.time() * 1000), "text": f"Crashed: {what[:160]}{where}.{hint} Want me to fix it?",
          "actions": ACTIONS}
    _events.append(ev)
    del _events[:-5]
    return ev


def last(max_age_s: float | None = None) -> dict | None:
    age = config.AGENT_FAILURE_MAX_AGE_S if max_age_s is None else max_age_s
    return dict(_last) if _last and time.time() - _last["ts"] < age else None


def events() -> list[dict]:
    return list(_events)


def run_again(command: str, cwd: str = "") -> str:
    """Run the command again in VS Code's terminal (the one it failed in), through the editor link."""
    from jarvis.core import editor
    states = editor.states()
    st = next((s for s in states if cwd and s.get("root") and cwd.startswith(s["root"])), states[0] if states else None)
    if st is None:
        return f"Run `{command}` again to check it."
    r = editor.edit(st, "terminal_run", text=command, cwd=cwd)
    return f"Running `{command}` again in the terminal…" if r.get("ok") else f"Run `{command}` again to check it."
