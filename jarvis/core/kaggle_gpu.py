"""Train on Kaggle's free GPU from the laptop: "train this on GPU" -> push, watch, download the results. 0 tokens.

  setup:  the official `kaggle` CLI lives in its own small venv (data/kaggle_venv), so its dependencies never touch
          KURAMA's. Credentials: ~/.kaggle/kaggle.json, or KAGGLE_USERNAME + KAGGLE_KEY (or KAGGLE_API_TOKEN) in .env.
  run:    a .py / .ipynb file, or a project folder (main script = train.py / main.py / the only script). The other
          files in the folder go up as a private Kaggle dataset; a first step copies them into /kaggle/working and
          cd's there, so relative paths in the code keep working and everything the code saves is downloaded later.
          requirements.txt is pip-installed first. The kernel is private, GPU (and internet) on.
  watch:  the scheduler worker calls tick() every ~60 s: when a run finishes, its output files are downloaded to
          data/outputs/kaggle/<run>/ and a desktop + Telegram alert says where; a failure sends the log's tail.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from jarvis.core import config, notify, store

log = logging.getLogger(__name__)
_RUNS = "kaggle_runs"
_SKIP = {".git", "venv", ".venv", "__pycache__", "node_modules", ".ipynb_checkpoints", ".idea", ".vscode"}
_POLL_S = 60
MAX_DATA_MB = 2000


class KaggleError(Exception):
    pass


def venv_dir() -> Path:
    return Path(config.DATA_DIR) / "kaggle_venv"


def cli() -> Path:
    return venv_dir() / "bin" / "kaggle"


def _env() -> dict:
    env = dict(os.environ)
    for k in ("KAGGLE_USERNAME", "KAGGLE_KEY", "KAGGLE_API_TOKEN"):
        if v := os.getenv(k) or _dotenv().get(k):
            env[k] = v
    return env


def _dotenv() -> dict:
    try:
        from dotenv import dotenv_values
        return {k: v for k, v in dotenv_values(Path(config.ROOT) / ".env").items() if v}
    except Exception:  # noqa: BLE001
        return {}


def has_credentials() -> bool:
    e = _env()
    return (Path.home() / ".kaggle" / "kaggle.json").exists() or bool(e.get("KAGGLE_API_TOKEN")) or \
        bool(e.get("KAGGLE_USERNAME") and e.get("KAGGLE_KEY"))


SETUP_HELP = ("Kaggle needs a one-time key: on kaggle.com go to Settings -> API -> 'Create New Token', then put "
              "the downloaded kaggle.json in ~/.kaggle/ (or KAGGLE_USERNAME and KAGGLE_KEY in KURAMA's .env). For "
              "GPU and internet the Kaggle account must be phone-verified.")


def username() -> str:
    e = _env()
    if e.get("KAGGLE_USERNAME"):
        return e["KAGGLE_USERNAME"]
    try:
        return json.loads((Path.home() / ".kaggle" / "kaggle.json").read_text())["username"]
    except (OSError, ValueError, KeyError):
        pass
    out = kaggle(["config", "view"], check=False)
    m = re.search(r"username:\s*(\S+)", out)
    if not m:
        raise KaggleError("couldn't find your Kaggle username. " + SETUP_HELP)
    return m.group(1)


def kaggle(args: list[str], check: bool = True, timeout: float = 600) -> str:
    if not cli().exists():
        raise KaggleError("the Kaggle tool isn't set up yet; say 'set up kaggle'")
    r = subprocess.run([str(cli()), *args], capture_output=True, text=True, timeout=timeout, env=_env())
    out = (r.stdout or "") + (r.stderr or "")
    if check and r.returncode != 0:
        raise KaggleError(out.strip().splitlines()[-1][:300] if out.strip() else f"kaggle {args[0]} failed")
    return out


def setup() -> str:
    """Create the private venv and install the Kaggle CLI (one time, ~40 MB)."""
    if cli().exists():
        return "The Kaggle tool is already set up." + ("" if has_credentials() else " " + SETUP_HELP)
    vd = venv_dir()
    subprocess.run([sys.executable, "-m", "venv", str(vd)], check=True, timeout=120)
    r = subprocess.run([str(vd / "bin" / "pip"), "install", "-q", "kaggle"], capture_output=True, text=True,
                       timeout=900)
    if r.returncode != 0:
        raise KaggleError("installing the Kaggle tool failed: " + (r.stderr or r.stdout).strip()[-200:])
    return "The Kaggle tool is installed." + ("" if has_credentials() else " " + SETUP_HELP)


def slug_for(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "run"
    return f"kurama-{base}-{time.strftime('%m%d%H%M')}"


def main_script(folder: Path) -> Path:
    for n in ("train.py", "main.py", "train.ipynb", "main.ipynb"):
        if (folder / n).is_file():
            return folder / n
    scripts = [p for p in folder.iterdir() if p.suffix in (".py", ".ipynb") and p.is_file()]
    if len(scripts) == 1:
        return scripts[0]
    raise KaggleError("which script should run? Name it (e.g. 'train train.py on GPU') or call it train.py")


def _prelude(dataset_slug: str | None, has_reqs: bool) -> str:
    lines = ["# --- added by KURAMA: make the uploaded files usable at their relative paths ---",
             "import os, shutil, subprocess, sys"]
    if dataset_slug:
        lines += [f"_src = '/kaggle/input/{dataset_slug}'",
                  "if os.path.isdir(_src):",
                  "    shutil.copytree(_src, '/kaggle/working', dirs_exist_ok=True)"]
    lines.append("os.chdir('/kaggle/working')")
    if has_reqs:
        lines.append("subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '-r', 'requirements.txt'])")
    lines.append("# --- end of KURAMA setup ---\n")
    return "\n".join(lines)


def _with_prelude(script: Path, prelude: str, out: Path) -> None:
    if script.suffix == ".ipynb":
        nb = json.loads(script.read_text())
        nb.setdefault("cells", []).insert(0, {"cell_type": "code", "metadata": {}, "execution_count": None,
                                              "outputs": [], "source": prelude.splitlines(keepends=True)})
        out.write_text(json.dumps(nb))
    else:
        out.write_text(prelude + "\n" + script.read_text())


def _data_files(folder: Path, script: Path) -> list[Path]:
    files, total = [], 0
    for dp, dns, fns in os.walk(folder):
        dns[:] = [d for d in dns if d not in _SKIP and not d.startswith(".")]
        for f in fns:
            p = Path(dp) / f
            if p == script or f.startswith("."):
                continue
            total += p.stat().st_size
            files.append(p)
    if total > MAX_DATA_MB * 1024 * 1024:
        raise KaggleError(f"the folder is {total // 1048576} MB; more than {MAX_DATA_MB} MB is too slow to upload")
    return files


def run(path: Path, gpu: bool = True) -> str:
    if not cli().exists():
        setup()
    if not has_credentials():
        raise KaggleError(SETUP_HELP)
    path = path.resolve()
    folder, script = (path, main_script(path)) if path.is_dir() else (path.parent, path)
    if script.suffix not in (".py", ".ipynb"):
        raise KaggleError("Kaggle can run a .py script or a .ipynb notebook")
    user = username()
    slug = slug_for(folder.name if path.is_dir() else script.stem)
    work = Path(config.DATA_DIR) / "kaggle" / slug
    kdir = work / "kernel"
    kdir.mkdir(parents=True, exist_ok=True)
    dataset = None
    if path.is_dir() and (files := _data_files(folder, script)):
        dataset = f"{slug}-data"
        ddir = work / "data"
        for f in files:
            dst = ddir / f.relative_to(folder)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
        (ddir / "dataset-metadata.json").write_text(json.dumps(
            {"title": dataset, "id": f"{user}/{dataset}", "licenses": [{"name": "CC0-1.0"}]}))
        kaggle(["datasets", "create", "-p", str(ddir), "--dir-mode", "zip", "-q"], timeout=3600)
    code = kdir / script.name
    _with_prelude(script, _prelude(dataset, path.is_dir() and (folder / "requirements.txt").exists()), code)
    meta = {"id": f"{user}/{slug}", "title": slug, "code_file": script.name, "language": "python",
            "kernel_type": "notebook" if script.suffix == ".ipynb" else "script", "is_private": True,
            "enable_gpu": bool(gpu), "enable_internet": True, "dataset_sources": [f"{user}/{dataset}"] if dataset
            else [], "competition_sources": [], "kernel_sources": []}
    (kdir / "kernel-metadata.json").write_text(json.dumps(meta, indent=1))
    if dataset:
        time.sleep(20)  # a new dataset needs a moment before a kernel can attach it
    kaggle(["kernels", "push", "-p", str(kdir)], timeout=600)
    runs = _runs()
    runs.append({"ref": f"{user}/{slug}", "slug": slug, "started": time.time(), "state": "queued", "checked": 0,
                 "script": str(script)})
    _save(runs)
    return (f"Sent {script.name} to Kaggle's free {'GPU' if gpu else 'CPU'} as {slug}. I'll download the results "
            f"and tell you when it finishes. Watch it live: https://www.kaggle.com/code/{user}/{slug}")


def _runs() -> list[dict]:
    try:
        return json.loads(store.kv_get(_RUNS) or "[]")
    except (ValueError, TypeError):
        return []


def _save(runs: list[dict]) -> None:
    store.kv_set(_RUNS, json.dumps(runs[-20:]))


def state_of(ref: str) -> str:
    out = kaggle(["kernels", "status", ref], check=False, timeout=60)
    m = re.search(r'status\s+"?(?:KernelWorkerStatus\.)?(\w+)', out, re.I)
    return (m.group(1) if m else "unknown").lower()


def fetch(run_: dict) -> Path:
    out = Path(config.DATA_DIR) / "outputs" / "kaggle" / run_["slug"]
    out.mkdir(parents=True, exist_ok=True)
    kaggle(["kernels", "output", run_["ref"], "-p", str(out)], timeout=3600)
    return out


def tick(now: float | None = None) -> None:
    """Scheduler hook: check active runs every _POLL_S; download + notify when they end."""
    now = now or time.time()
    runs, changed = _runs(), False
    for r in runs:
        if r["state"] in ("complete", "error", "cancelled", "failed") or now - r.get("checked", 0) < _POLL_S:
            continue
        r["checked"], changed = now, True
        try:
            st = state_of(r["ref"])
        except KaggleError as e:
            log.warning("kaggle status failed: %s", e)
            continue
        if st in ("complete", "error", "cancelacknowledged", "cancelrequested", "failed"):
            r["state"] = "complete" if st == "complete" else "error"
            mins = int((now - r["started"]) // 60)
            try:
                out = fetch(r)
                files = [p.name for p in out.iterdir()][:6]
            except KaggleError as e:
                out, files = None, [f"(download failed: {e})"]
            if r["state"] == "complete":
                notify.notify(f"Kaggle run finished: {r['slug']}", f"{mins} min. Results in {out}: "
                              f"{', '.join(files)}", level="info", source="kaggle", telegram=True)
            else:
                tail = ""
                if out and (logs := sorted(out.glob("*.log"))):
                    tail = logs[0].read_text(errors="replace")[-600:]
                notify.notify(f"Kaggle run failed: {r['slug']}", tail or "See the Kaggle page for the error.",
                              level="warning", source="kaggle", telegram=True)
        elif st != r["state"]:
            r["state"] = st
    if changed:
        _save(runs)


def status_text() -> str:
    runs = _runs()
    if not runs:
        return "No Kaggle runs yet. Say 'train <script or folder> on GPU'."
    lines = []
    for r in runs[-5:][::-1]:
        mins = int((time.time() - r["started"]) // 60)
        lines.append(f"{r['slug']}: {r['state']} ({mins} min ago) https://www.kaggle.com/code/{r['ref']}")
    return "Kaggle runs:\n" + "\n".join(lines)
