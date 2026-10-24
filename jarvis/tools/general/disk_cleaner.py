"""disk_cleaner: what fills the disk (incl. ML caches, old checkpoints, dead venvs, duplicates) and free it after asking
(safe; cleaning asks first). Replaces cleanup_scan (alias kept)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import diskclean as dc
from jarvis.core import safety
from jarvis.core.registry import alias, tool


@tool(group="daily", safety="safe", max_chars=1500,
      description="Disk space: what is using it (biggest folders, Hugging Face/pip/torch caches, old checkpoints, venvs "
                  "of old projects, duplicates, trash, old downloads) and clean a category after asking.")
def disk_cleaner(action: Literal["scan", "clean"] = "scan", category: str = "", path: str = "") -> str:
    """Disk cleaner.

    Args:
        action: scan = report (deletes nothing); clean = free `category` (asks first).
        category: hf_cache, torch_cache, pip_cache, trash, old_downloads, checkpoints, dead_venvs, pycache, duplicates.
        path: For scan: also list the biggest folders inside this folder.
    """
    if action == "scan":
        return dc.scan(path)
    cat = category.strip().lower().replace(" ", "_").replace("-", "_")
    cat = {"huggingface": "hf_cache", "hugging_face": "hf_cache", "cache": "pip_cache", "downloads": "old_downloads",
           "venvs": "dead_venvs", "venv": "dead_venvs", "duplicate": "duplicates"}.get(cat, cat)
    if cat not in dc.CATEGORIES:
        return f"error: say which: {', '.join(dc.CATEGORIES)}"
    items = dc.find(cat)
    if not items:
        return f"Nothing to clean in {dc.LABEL[cat]}."
    total = sum(dc.size_of(p) for p in items)
    how = "deleted (it refills itself when needed)" if cat in dc.SELF_REFILLING else "moved to the Trash"
    if cat == "duplicates":
        how += " (the oldest copy of each file is kept; each copy is compared byte for byte first)"
    shown = ", ".join(p.name for p in items[:4]) + (f" and {len(items) - 4} more" if len(items) > 4 else "")
    if not safety.ask(f"Free {dc.gb(total)} of {dc.LABEL[cat]} ({shown})? It will be {how}."):
        return "The user said no, so nothing was removed."
    n, freed = dc.clean(cat)
    return f"Freed {dc.gb(freed)}: {n} item(s) of {dc.LABEL[cat]} {how}."


alias("cleanup_scan", "disk_cleaner", lambda a: {"path": a.get("path", "") if a.get("path") not in ("~", None) else ""},
      action="scan")
