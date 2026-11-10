"""Find files by what is INSIDE them (plan 11-09 phase 9), offline, 0 tokens: "the PDF about attention I downloaded
last week", "my notes on backpropagation", "the notebook where I trained the CNN".

An SQLite FTS5 index (data/content_index.db) of the text of documents: PDF (pdftotext), Word .docx and PowerPoint
.pptx (their XML, no extra library), Jupyter .ipynb (markdown + code cells), .md / .txt. Roots: Downloads,
Documents, Desktop and the mounted project disks (venvs, node_modules, .git, caches skipped). Only new or changed
files are read again (mtime), at most CONTENT_MAX_MB each, the first CONTENT_MAX_CHARS characters. Refreshed by the
timemachine worker once a day (a few seconds after the first full pass) and on demand when it is older than a day.
Query: words (FTS5 / BM25 ranking) + optional type ("pdf", "notebook") + time ("last week", "yesterday", "this
month") read from the request.
"""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import threading
import time
import zipfile
from pathlib import Path

from jarvis.core import config

DB = config.DATA_DIR / "content_index.db"
TYPES = {".pdf": "pdf", ".docx": "word", ".pptx": "slides", ".ipynb": "notebook", ".md": "notes", ".txt": "text"}
SKIP_DIRS = {"venv", ".venv", "env", "node_modules", ".git", "site-packages", "dist-packages", "__pycache__",
             ".cache", ".ipynb_checkpoints", "kaggle_venv", ".mypy_cache", ".pytest_cache", "build", "dist",
             ".local", ".config", "snap", ".npm", ".cargo", ".rustup", "Trash", ".Trash-1000", "lost+found"}
MAX_MB = 40
MAX_CHARS = 60_000
REFRESH_S = 86400
_lock = threading.Lock()


def roots() -> list[Path]:
    home = Path.home()
    out = [home / d for d in ("Downloads", "Documents", "Desktop")]
    media = Path("/media") / home.name
    if media.is_dir():
        out += [p for p in sorted(media.iterdir()) if p.is_dir() and not p.name.lower().startswith("ventoy")]
    return [p for p in out if p.is_dir()]


def _db() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=10)
    c.execute("create table if not exists files(path text primary key, mtime real, size integer, kind text)")
    c.execute("create virtual table if not exists docs using fts5(path unindexed, name, body, tokenize='porter unicode61')")
    c.execute("create table if not exists meta(k text primary key, v text)")
    return c


def _xml_text(path: Path, prefix: str) -> str:
    out = []
    with zipfile.ZipFile(path) as z:
        for n in sorted(z.namelist()):
            if n.startswith(prefix) and n.endswith(".xml"):
                out.append(re.sub(r"<[^>]+>", " ", z.read(n).decode("utf-8", "replace")))
    return re.sub(r"\s+", " ", " ".join(out))


def extract(path: Path) -> str:
    """The text of one document ('' when it can't be read)."""
    kind = TYPES.get(path.suffix.lower())
    try:
        if kind == "pdf":
            return subprocess.run(["pdftotext", "-l", "60", "-q", str(path), "-"], capture_output=True, text=True,
                                  timeout=40).stdout[:MAX_CHARS]
        if kind == "word":
            return _xml_text(path, "word/document")[:MAX_CHARS]
        if kind == "slides":
            return _xml_text(path, "ppt/slides/slide")[:MAX_CHARS]
        if kind == "notebook":
            nb = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            return "\n".join("".join(c.get("source") or "") for c in nb.get("cells") or [])[:MAX_CHARS]
        if kind in ("notes", "text"):
            return path.read_text(encoding="utf-8", errors="replace")[:MAX_CHARS]
    except Exception:  # noqa: BLE001 - a broken file is skipped, never a crash
        return ""
    return ""


