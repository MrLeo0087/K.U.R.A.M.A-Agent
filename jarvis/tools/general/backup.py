"""backup: back up project folders to another drive with rsync (never deletes there, skips venvs/caches, checks
itself), weekly and when the drive is plugged in (safe)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import automation
from jarvis.core.registry import tool


@tool(group="automation", safety="safe",
      description="Backups: set which folders go to which drive/folder, run a backup now (verified), or status. Runs "
                  "weekly and when the backup drive is plugged in.")
def backup(action: Literal["status", "setup", "run", "drives"] = "status", folders: str = "", target: str = "") -> str:
    """Backup.

    Args:
        action: status, setup (`folders` -> `target`), run now, or drives (plugged-in drives you could use).
        folders: Folders to back up, comma separated (loose names work, e.g. "kurama, tara").
        target: Where to (e.g. /media/leo/MyPassport/backup).
    """
    if action == "setup":
        return automation.backup_set([f for f in folders.split(",")], target)
    if action == "run":
        return automation.backup_run()
    if action == "drives":
        return "Drives: " + (", ".join(automation.removable_drives()) or "none mounted")
    return automation.backup_status()
