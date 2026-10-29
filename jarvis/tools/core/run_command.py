"""run_command: run ONE terminal command on the laptop. The owner's rule: KURAMA asks before EVERY command (confirm),
shows the exact command in the question, never uses sudo, and refuses commands that could wreck the system."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from jarvis.core.registry import tool

TIMEOUT_S = 60
NEVER = re.compile(r"\b(?:sudo|su|doas|pkexec|mkfs\S*|fdisk|parted|shutdown|reboot|poweroff|halt)\b|"
                   r"\brm\s+-[a-z]*r[a-z]*f?[a-z]*\s+(?:/|~|\$HOME|/\*)(?:\s|$)|\bdd\b[^|]*\bof=/dev/|:\(\)\s*\{|>\s*/dev/sd|chmod\s+-R\s+777\s+/",
                   re.I)


@tool(group="core", safety="confirm", max_chars=1500,
      description="Run one terminal command on the laptop (bash) and return its output; asks the user first, every time. "
                  "Use for things no other tool does (file sizes, git, pip, system info...). Never sudo.")
def run_command(command: str, folder: str = "") -> str:
    """Run a shell command.

    Args:
        command: The exact bash command, e.g. 'du -sh ~/Downloads' or 'ls -la'.
        folder: Folder to run it in (default: home).
    """
    cmd = (command or "").strip()
    if not cmd:
        return "error: no command"
    if NEVER.search(cmd):
        return "Refused: that command could damage the system or needs sudo. I never run it."
    cwd = Path(os.path.expanduser(folder or "~"))
    if not cwd.is_dir():
        return f"error: not a folder: {cwd}"
    try:
        cp = subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT_S,
                            stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return f"Stopped: the command ran longer than {TIMEOUT_S} s."
    out = (cp.stdout or "") + (("\n" + cp.stderr) if cp.stderr.strip() else "")
    return (f"exit {cp.returncode}\n" if cp.returncode else "") + (out.strip() or "(no output)")
