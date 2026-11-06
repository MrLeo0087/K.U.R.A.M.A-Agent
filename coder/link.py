"""The ONLY place the coding agent touches KURAMA: background jobs, the Progress section's checklist, the folder
open in VS Code, opening a folder, the workspace, Telegram. Swap this file to run the agent elsewhere."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable


def submit(title: str, fn: Callable[[Any], str | None]) -> int:
    """Run fn(ctx) as a KURAMA background job; the turn that started it watches it (announced when done)."""
    from jarvis.core import jobs, safety
    job = jobs.get_manager().submit(title[:80], "coding", fn)
    try:
        if (started := safety.context().get("jobs")) is not None and job.id not in started:
            started.append(job.id)
    except Exception:  # noqa: BLE001
        pass
    return job.id


def channel() -> str:
    """Where the request came from ('telegram' = the phone)."""
    try:
        from jarvis.core import safety
        return str(safety.context().get("channel") or "")
    except Exception:  # noqa: BLE001
        return ""


def steps(job_id: int, items: list[tuple[str, str]]) -> None:
    from jarvis.core import progress
    progress.set_steps(job_id, items)


def pinned() -> Path | None:
    """The project the owner pinned (the path box in the coding chat, or the last project built / chosen)."""
    import json
    from coder import settings
    try:
        d = json.loads((settings.data_dir() / "project.json").read_text(encoding="utf-8"))
        p = Path(d.get("path") or "")
        return p if p.is_dir() else None
    except (OSError, ValueError):
        return None


def pin(path: str | Path | None) -> Path | None:
    """Pin the working project (None/'' = unpin: the VS Code window used last decides again)."""
    import json
    from coder import settings
    f = settings.data_dir() / "project.json"
    if not path:
        f.unlink(missing_ok=True)
        return None
    p = Path(str(path)).expanduser()
    if not p.is_dir():
        return None
    f.write_text(json.dumps({"path": str(p.resolve())}), encoding="utf-8")
    return p.resolve()


def vscode_root() -> Path | None:
    """The project worked on: the PINNED one when there is one (owner 11-06: "a box for the project path, so it
    never confuses which project"), else the folder of the VS Code window you used LAST (focused most recently), not the first one listed
    (11-06: new_folder was open and in use, the build went to the KURAMA window's folder)."""
    if (p := pinned()) is not None:
        return p
    try:
        from jarvis.core import editor
        states = [x for x in editor.states() if x.get("root")]
        if states:
            best = max(states, key=lambda x: (float(x.get("focused_at") or 0), bool(x.get("focused"))))
            return Path(best["root"])
        from jarvis.agents.coding.bridge import project_root
        return project_root()
    except Exception:  # noqa: BLE001
        return None


def open_folder(p: Path) -> None:
    try:
        subprocess.Popen(["code", str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def to_workspace(title: str, text: str) -> str:
    """The plan / report in the workspace; returns its one-line summary."""
    try:
        from jarvis.core import workspace
        line, _ = workspace.to_workspace(title, text, "en")
        return line
    except Exception:  # noqa: BLE001
        return ""


def tell(title: str, text: str) -> None:
    """A finished run on the laptop and in Telegram's Jobs section."""
    try:
        from jarvis.core import notify
        notify.notify(title, text, level="info", source="jobs", telegram=True)
    except Exception:  # noqa: BLE001
        pass


def claude_code(prompt: str, folder: Path) -> str:
    """Hand a big job to Claude Code: the folder opens in VS Code and a NEW Claude Code chat starts there with the
    ready prompt (KURAMA's Claude Code link). Uses the owner's Claude Code plan instead of Groq tokens."""
    import time as _t
    try:
        from jarvis.core import claudewatch, editor
    except Exception as e:  # noqa: BLE001
        return f"Claude Code isn't reachable ({e})."
    folder.mkdir(parents=True, exist_ok=True)
    if not claudewatch.is_on():
        claudewatch.turn_on()
    subprocess.Popen(["code", str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    st = None
    for _ in range(40):
        _t.sleep(0.5)
        st = claudewatch._window(str(folder))
        if st is not None and str(st.get("root") or "") == str(folder):
            break
    if st is None or str(st.get("root") or "") != str(folder):
        return f"I opened {folder} in VS Code, but couldn't reach Claude Code there. Paste the prompt from the workspace."
    r = editor.edit(st, "claude_new", text=" ".join(prompt.split()))
    if not r.get("ok") or not claudewatch._press_enter(folder.name):
        return "VS Code couldn't start the Claude Code chat. The prompt is in the workspace: paste it there."
    return f"Claude Code is building it in {folder} (a new chat in VS Code). /claude status shows how it's going."


def to_workspace_file(src: Path, title: str) -> None:
    """A picture (a screenshot of the app) into the workspace's images, next to the task's report."""
    try:
        import shutil
        import time as _t

        from jarvis.core import config
        dst = Path(config.OUTPUTS_DIR) / "images" / f"{_t.strftime('%Y%m%d-%H%M%S')}-{src.stem}-{abs(hash(title)) % 9999}.png"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    except Exception:  # noqa: BLE001
        pass


def tell_result(title: str, text: str, picture: Path | None = None, channel: str = "") -> None:
    """A finished task on the laptop and in Telegram's Jobs section, with its last screenshot."""
    tell(title, text)
    if picture is None or not picture.exists():
        return
    try:
        from jarvis.core import notify, tgtopics
        g, t = tgtopics.where("jobs", "info")
        from jarvis.core import config
        notify.telegram_call("sendPhoto", {"chat_id": g or config.TELEGRAM_CHAT_ID, **({"message_thread_id": t} if t else {}),
                                           "caption": title[:200]},
                             files={"photo": (picture.name, picture.read_bytes())}, upload=True, timeout=45)
    except Exception:  # noqa: BLE001
        pass
