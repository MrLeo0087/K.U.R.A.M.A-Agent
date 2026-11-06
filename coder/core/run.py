"""One run's state and its temporary memory: data/coder/runs/<id>/ holds the plan, the backups (for undo) and
notes while it works; on success only the undo record is kept (the newest 10 runs), the rest is deleted."""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from coder.core import settings


@dataclass
class FileSpec:
    path: str  # relative to the project root
    purpose: str
    uses: list[str] = field(default_factory=list)  # files it depends on (written first, shown to the writer)
    level: str = "normal"  # easy | normal | hard -> which model writes it


@dataclass
class Run:
    id: str
    request: str
    root: Path
    stack: str = ""
    kind: str = "new"  # new (an empty / new folder) | add (into an existing project)
    plan_name: str = ""
    files: list[FileSpec] = field(default_factory=list)
    run_cmd: str = ""
    notes: str = ""
    todo: list[str] = field(default_factory=list)
    scaffold: str = ""  # what made the starting files: "vite-react-ts", "github:owner/repo", ""
    written: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    needs: list[str] = field(default_factory=list)  # packages the program needs that aren't installed
    tokens: int = 0
    estimate: int = 0
    todo_item: str = ""  # the TODO.md line this run does ('continue the project'): ticked when built
    channel: str = ""  # where it was asked ("telegram": the plan and the result also go to the phone)
    started: float = field(default_factory=time.time)

    @property
    def dir(self) -> Path:
        d = settings.data_dir() / "runs" / self.id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self) -> None:
        d = asdict(self)
        d["root"] = str(self.root)
        (self.dir / "run.json").write_text(json.dumps(d, indent=1), encoding="utf-8")

    def note(self, text: str) -> None:
        with (self.dir / "notes.txt").open("a", encoding="utf-8") as fh:
            fh.write(time.strftime("%H:%M:%S ") + text + "\n")


def new(request: str, root: Path) -> Run:
    return Run(id=time.strftime("%Y%m%d-%H%M%S"), request=request, root=root)


def finish(run: Run) -> None:
    """The temporary memory goes; the undo record (backups + created list) stays for the newest 10 runs."""
    for name in ("notes.txt",):
        (run.dir / name).unlink(missing_ok=True)
    runs = sorted((settings.data_dir() / "runs").iterdir(), key=lambda p: p.name)
    for old in runs[:-10]:
        shutil.rmtree(old, ignore_errors=True)


def last_run() -> Path | None:
    d = settings.data_dir() / "runs"
    runs = sorted((p for p in d.iterdir() if (p / "undo.json").exists()), key=lambda p: p.name) if d.exists() else []
    return runs[-1] if runs else None