def _walk(root: Path):
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = list(d.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.is_symlink():
                continue
            if p.is_dir():
                if p.name not in SKIP_DIRS and not p.name.startswith("."):
                    stack.append(p)
            elif p.suffix.lower() in TYPES:
                yield p


def refresh(budget_s: float = 600.0, progress=lambda _: None) -> dict:
    """Index new / changed documents and drop deleted ones. Returns counts."""
    with _lock:
        c = _db()
        known = {r[0]: (r[1], r[2]) for r in c.execute("select path, mtime, size from files")}
        seen, added, t0 = set(), 0, time.monotonic()
        for root in roots():
            for p in _walk(root):
                sp = str(p)
                seen.add(sp)
                try:
                    st = p.stat()
                except OSError:
                    continue
                if st.st_size > MAX_MB * 1e6 or known.get(sp) == (st.st_mtime, st.st_size):
                    continue
                if time.monotonic() - t0 > budget_s:
                    break
                body = extract(p)
                c.execute("delete from docs where path = ?", (sp,))
                c.execute("insert into docs(path, name, body) values (?, ?, ?)", (sp, p.stem.replace("_", " "), body))
                c.execute("insert or replace into files values (?, ?, ?, ?)",
                          (sp, st.st_mtime, st.st_size, TYPES[p.suffix.lower()]))
                added += 1
                if added % 25 == 0:
                    c.commit()
                    progress(f"read {added} documents")
        gone = [p for p in known if p not in seen and not Path(p).exists()]
        for p in gone:
            c.execute("delete from docs where path = ?", (p,))
            c.execute("delete from files where path = ?", (p,))
        c.execute("insert or replace into meta values ('refreshed', ?)", (str(time.time()),))
        c.commit()
        total = c.execute("select count(*) from files").fetchone()[0]
        c.close()
    return {"added": added, "removed": len(gone), "total": total}


def refreshed_at() -> float:
    try:
        c = _db()
        r = c.execute("select v from meta where k = 'refreshed'").fetchone()
        c.close()
        return float(r[0]) if r else 0.0
    except sqlite3.Error:
        return 0.0


def tick() -> str | None:
    """The timemachine worker: once a day."""
    if time.time() - refreshed_at() < REFRESH_S:
        return None
    r = refresh(budget_s=300)
    return f"content index: +{r['added']} -{r['removed']} ({r['total']} documents)"


_KIND_WORDS = {"pdf": "pdf", "pdfs": "pdf", "word": "word", "docx": "word", "doc": "word", "slides": "slides",
               "pptx": "slides", "presentation": "slides", "ppt": "slides", "notebook": "notebook",
               "notebooks": "notebook", "ipynb": "notebook", "jupyter": "notebook", "markdown": "notes", "md": "notes",
               "txt": "text"}  # ('my notes on X' = any document, not only .md files)
_TIME = [(r"\btoday\b", 1), (r"\byesterday\b", 2), (r"\b(?:this|last|past)\s+week\b", 8),
         (r"\b(?:this|last|past)\s+month\b", 32), (r"\b(?:few|couple of)\s+days\b", 5), (r"\bthis\s+year\b", 366)]
_STOP = set("the a an my i me find show where is was that which about on of for in to from with file files document "
            "documents downloaded download saved wrote made opened last this week month year today yesterday past "
            "few days couple and or it any some".split()) | set(_KIND_WORDS)


def parse(query: str) -> tuple[str, str, float]:
    """(FTS words, kind or '', newer-than unix time or 0) from a request in plain words."""
    q = (query or "").lower()
    kind = next((_KIND_WORDS[w] for w in re.findall(r"[a-z]+", q) if w in _KIND_WORDS), "")
    since = next((time.time() - days * 86400 for pat, days in _TIME if re.search(pat, q)), 0.0)
    words = [w for w in re.findall(r"[a-z0-9]+", q) if w not in _STOP and len(w) > 1]
    return " OR ".join(f'"{w}"' for w in words[:8]), kind, since


def search(query: str, limit: int = 8) -> list[dict]:
    """Best matches: [{path, kind, mtime, snippet}]."""
    fts, kind, since = parse(query)
    if not fts:
        return []
    if time.time() - refreshed_at() > REFRESH_S:  # never indexed / older than a day: a quick pass first
        refresh(budget_s=120)
    c = _db()
    sql = ("select d.path, f.kind, f.mtime, snippet(docs, 2, '«', '»', ' … ', 12), bm25(docs, 0, 4.0, 1.0) as s "
           "from docs d join files f on f.path = d.path where docs match ?"
           + (" and f.kind = ?" if kind else "") + (" and f.mtime >= ?" if since else "") + " order by s limit ?")
    args: list = [fts] + ([kind] if kind else []) + ([since] if since else []) + [limit]
    args[-1] = limit * 4  # (copies of the same file are shown once)
    try:
        rows = c.execute(sql, args).fetchall()
        sizes = dict(c.execute("select path, size from files where path in (%s)" % ",".join("?" * len(rows)),
                               [r[0] for r in rows]).fetchall()) if rows else {}
    except sqlite3.Error:
        rows, sizes = [], {}
    c.close()
    out, seen = [], set()
    for r in rows:
        key = (Path(r[0]).name.lower(), sizes.get(r[0]))
        if key in seen:
            continue
        seen.add(key)
        out.append({"path": r[0], "kind": r[1], "mtime": r[2], "snippet": re.sub(r"\s+", " ", r[3] or "")[:200]})
    return out[:limit]


def answer(query: str):
    hits = search(query)
    if not hits:
        fts, kind, since = parse(query)
        what = (f" {kind}" if kind else "") + (" from that time" if since else "")
        return (f"I found no{what} document with those words inside. (I read PDFs, Word, PowerPoint, notebooks and "
                f"notes in Downloads, Documents, Desktop and your project disks.)")
    lines = [f"📄 Found by what's inside ({len(hits)}):"]
    for i, h in enumerate(hits, 1):
        when = time.strftime("%d %b", time.localtime(h["mtime"]))
        lines.append(f"{i}. {Path(h['path']).name} ({h['kind']}, {when}) — {h['path']}\n   “{h['snippet']}”")
    lines.append("Say 'open 1' or 'send 1 to telegram'.")
    from jarvis.core.results import Reply
    return Reply("\n".join(lines), paths=[h["path"] for h in hits])  # numbered: 'open 2' picks the exact path
