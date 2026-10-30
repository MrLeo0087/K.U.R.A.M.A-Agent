"""folder_lock: lock a folder/file with a password (AES-256, typed in a box on the laptop) or unlock it (confirm)."""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import tool


@tool(group="filesearch", safety="safe",  # typing the password twice in the box IS the yes (no extra yes/no first)
      description="Lock a folder or file with a password (encrypted into one file, original removed) or unlock it. "
                  "The password is typed into a box on the laptop, never in chat.")
def folder_lock(action: Literal["lock", "unlock"] = "lock", path: str = "") -> str:
    """Lock or unlock.

    Args:
        action: lock or unlock.
        path: The folder/file (a path, a name, or 'this' for the current one); for unlock, the locked one's name.
    """
    from jarvis.core import focus, vault
    try:
        if action == "unlock":
            locked = vault.find_locked(path.strip() or str(focus.cwd() or ""))
            if not locked:
                return f"error: I couldn't find a locked '{path}'."
            pw = vault.ask_password(f"Unlock {locked.name[: -len(vault.SUFFIX)]}", confirm=False)
            if pw is None:
                return "Cancelled."
            out = vault.unlock(locked, pw)
            focus.set_path(out)
            return f"Unlocked {out.name} ({out})."
        from jarvis.core.paths import resolve_target
        target = resolve_target(path)
        if isinstance(target, str):
            return target
        from jarvis.tools.general.send_file_telegram import too_broad
        if err := too_broad(target):
            return err.replace("send", "lock")
        pw = vault.ask_password(f"Lock {target.name}", confirm=True)
        if pw is None:
            return "Cancelled, nothing was locked."
        out = vault.lock(target, pw)
        focus.set_path(out.parent)
        return (f"Locked {target.name}. It is now one encrypted file: {out}. "
                f"Say 'unlock {target.name}' to open it. If you forget the password, it can't be recovered.")
    except vault.VaultError as e:
        return f"error: {e}"
