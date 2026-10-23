"""Helpers a generated tool may import inside the sandbox (`from jarvis_helpers import http_get, ...`).

Each one checks its own limits, then opens the runner's audit-hook gate (_GATE) only for its own
work. Generated code cannot reach _GATE or any other underscore name (the AST check refuses them).
"""
import ipaddress
import os
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse

_GATE = [0]
_SPEC: dict = {}
_DENY_READ = (".ssh", ".gnupg", ".aws", ".netrc", ".env", ".password-store", "keyrings", ".mozilla",
              ".config/google-chrome", ".config/chromium", "id_rsa", "id_ed25519", ".git-credentials",
              ".pypirc", ".docker/config.json", ".kube")
_NEVER = ("sudo", "su", "doas", "pkexec")
MAX_BYTES = 200_000


class _Open:
    def __enter__(self):
        _GATE[0] += 1

    def __exit__(self, *exc):
        _GATE[0] -= 1


def configure(spec: dict) -> None:
    _SPEC.clear()
    _SPEC.update(spec)


def _inside(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


def write_ok(path) -> bool:
    """True when path is inside the sandbox folder or a path the user named in the task."""
    try:
        p = Path(os.fsdecode(path)).expanduser()
        p = (Path(_SPEC.get("sandbox", ".")) / p if not p.is_absolute() else p).resolve()
    except (OSError, ValueError, TypeError):
        return False
    roots = [Path(_SPEC.get("sandbox", ".")).resolve()] + [Path(x).resolve() for x in _SPEC.get("write_paths", [])]
    return any(p == r or _inside(p, r) for r in roots)


def http_get(url: str) -> str:
    """GET a public http(s) URL (6 s timeout, first 200 KB as text)."""
    u = urlparse(str(url))
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("only http(s) URLs are allowed")
    with _Open():
        for info in socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80)):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise ValueError("local or private addresses are not allowed")
        import httpx

        chunks, size = [], 0
        with httpx.stream("GET", str(url), timeout=6.0, follow_redirects=True,
                          headers={"User-Agent": "Jarvis-tool/1.0"}) as r:
            for chunk in r.iter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if size >= MAX_BYTES:
                    break
        return b"".join(chunks)[:MAX_BYTES].decode(r.encoding or "utf-8", "replace")


def read_text(path: str) -> str:
    """Read a text file under the user's home folder (first 200 KB). Secret folders are refused."""
    home = Path(_SPEC.get("home") or Path.home()).resolve()
    p = Path(str(path)).expanduser().resolve()
    if not _inside(p, home):
        raise PermissionError("only files under your home folder can be read")
    low = str(p).lower()
    if any(d in low for d in _DENY_READ):
        raise PermissionError("that file may hold secrets; refused")
    with _Open():
        with open(p, "rb") as fh:
            return fh.read(MAX_BYTES).decode("utf-8", "replace")


def write_text(path: str, text: str) -> str:
    """Write text inside the tool's sandbox folder or to a path the user named in the task."""
    p = Path(str(path)).expanduser()
    if not p.is_absolute():
        p = Path(_SPEC.get("sandbox", ".")) / p
    if not write_ok(p):
        raise PermissionError("can only write inside the sandbox folder or a path you named")
    data = str(text)[:1_000_000]
    with _Open():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data, encoding="utf-8")
    return f"wrote {len(data)} chars to {p}"


def run_cmd(argv: list) -> str:
    """Run one allowlisted command (list form, no shell, 10 s timeout); returns its output."""
    argv = [str(a) for a in argv]
    if not argv:
        raise ValueError("empty command")
    binary = argv[0].rsplit("/", 1)[-1]
    if binary in _NEVER or binary not in _SPEC.get("allow_cmds", []):
        raise PermissionError(f"{binary} is not allowed")
    if any(c in a for a in argv for c in ("\n", "\x00")):
        raise ValueError("bad characters in the command")
    if _SPEC.get("dry_run_cmds"):
        return "[dry run] would run: " + " ".join(argv)
    with _Open():
        p = subprocess.run([binary] + argv[1:], capture_output=True, text=True, timeout=10,
                           stdin=subprocess.DEVNULL)
    out = (p.stdout or "") + (f"\n{p.stderr}" if p.returncode and p.stderr else "")
    return out.strip()[:4000] or f"exit code {p.returncode}"
