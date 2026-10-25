"""Install / remove / update apps from apt, snap or flatpak — finds the right source, then installs in the background.

Root actions go through pkexec (apt) or snapd's own polkit check (snap), so Ubuntu shows its normal password popup
on the laptop; KURAMA never sees or stores the password. The tool itself is confirm-level (needs the user's yes). 0 tokens.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass

from jarvis.core import notify

log = logging.getLogger(__name__)

# spoken name -> (source, package, classic snap). Checked first; anything else is searched.
KNOWN: dict[str, tuple[str, str, bool]] = {
    "vs code": ("snap", "code", True), "vscode": ("snap", "code", True), "visual studio code": ("snap", "code", True),
    "pycharm": ("snap", "pycharm-community", True), "android studio": ("snap", "android-studio", True),
    "intellij": ("snap", "intellij-idea-community", True), "sublime": ("snap", "sublime-text", True),
    "postman": ("snap", "postman", False), "discord": ("snap", "discord", False),
    "spotify": ("snap", "spotify", False), "zoom": ("snap", "zoom-client", False),
    "telegram": ("snap", "telegram-desktop", False), "slack": ("snap", "slack", False),
    "obs": ("apt", "obs-studio", False), "obs studio": ("apt", "obs-studio", False), "vlc": ("apt", "vlc", False),
    "gimp": ("apt", "gimp", False), "inkscape": ("apt", "inkscape", False), "kdenlive": ("apt", "kdenlive", False),
    "libreoffice": ("apt", "libreoffice", False), "git": ("apt", "git", False), "curl": ("apt", "curl", False),
    "htop": ("apt", "htop", False), "ffmpeg": ("apt", "ffmpeg", False), "pandoc": ("apt", "pandoc", False),
    "audacity": ("apt", "audacity", False), "qbittorrent": ("apt", "qbittorrent", False),
    "chromium": ("snap", "chromium", False), "firefox": ("snap", "firefox", False),
    "brave": ("snap", "brave", False), "notion": ("snap", "notion-snap-reborn", False),
    "whatsapp": ("snap", "whatsapp-for-linux", False), "dbeaver": ("snap", "dbeaver-ce", False),
    "blender": ("snap", "blender", True), "node": ("snap", "node", True), "nodejs": ("snap", "node", True),
    "tesseract": ("apt", "tesseract-ocr", False), "gparted": ("apt", "gparted", False),
    "timeshift": ("apt", "timeshift", False), "neovim": ("apt", "neovim", False), "tmux": ("apt", "tmux", False),
}


@dataclass
class Pkg:
    source: str  # apt | snap | flatpak
    name: str
    classic: bool = False
    summary: str = ""
    installed: bool = False

    def label(self) -> str:
        return f"{self.name} ({self.source}{', installed' if self.installed else ''})" + (
            f" - {self.summary[:60]}" if self.summary else "")


def _out(argv: list[str], timeout: float = 25) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _apt(pkg: str) -> Pkg | None:
    if not shutil.which("apt-cache"):
        return None
    out = _out(["apt-cache", "policy", pkg])
    cand = re.search(r"Candidate:\s*(\S+)", out)
    if not cand or cand.group(1) == "(none)":
        return None
    inst = re.search(r"Installed:\s*(\S+)", out)
    summary = re.search(r"^Description(?:-en)?:\s*(.+)$", _out(["apt-cache", "show", "--no-all-versions", pkg]), re.M)
    return Pkg("apt", pkg, summary=summary.group(1) if summary else "",
               installed=bool(inst and inst.group(1) != "(none)"))


def _snap(pkg: str) -> Pkg | None:
    if not shutil.which("snap"):
        return None
    out = _out(["snap", "info", pkg])
    if not re.search(r"^name:\s*" + re.escape(pkg) + r"\s*$", out, re.M):
        return None
    summary = re.search(r"^summary:\s*(.+)$", out, re.M)
    classic = "classic" in (re.search(r"^\s*latest/stable:.*$", out, re.M) or [""])[0]
    return Pkg("snap", pkg, classic, summary.group(1) if summary else "", bool(re.search(r"^installed:", out, re.M)))


def _snap_search(q: str) -> list[Pkg]:
    out = _out(["snap", "find", q]) if shutil.which("snap") else ""
    res = []
    for line in out.splitlines()[1:6]:
        parts = line.split(None, 4)
        if len(parts) >= 4:
            res.append(Pkg("snap", parts[0], "classic" in parts[3], parts[4] if len(parts) > 4 else ""))
    return res


def _flatpak_search(q: str) -> list[Pkg]:
    out = _out(["flatpak", "search", "--columns=application,name,description", q]) if shutil.which("flatpak") else ""
    res = []
    for line in out.splitlines()[:5]:
        parts = line.split("\t")
        if len(parts) >= 2 and "." in parts[0]:
            res.append(Pkg("flatpak", parts[0], summary=f"{parts[1]} - {parts[2] if len(parts) > 2 else ''}"))
    return res


def find(name: str) -> list[Pkg]:
    """Best candidates for a spoken app name: the known table, then apt, snap, flatpak."""
    q = re.sub(r"\s+", " ", name.lower().strip())
    if q in KNOWN:
        src, pkg, classic = KNOWN[q]
        hit = _apt(pkg) if src == "apt" else _snap(pkg)
        if hit:
            hit.classic = hit.classic or classic
            return [hit]
    slug = q.replace(" ", "-")
    found = [p for p in (_apt(slug), _snap(slug)) if p]
    if found:
        return found
    return (_snap_search(q) + _flatpak_search(q))[:5]


def _on_pypi(name: str) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9._-]{2,60}", name):
        return False
    try:
        import httpx
        return httpx.get(f"https://pypi.org/pypi/{name}/json", timeout=6).status_code == 200
    except Exception:  # noqa: BLE001 - offline -> just "not found"
        return False


def _argv(action: str, p: Pkg) -> list[str]:
    if p.source == "apt":
        verb = "install" if action == "install" else "remove"
        return ["pkexec", "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", verb, "-y", p.name]
    if p.source == "snap":
        return ["snap", action, p.name, *(["--classic"] if action == "install" and p.classic else [])]
    return ["flatpak", action if action == "install" else "uninstall", "-y", "--noninteractive",
            *(["flathub"] if action == "install" else []), p.name]


def _bg(argv: list[str], title: str) -> None:
    def run() -> None:
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=3600)
            ok, tail = r.returncode == 0, (r.stderr or r.stdout).strip().splitlines()[-2:]
        except (OSError, subprocess.SubprocessError) as e:
            ok, tail = False, [str(e)]
        if not ok and any(w in " ".join(tail).lower() for w in ("dismissed", "not authorized", "126", "127")):
            tail = ["the password popup was cancelled"]
        notify.notify(f"{title} {'done' if ok else 'failed'}", "\n".join(tail)[-400:], level="info" if ok else
                      "warning", source="installer", telegram=True)
    threading.Thread(target=run, daemon=True).start()


def install(name: str, remove: bool = False) -> str:
    action = "remove" if remove else "install"
    cands = find(name)
    if not cands:
        if not remove and _on_pypi(name):  # not an app but a Python package: hand over to pip
            from jarvis.tools.interactive.python_env import python_env
            return getattr(python_env, "func", python_env)("install", name, ".")
        return f"I couldn't find an app called '{name}' in apt, snap or flatpak."
    p = cands[0]
    if not remove and p.installed:
        return f"{p.name} is already installed ({p.source})."
    if remove and p.source != "flatpak" and not p.installed:
        return f"{p.name} isn't installed."
    _bg(_argv(action, p), f"{action.title()} {p.name}")
    pw = " Enter your password in the popup on the laptop."
    return f"{'Installing' if not remove else 'Removing'} {p.name} from {p.source} in the background.{pw} " \
           f"I'll tell you when it's done."


def search(name: str) -> str:
    cands = find(name)
    if not cands:
        return f"Nothing called '{name}' in apt, snap or flatpak."
    return "Found:\n" + "\n".join(f"{i}. {p.label()}" for i, p in enumerate(cands, 1))


def update_all() -> str:
    script = "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get -y upgrade"
    _bg(["pkexec", "sh", "-c", script], "System update (apt)")
    if shutil.which("snap"):
        _bg(["snap", "refresh"], "Snap update")
    if shutil.which("flatpak"):
        _bg(["flatpak", "update", "-y", "--noninteractive"], "Flatpak update")
    return "Updating everything in the background. Enter your password in the popup; I'll tell you when it's done."
