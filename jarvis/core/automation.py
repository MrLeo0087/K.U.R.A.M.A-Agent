"""File automations (0 tokens): overnight downloads, a tidy Downloads folder, and backups that check themselves.

Downloads: "download <url> tonight" queues it (watches table, kind "dl"); the process_watch worker starts it when it's
due (now, or after DOWNLOAD_NIGHT_HOUR), with wget -c so a broken connection resumes instead of restarting, retries
up to 3 times, and says when it's done (size, folder) on the desktop and phone.

Downloads sorter: files in ~/Downloads (not folders, not half-downloaded .part/.crdownload, not touched in the last
5 minutes) move into Documents/Images/Videos/Audio/Archives/Code/Data/Installers sub-folders; screenshots go to
Images/Screenshots; an exact duplicate goes to the Trash. Preview first; "auto" re-runs it daily.

Backup: rsync copies your projects to a backup folder (an external drive or another disk), never deleting anything
there, skipping venvs/caches; then a dry run checks that nothing is left to copy ("verified"). Runs weekly by itself
and when the backup drive is plugged in.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

from jarvis.core import config, notify, store

# ---------------------------------------------------------------- downloads
def dl_dir() -> Path:
    d = Path(config.DOWNLOAD_DIR).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _name_from(url: str) -> str:
    tail = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"[^\w.\-]+", "_", tail) or f"download-{int(time.time())}"


def queue(url: str, folder: str = "", when: str = "now") -> str:
    url = url.strip()
    if not re.match(r"^https?://\S+$", url):
        return "error: give a full http(s) link"
    target = Path(folder).expanduser() if folder else dl_dir()
    if folder and not target.is_dir():
        from jarvis.core.paths import smart_path
        target = smart_path(folder, want="dir") or dl_dir()
    start = time.time()
    if when == "tonight":
        now = datetime.now()
        night = now.replace(hour=config.DOWNLOAD_NIGHT_HOUR, minute=0, second=0, microsecond=0)
        if night <= now and now.hour >= 6:  # already past tonight's start: the coming night
            night += timedelta(days=1)
        start = max(night.timestamp(), time.time())
    name = _name_from(url)
    taken = {Path(w["state"]["folder"]) / w["label"] for w in store.watches_list(("active",)) if w["kind"] == "dl"}
    stem, suf, n = Path(name).stem, Path(name).suffix, 1
    while (target / name) in taken or (target / name).exists():
        name = f"{stem} ({n}){suf}"
        n += 1
    wid = store.watch_add("dl", url, name, "", {"folder": str(target), "start_at": start, "tries": 0, "pid": 0})
    when_txt = "now" if start <= time.time() + 1 else datetime.fromtimestamp(start).strftime("at %H:%M")
    return f"Download #{wid} ({name}) starts {when_txt} into {target}; it resumes if the connection breaks."


def _launch(w: dict) -> None:
    st = w["state"]
    path = Path(st["folder"]) / w["label"]
    log = Path(config.DATA_DIR) / "runs" / f"dl-{w['id']}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as f:
        p = subprocess.Popen(["wget", "-c", "--tries=3", "--timeout=30", "-O", str(path), w["target"]],
                             stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    st.update(pid=p.pid, path=str(path), tries=int(st.get("tries", 0)) + 1, started=time.time())
    store.watch_update(w["id"], state=st)
    key = f"dl_exit:{w['id']}:{st['tries']}"
    import threading
    threading.Thread(target=lambda: store.kv_set(key, str(p.wait())), daemon=True).start()


def check_download(w: dict) -> None:
    """Worker tick for one download: start when due, notice the end, retry a failure (resuming)."""
    st = w["state"]
    if not st.get("pid"):
        if time.time() >= float(st.get("start_at") or 0):
            _launch(w)
        return
    rc = store.kv_get(f"dl_exit:{w['id']}:{st['tries']}")
    if rc is None:
        if Path(f"/proc/{st['pid']}").exists():
            return
        rc = "-1"
    path = Path(st["path"])
    size = path.stat().st_size if path.exists() else 0
    if rc == "0" and size:
        store.watch_update(w["id"], status="done", finished=time.time(), result=f"{size / 1e6:.1f} MB", state=st)
        notify.notify(f"Downloaded {w['label']}", f"{size / 1e6:.1f} MB in {st['folder']}", level="info",
                      source="downloads", telegram=True)
    elif st["tries"] < 3:
        st["pid"] = 0
        st["start_at"] = time.time() + 60  # wait a minute, then resume where it stopped
        store.watch_update(w["id"], state=st)
    else:
        store.watch_update(w["id"], status="failed", finished=time.time(), result=f"failed (wget exit {rc})", state=st)
        notify.notify(f"Download failed: {w['label']}", f"{w['target']}\nwget exit {rc} after 3 tries; "
                      f"{size / 1e6:.1f} MB kept, saying 'download it again' resumes.", level="warning",
                      source="downloads")


def downloads_text() -> str:
    rows = [w for w in store.watches_list() if w["kind"] == "dl"][:8]
    if not rows:
        return "No downloads."
    out = []
    for w in rows:
        st = w["state"]
        path = Path(st.get("path") or Path(st["folder"]) / w["label"])
        mb = path.stat().st_size / 1e6 if path.exists() else 0
        when = "" if st.get("pid") or w["status"] != "active" else \
            f", starts {datetime.fromtimestamp(st['start_at']).strftime('%H:%M')}"
        out.append(f"#{w['id']} {w['label']}: {w['status']}{when}, {mb:.1f} MB so far" if w["status"] == "active"
                   else f"#{w['id']} {w['label']}: {w['status']} {w.get('result') or ''}".rstrip())
    return "\n".join(out)


# ---------------------------------------------------------------- downloads sorter
SORT = {"Documents": {".pdf", ".doc", ".docx", ".odt", ".ppt", ".pptx", ".odp", ".xls", ".xlsx", ".ods", ".txt", ".md",
                      ".epub", ".rtf"},
        "Images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".heic", ".bmp", ".tif", ".tiff"},
        "Videos": {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"},
        "Audio": {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".aac"},
        "Archives": {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".xz", ".bz2"},
        "Code": {".py", ".ipynb", ".js", ".ts", ".html", ".css", ".java", ".c", ".cpp", ".sh", ".json", ".yaml", ".yml"},
        "Data": {".csv", ".tsv", ".parquet", ".xml", ".sqlite", ".db", ".npy", ".npz", ".pkl", ".h5", ".pt", ".pth",
                 ".onnx", ".safetensors"},
        "Installers": {".deb", ".appimage", ".run", ".rpm", ".snap", ".flatpak"}}
PARTIAL = {".part", ".crdownload", ".tmp", ".download", ".partial"}


def _md5(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sort_plan(folder: Path | None = None) -> list[tuple[Path, Path | None]]:
    """[(file, destination or None = duplicate to trash)]."""
    d = folder or Path.home() / "Downloads"
    plan: list[tuple[Path, Path | None]] = []
    seen: dict[tuple[int, str], Path] = {}
    files = sorted((f for f in d.iterdir() if f.is_file() and not f.name.startswith(".")), key=lambda f: f.stat().st_mtime)
    for f in files:
        if f.suffix.lower() in PARTIAL or time.time() - f.stat().st_mtime < 300:
            continue
        try:
            key = (f.stat().st_size, _md5(f)) if f.stat().st_size < 2 * 1024 ** 3 else None
        except OSError:
            continue
        if key and key in seen:
            plan.append((f, None))
            continue
        if key:
            seen[key] = f
        cat = next((c for c, exts in SORT.items() if f.suffix.lower() in exts), None)
        if cat is None:
            continue
        if cat == "Images" and re.match(r"(?i)^(screenshot|screen ?shot|scrot|jarvis-\d)", f.name):
            cat = "Images/Screenshots"
        plan.append((f, d / cat))
    return plan


def sort_preview() -> str:
    plan = sort_plan()
    if not plan:
        return "Downloads is already tidy."
    by: dict[str, int] = {}
    for _, dest in plan:
        k = dest.name if dest else "duplicates to Trash"
        by[k] = by.get(k, 0) + 1
    return f"I'd move {sum(by.values())} files: " + ", ".join(f"{k} {v}" for k, v in by.items()) + \
        ". Say 'sort my downloads' to do it."


def sort_run() -> str:
    moved, dupes = 0, 0
    for f, dest in sort_plan():
        try:
            if dest is None:
                subprocess.run(["gio", "trash", str(f)], check=True, capture_output=True, timeout=30)
                dupes += 1
                continue
            dest.mkdir(parents=True, exist_ok=True)
            target = dest / f.name
            n = 1
            while target.exists():
                target = dest / f"{f.stem} ({n}){f.suffix}"
                n += 1
            shutil.move(str(f), target)
            moved += 1
        except (OSError, subprocess.SubprocessError):
            continue
    store.kv_set("sort_last", str(time.time()))
    return f"Sorted {moved} files into folders" + (f" and moved {dupes} duplicate(s) to the Trash" if dupes else "") + "."


def sort_auto_tick() -> str | None:
    """Daily, when the user turned auto-sorting on."""
    if store.kv_get("sort_auto") != "1" or time.time() - float(store.kv_get("sort_last") or 0) < 86400:
        return None
    return sort_run()


# ---------------------------------------------------------------- backup
EXCLUDE = ["venv/", ".venv/", "env/", "node_modules/", "__pycache__/", ".cache/", "*.pyc", ".ipynb_checkpoints/",
           "wandb/", ".mypy_cache/", ".pytest_cache/"]


def backup_conf() -> dict:
    return json.loads(store.kv_get("backup_conf") or "{}")


def backup_set(sources: list[str], target: str) -> str:
    from jarvis.tools.interactive import _proc
    try:
        srcs = [str(_proc.resolve_dir(s)) for s in sources if s.strip()]
    except _proc.ProcError as e:
        return f"error: {e}"
    if not srcs:
        return "error: which folders should I back up?"
    tgt = Path(target).expanduser()
    if any(tgt.resolve() == Path(s) or Path(s) in tgt.resolve().parents for s in srcs):
        return "error: the backup can't be inside the folder it backs up"
    if not tgt.exists():
        return f"error: the backup place {tgt} doesn't exist (plug in the drive, or make the folder first)"
    store.kv_set("backup_conf", json.dumps({"sources": srcs, "target": str(tgt)}))
    return f"Backup set: {', '.join(Path(s).name for s in srcs)} -> {tgt} (every {config.BACKUP_EVERY_DAYS} days and " \
           f"whenever that drive is plugged in). Say 'back up now' to run it."


def backup_run() -> str:
    conf = backup_conf()
    if not conf:
        return "No backup set up yet: tell me which folders and where (an external drive or another disk)."
    tgt = Path(conf["target"])
    if not tgt.exists():
        return f"The backup drive isn't plugged in ({tgt})."
    base = ["rsync", "-a", "--partial", *[f"--exclude={e}" for e in EXCLUDE]]
    copied, failed = 0, []
    for src in conf["sources"]:
        dest = tgt / Path(src).name
        cp = subprocess.run([*base, "--stats", f"{src}/", f"{dest}/"], capture_output=True, text=True, timeout=6 * 3600)
        if cp.returncode not in (0, 24):  # 24 = files vanished while copying (fine)
            failed.append(f"{Path(src).name}: {cp.stderr.strip()[-120:]}")
            continue
        m = re.search(r"Number of regular files transferred: ([\d,]+)", cp.stdout)
        copied += int(m.group(1).replace(",", "")) if m else 0
        check = subprocess.run([*base, "-n", "--itemize-changes", f"{src}/", f"{dest}/"], capture_output=True,
                               text=True, timeout=3600)
        if [ln for ln in check.stdout.splitlines() if ln.startswith(">f")]:
            failed.append(f"{Path(src).name}: not everything was copied (check the drive's free space)")
    store.kv_set("backup_last", str(time.time()))
    msg = f"Backup done: {copied} file(s) copied to {tgt}" + ("; verified" if not failed else "") + "."
    if failed:
        msg += " Problems: " + "; ".join(failed)
    notify.notify("Backup finished" if not failed else "Backup had problems", msg,
                  level="info" if not failed else "warning", source="backup", telegram=True)
    return msg


def backup_tick() -> str | None:
    """Worker: run when it's due, or when the backup drive has just appeared."""
    conf = backup_conf()
    if not conf:
        return None
    present = Path(conf["target"]).exists()
    was = store.kv_get("backup_present") == "1"
    store.kv_set("backup_present", "1" if present else "0")
    due = time.time() - float(store.kv_get("backup_last") or 0) >= config.BACKUP_EVERY_DAYS * 86400
    if present and (due or (not was and time.time() - float(store.kv_get("backup_last") or 0) > 3600)):
        return backup_run()
    return None


def backup_status() -> str:
    conf = backup_conf()
    if not conf:
        return "No backup set up yet."
    last = float(store.kv_get("backup_last") or 0)
    when = datetime.fromtimestamp(last).strftime("%d %b %H:%M") if last else "never"
    return f"Backup of {', '.join(Path(s).name for s in conf['sources'])} to {conf['target']}; last run {when}" + \
        ("" if Path(conf["target"]).exists() else " (drive not plugged in now)") + "."


def removable_drives() -> list[str]:
    base = Path("/media") / os.environ.get("USER", "")
    return [str(p) for p in base.iterdir() if p.is_dir()] if base.is_dir() else []
