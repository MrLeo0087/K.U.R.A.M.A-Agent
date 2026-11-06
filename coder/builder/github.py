"""A starter project from GitHub (only when the owner asks: "from GitHub", "use a template"). Checked before use:
an open licence (MIT, Apache, BSD, ISC, Unlicense), small (< 5 MB), not archived, some stars; after download no
secrets, no PyTorch / TensorFlow (no GPU here), no paths outside the folder. 0 tokens."""
from __future__ import annotations

import io
import re
import tarfile

from coder.core import safety, settings
from coder.core.run import Run

OPEN = {"mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "isc", "unlicense", "0bsd"}
HEAVY = re.compile(r"\b(?:torch|tensorflow|tensorflow-gpu|jax|cuda|nvidia-[\w-]+)\b", re.I)
MAX_KB = 5000


def query(run: Run) -> str:
    from coder.builder.understand import slug
    words = slug(run.request).replace("-", " ")
    stack = {"react": "react vite", "web": "html css javascript", "pygame": "pygame", "fastapi": "fastapi",
             "flask": "flask", "next": "nextjs", "node": "node express"}.get(run.stack, run.stack)
    return f"{words} {stack} template".strip()


def search(q: str) -> list[dict]:
    import httpx
    r = httpx.get("https://api.github.com/search/repositories", params={"q": q, "sort": "stars", "per_page": 10},
                  headers={"Accept": "application/vnd.github+json", "User-Agent": "kurama-coder"}, timeout=15)
    r.raise_for_status()
    out = []
    for it in r.json().get("items") or []:
        lic = ((it.get("license") or {}).get("key") or "").lower()
        if lic in OPEN and int(it.get("size") or 0) < MAX_KB and not it.get("archived") and int(it.get("stargazers_count") or 0) >= 10:
            out.append(it)
    return out


def fetch(it: dict, dest) -> str:
    """Download and unpack the repository into dest (the run's staging folder), checked. '' or why refused."""
    import httpx
    url = f"https://codeload.github.com/{it['full_name']}/tar.gz/{it.get('default_branch') or 'main'}"
    r = httpx.get(url, timeout=60, follow_redirects=True, headers={"User-Agent": "kurama-coder"})
    r.raise_for_status()
    if len(r.content) > MAX_KB * 1024 * 2:
        return "too big"
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz") as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            parts = m.name.split("/")[1:]  # drop "<repo>-<branch>/"
            if not parts or any(p in ("..", "") or p in settings.SKIP_DIRS for p in parts) or m.name.startswith("/"):
                continue
            f = tf.extractfile(m)
            if f is not None:
                files["/".join(parts)] = f.read()
    for rel, data in files.items():
        txt = data[:200_000].decode("utf-8", errors="ignore")
        if safety.SECRET.search(txt):
            return f"it holds a secret-looking value ({rel})"
        if re.search(r"(?:^|/)(?:requirements[^/]*\.txt|package\.json|pyproject\.toml|environment\.yml)$", rel) and HEAVY.search(txt):
            return f"it needs GPU / deep-learning packages ({rel})"
    dest.mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return ""


def staging(run: Run):
    return run.dir / "starter"


def starter(run: Run) -> str:
    """At plan time: the best checked starter, downloaded into the run's staging folder (copied into the project
    only after the owner's yes). '' when none fits (the agent then writes everything itself)."""
    try:
        for it in search(query(run))[:3]:
            why = fetch(it, staging(run))
            if not why:
                lic = (it.get("license") or {}).get("spdx_id", "")
                run.scaffold = f"github:{it['full_name']} ({lic}, {it.get('stargazers_count')} stars)"
                return f"Starts from GitHub: {it['full_name']} ({it.get('stargazers_count')} stars, {lic} licence)."
            run.note(f"github {it['full_name']} refused: {why}")
    except Exception as e:  # noqa: BLE001 - no network / rate limit: write it ourselves
        run.note(f"github search failed: {e}")
    return ""


def copy_in(run: Run) -> int:
    """The staged starter into the project (each file backed up / listed for undo)."""
    src = staging(run)
    n = 0
    for f in sorted(src.rglob("*")) if src.exists() else []:
        if f.is_file():
            p = run.root / f.relative_to(src)
            safety.before_write(run, p)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(f.read_bytes())
            n += 1
    return n
