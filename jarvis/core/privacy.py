"""Keep Jarvis data private to this user: called first thing by every entry point.

umask 077 makes every file/folder created afterwards (SQLite DBs, logs, outputs, skills) readable
only by the owner; data/ itself is tightened to 700 if it already exists.
"""
from __future__ import annotations

import os
from pathlib import Path


def harden(data_dir: str | Path | None = None) -> None:
    os.umask(0o077)
    if data_dir is None:
        from jarvis.core import config

        data_dir = config.DATA_DIR
    d = Path(data_dir)
    try:
        if d.is_dir():
            d.chmod(0o700)
    except OSError:
        pass  # not our folder (shared mount): umask still protects new files
