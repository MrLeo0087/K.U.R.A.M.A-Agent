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


def steps(job_id: int, items: list[tuple[str, str]]) -> None:
    from jarvis.core import progress
    progress.set_steps(job_id, items)


def vscode_root() -> Path | None:
    """The project folder open in VS Code (the window in use)."""
    try:
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
