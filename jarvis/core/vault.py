"""Lock a folder (or file) with a password: AES-256 encrypted, one file, the original removed; unlock restores it.

  lock:   tar | gpg --symmetric AES256  ->  <name>.locked.gpg next to it; checked by decrypting the listing,
          then the original is deleted.
  unlock: gpg -d | tar -x back into the same place, then the .locked.gpg is deleted.

The password is typed into a password box on the laptop (zenity) and handed to gpg through a pipe: it never goes
to the chat, the LLM, the logs or disk. If the password is forgotten the data is gone (AES has no back door). 0 tokens.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

SUFFIX = ".locked.gpg"


class VaultError(Exception):
    pass


def ask_password(title: str, confirm: bool) -> str | None:
    """Password box on the laptop screen (None = cancelled). confirm=True asks twice and compares."""
    if not shutil.which("zenity"):
        raise VaultError("zenity is missing (sudo apt install zenity)")
    def one(text: str) -> str | None:
        r = subprocess.run(["zenity", "--password", "--title", title, "--text", text, "--timeout", "120"],
                           capture_output=True, text=True)
        return r.stdout.rstrip("\n") if r.returncode == 0 else None
    pw = one("Password")
    if not pw:
        return None
    if confirm:
        again = one("Type the same password again")
        if again != pw:
            raise VaultError("the two passwords didn't match; nothing was locked")
        if len(pw) < 4:
            raise VaultError("use a password of at least 4 characters")
    return pw


def _gpg(args: list[str], pw: str, stdin=None, stdout=None) -> subprocess.Popen:
    r, w = os.pipe()
    os.write(w, pw.encode() + b"\n")
    os.close(w)
    p = subprocess.Popen(["gpg", "--batch", "--yes", "--quiet", "--no-symkey-cache", "--pinentry-mode", "loopback", "--passphrase-fd",
                          str(r), *args], stdin=stdin, stdout=stdout, stderr=subprocess.PIPE, pass_fds=(r,))
    os.close(r)
    return p


def lock(target: Path, pw: str) -> Path:
    target = target.resolve()
    if not target.exists():
        raise VaultError(f"{target} doesn't exist")
    if target.name.endswith(SUFFIX):
        raise VaultError("that is already locked")
    out = target.parent / (target.name + SUFFIX)
    if out.exists():
        raise VaultError(f"{out.name} already exists")
    tar = subprocess.Popen(["tar", "-czf", "-", "-C", str(target.parent), target.name], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
    g = _gpg(["--symmetric", "--cipher-algo", "AES256", "-o", str(out)], pw, stdin=tar.stdout)
    tar.stdout.close()  # type: ignore[union-attr]
    _, gerr = g.communicate(timeout=3600)
    tar.wait(timeout=60)
    if tar.returncode != 0 or g.returncode != 0 or not out.exists():
        out.unlink(missing_ok=True)
        raise VaultError((gerr or b"").decode(errors="replace").strip()[:200] or "encryption failed")
    # prove it opens with this password BEFORE deleting anything
    g2 = _gpg(["-d", str(out)], pw, stdout=subprocess.PIPE)
    lst = subprocess.run(["tar", "-tzf", "-"], stdin=g2.stdout, capture_output=True, timeout=600)
    g2.wait(timeout=60)
    if g2.returncode != 0 or lst.returncode != 0 or not lst.stdout.strip():
        out.unlink(missing_ok=True)
        raise VaultError("the check after locking failed; the original was kept")
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return out


def unlock(locked: Path, pw: str) -> Path:
    locked = locked.resolve()
    if not locked.name.endswith(SUFFIX):
        raise VaultError(f"{locked.name} isn't a locked KURAMA file")
    name = locked.name[: -len(SUFFIX)]
    if (locked.parent / name).exists():
        raise VaultError(f"{name} already exists next to it; move it first")
    g = _gpg(["-d", str(locked)], pw, stdout=subprocess.PIPE)
    tar = subprocess.run(["tar", "-xzf", "-", "-C", str(locked.parent)], stdin=g.stdout, capture_output=True,
                         timeout=3600)
    _, gerr = g.communicate(timeout=60)
    if g.returncode != 0:
        shutil.rmtree(locked.parent / name, ignore_errors=True)
        msg = (gerr or b"").decode(errors="replace")
        raise VaultError("wrong password" if "bad" in msg.lower() or "decrypt" in msg.lower() else msg.strip()[:200])
    if tar.returncode != 0 or not (locked.parent / name).exists():
        raise VaultError("couldn't restore the files: " + tar.stderr.decode(errors="replace").strip()[:200])
    locked.unlink()
    return locked.parent / name


def find_locked(name: str) -> Path | None:
    """The .locked.gpg for a loose name: a path, '<name>.locked.gpg' next to the current folder, or anywhere."""
    p = Path(name).expanduser()
    if p.is_file() and p.name.endswith(SUFFIX):
        return p
    if p.with_name(p.name + SUFFIX).is_file():
        return p.with_name(p.name + SUFFIX)
    from jarvis.core import focus
    for base in filter(None, (focus.cwd(), focus.cwd().parent if focus.cwd() else None)):
        hits = [q for q in base.glob("*" + SUFFIX) if _same(q.name[: -len(SUFFIX)], name)]
        if hits:
            return hits[0]
    from jarvis.tools.general.find_and_send import search
    hits = [q for q in search(f"{Path(name).name}{SUFFIX}") if q.name.endswith(SUFFIX)] or \
        [q for q in search(Path(name).name) if q.name.endswith(SUFFIX)]
    return hits[0] if hits else None


def _same(a: str, b: str) -> bool:
    from jarvis.core.paths import norm
    return norm(a) == norm(Path(b).name)
