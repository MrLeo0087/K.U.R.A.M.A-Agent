"""Semantic memory (P7): hybrid RAG over the user's code and notes.

Storage is one SQLite file (config.MEMORY_DB_PATH): `files` (path, mtime, size, sha1), `chunks`
(path + line range + text), `chunks_fts` (FTS5, BM25) and `vectors` (float32 blobs). Search fuses
BM25 and brute-force numpy cosine with reciprocal rank fusion. Why not FAISS: at <= ~50k chunks x
384 dims a single matrix-vector product takes a few ms and ~75 MB at the very top end, FAISS adds a
native dependency and a second store to keep in sync, and SQLite already gives us FTS5,
incremental updates and deletes for free.

Embeddings come from fastembed (ONNX Runtime, no torch) and are loaded lazily on the first
index/search call; the model and the cached vector matrix are dropped after
config.EMBED_IDLE_UNLOAD_S idle seconds. By default (config.EMBED_IN_SUBPROCESS) the model lives in a
child process (`python -m jarvis.core.memory _worker`), so unloading frees everything, including
the ~80 MB of onnxruntime/fastembed imports that a `del` cannot release in-process. If the model cannot load (offline) search is BM25-only
and missing vectors are filled in on the next index pass.

    python -m jarvis.core.memory index [path ...]   # default: config.MEMORY_ROOTS
    python -m jarvis.core.memory search "query"
    python -m jarvis.core.memory ask "question"
    python -m jarvis.core.memory stats
"""
from __future__ import annotations

import ast
import gc
import hashlib
import json
import logging
import os
import pickle
import re
import sqlite3
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from jarvis.core import config

log = logging.getLogger("jarvis.memory")


# --------------------------------------------------------------------------- embedding model
def _load_fastembed() -> Any:
    from fastembed import TextEmbedding  # lazy: ~onnxruntime + tokenizers only when needed

    Path(config.EMBED_CACHE_DIR).mkdir(parents=True, exist_ok=True)
    # The CPU memory arena keeps the peak activation size forever; off = lower RSS, same speed.
    return TextEmbedding(model_name=config.EMBED_MODEL, cache_dir=str(config.EMBED_CACHE_DIR),
                         threads=config.EMBED_THREADS, enable_cpu_mem_arena=False)


def _malloc_trim() -> None:
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)  # hand freed heap back to the OS (glibc)
    except Exception:
        pass


class ProcessModel:
    """Embedding model in a child process; close() ends it and frees all of its memory.
    Protocol on the child's stdin/stdout: pickled (texts, query) -> ("ok", ndarray) | ("err", str)."""

    def __init__(self, timeout_s: float = 600.0):
        self.proc = subprocess.Popen([sys.executable, "-m", "jarvis.core.memory", "_worker"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     cwd=str(config.ROOT))
        self._lock = threading.Lock()
        status, info = self._recv()  # ("ready", rss) once the model is loaded (may download first)
        if status != "ready":
            self.close()
            raise RuntimeError(f"embedding worker failed to start: {info}")
        self.child_rss_mb = info

    def _recv(self) -> tuple[str, Any]:
        try:
            return pickle.load(self.proc.stdout)  # type: ignore[arg-type]
        except EOFError:
            return "err", f"worker exited ({self.proc.poll()})"

    def _call(self, texts: list[str], query: bool) -> Any:
        with self._lock:
            pickle.dump((list(texts), query), self.proc.stdin)  # type: ignore[arg-type]
            self.proc.stdin.flush()  # type: ignore[union-attr]
            status, out = self._recv()
        if status != "ok":
            raise RuntimeError(f"embedding failed: {out}")
        return out

    def passage_embed(self, texts: list[str]) -> Any:
        return self._call(texts, False)

    def query_embed(self, texts: list[str]) -> Any:
        return self._call(texts, True)

    embed = passage_embed

    def close(self) -> None:
        try:
            if self.proc.poll() is None:
                self.proc.stdin.close()  # type: ignore[union-attr]
                self.proc.wait(timeout=3)
        except Exception:
            pass
        if self.proc.poll() is None:
            self.proc.kill()


def _worker_loop() -> None:
    """Child side of ProcessModel."""
    out = sys.stdout.buffer
    sys.stdout = sys.stderr  # stray prints must never corrupt the pickle stream
    import numpy as np
    import psutil

    try:
        model = _load_fastembed()
    except Exception as e:
        pickle.dump(("err", f"{type(e).__name__}: {e}"), out)
        out.flush()
        return
    pickle.dump(("ready", round(psutil.Process().memory_info().rss / 1e6)), out)
    out.flush()
    while True:
        try:
            texts, query = pickle.load(sys.stdin.buffer)
        except (EOFError, pickle.UnpicklingError):
            return
        try:
            fn = model.query_embed if query else model.passage_embed
            vecs = np.asarray(list(fn(texts, batch_size=max(1, config.EMBED_BATCH))), dtype=np.float32)
            pickle.dump(("ok", vecs), out)
        except Exception as e:
            pickle.dump(("err", f"{type(e).__name__}: {e}"), out)
        out.flush()


def _fastembed_factory() -> Any:
    return ProcessModel() if config.EMBED_IN_SUBPROCESS else _load_fastembed()


class Embedder:
    """Lazy embedding model with idle unload (del + gc)."""

    def __init__(self, factory: Callable[[], Any] | None = None, idle_s: float | None = None):
        self._factory = factory or _fastembed_factory
        self.idle_s = idle_s
        self._model: Any = None
        self._lock = threading.RLock()
        self._timer: threading.Timer | None = None
        self.last_used = 0.0
        self.loads = 0
        self.unload_hooks: list[Callable[[], None]] = []

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _idle(self) -> float:
        return float(config.EMBED_IDLE_UNLOAD_S if self.idle_s is None else self.idle_s)

    def _arm(self) -> None:
        idle = self._idle()
        if idle <= 0:
            return
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(idle, self._idle_check)
        self._timer.daemon = True
        self._timer.start()

    def _idle_check(self) -> None:
        with self._lock:
            if self._model is not None and time.monotonic() - self.last_used >= self._idle() - 0.05:
                log.info("embedding model idle for %.0f s: unloading", self._idle())
                self.unload()

    def unload(self) -> None:
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            had = self._model is not None
            if had and hasattr(self._model, "close"):
                try:
                    self._model.close()
                except Exception as e:
                    log.debug("model close failed: %s", e)
            self._model = None
            for hook in self.unload_hooks:
                try:
                    hook()
                except Exception as e:
                    log.debug("unload hook failed: %s", e)
        if had:
            gc.collect()
            _malloc_trim()

    def embed(self, texts: list[str], query: bool = False) -> Any:
        """L2-normalized float32 matrix (len(texts) x dim)."""
        import numpy as np

        with self._lock:  # held while embedding so an idle unload cannot happen mid-call
            if self._model is None:
                t0 = time.monotonic()
                self._model = self._factory()
                self.loads += 1
                log.info("embedding model %s loaded in %.1f s", config.EMBED_MODEL, time.monotonic() - t0)
            m = self._model
            fn = getattr(m, "query_embed" if query else "passage_embed", None) or m.embed
            vecs = np.asarray(list(fn(list(texts))), dtype=np.float32)
            self.last_used = time.monotonic()
            self._arm()
        if vecs.ndim == 1:
            vecs = vecs.reshape(1, -1)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vecs / norms


# --------------------------------------------------------------------------- chunking
@dataclass
class Chunk:
    start: int  # 1-based first line
    end: int  # 1-based last line (inclusive)
    text: str


def chunk_lines(lines: list[str], start: int = 1, size: int | None = None,
                overlap: int | None = None) -> list[Chunk]:
    """~size-char chunks on line boundaries; consecutive chunks share ~overlap chars of lines."""
    size = size or config.CHUNK_CHARS
    overlap = config.CHUNK_OVERLAP if overlap is None else overlap
    out: list[Chunk] = []
    i, n = 0, len(lines)
    while i < n:
        j, total = i, 0
        while j < n and (j == i or total + len(lines[j]) + 1 <= size):
            total += len(lines[j]) + 1
            j += 1
        text = "\n".join(lines[i:j])
        if j == i + 1 and len(text) > size:  # one over-long line (minified JSON...): hard split
            step = max(1, size - overlap)
            out += [Chunk(start + i, start + i, text[p:p + size]) for p in range(0, len(text), step)
                    if text[p:p + size].strip()]
        elif text.strip():
            out.append(Chunk(start + i, start + j - 1, text))
        if j >= n:
            break
        k, back = j, 0
        while k - 1 > i and back + len(lines[k - 1]) + 1 <= overlap:
            k -= 1
            back += len(lines[k]) + 1
        i = k
    return out


def _node_start(node: ast.AST, lines: list[str], floor: int) -> int:
    s = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])  # type: ignore[attr-defined]
    while s - 1 > floor and lines[s - 2].lstrip().startswith("#"):  # comments above a def belong to it
        s -= 1
    return s


def _segments(nodes: list[ast.stmt], lines: list[str], lo: int, hi: int) -> list[tuple[int, int, ast.stmt | None]]:
    """Split lines lo..hi (1-based, inclusive) at each node's start."""
    starts: list[tuple[int, ast.stmt]] = []
    floor = lo
    for nd in nodes:
        s = max(_node_start(nd, lines, floor), lo)
        if starts and s <= starts[-1][0]:
            continue
        starts.append((s, nd))
        floor = getattr(nd, "end_lineno", s) or s
    if not starts:
        return [(lo, hi, None)]
    segs: list[tuple[int, int, ast.stmt | None]] = []
    if starts[0][0] > lo:
        segs.append((lo, starts[0][0] - 1, None))
    for idx, (s, nd) in enumerate(starts):
        e = starts[idx + 1][0] - 1 if idx + 1 < len(starts) else hi
        segs.append((s, e, nd))
    return segs


def chunk_python(text: str, size: int | None = None) -> list[Chunk]:
    """Chunks that start at top-level def/class boundaries (big classes split at methods); small
    neighbours are merged up to ~size chars; anything still too big falls back to chunk_lines."""
    size = size or config.CHUNK_CHARS
    lines = text.splitlines()
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return chunk_lines(lines, size=size)
    if not lines:
        return []

    def seg_len(s: int, e: int) -> int:
        return sum(len(x) + 1 for x in lines[s - 1:e])

    def explode(s: int, e: int, nd: ast.stmt | None) -> list[tuple[int, int]]:
        if seg_len(s, e) <= size * 1.25:
            return [(s, e)]
        if isinstance(nd, ast.ClassDef) and nd.body:
            out: list[tuple[int, int]] = []
            for cs, ce, cn in _segments(nd.body, lines, s, e):
                out += explode(cs, ce, cn if isinstance(cn, ast.ClassDef) else None) \
                    if seg_len(cs, ce) > size * 1.25 and isinstance(cn, ast.ClassDef) else [(cs, ce)]
            return out
        return [(s, e)]

    pieces: list[tuple[int, int]] = []
    for s, e, nd in _segments(tree.body, lines, 1, len(lines)):
        pieces += explode(s, e, nd)
    out: list[Chunk] = []
    cur: tuple[int, int] | None = None

    def flush() -> None:
        if cur:
            body = "\n".join(lines[cur[0] - 1:cur[1]])
            if body.strip():
                out.append(Chunk(cur[0], cur[1], body))

    for s, e in pieces:
        n = seg_len(s, e)
        if n > size * 1.25:
            flush()
            cur = None
            out += chunk_lines(lines[s - 1:e], start=s, size=size)
            continue
        if cur and seg_len(cur[0], cur[1]) + n <= size:
            cur = (cur[0], e)
        else:
            flush()
            cur = (s, e)
    flush()
    return out


def notebook_text(raw: str) -> str:
    """Markdown + code cell sources of a .ipynb (outputs dropped), with cell markers."""
    nb = json.loads(raw)
    parts = []
    for i, cell in enumerate(nb.get("cells") or [], 1):
        if cell.get("cell_type") not in ("markdown", "code"):
            continue
        src = cell.get("source") or ""
        src = "".join(src) if isinstance(src, list) else str(src)
        if src.strip():
            parts.append(f"# [cell {i} {cell['cell_type']}]\n{src.rstrip()}")
    return "\n\n".join(parts)


def chunk_file(path: Path, text: str) -> list[Chunk]:
    ext = path.suffix.lower()
    if ext == ".py":
        return chunk_python(text)
    if ext == ".ipynb":
        try:
            text = notebook_text(text)
        except (ValueError, TypeError, AttributeError):
            return []
    return chunk_lines(text.splitlines())


def iter_files(root: Path) -> Iterator[Path]:
    """Indexable files under root (sane excludes, size cap, no symlinks, no hidden dirs, no .env)."""
    if root.is_file():
        yield root
        return
    excl = set(config.MEMORY_EXCLUDE_DIRS)
    exts = set(config.MEMORY_EXTS)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in excl
                             and not d.endswith(".egg-info"))
        for fn in sorted(filenames):
            if fn in config.MEMORY_EXCLUDE_FILES or fn.startswith(".env"):
                continue
            if Path(fn).suffix.lower() not in exts:
                continue
            p = Path(dirpath) / fn
            try:
                if p.is_symlink() or p.stat().st_size > config.MEMORY_MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield p


# --------------------------------------------------------------------------- index
_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY, path TEXT UNIQUE, root TEXT, mtime REAL, size INTEGER, hash TEXT,
    chunks INTEGER DEFAULT 0, indexed REAL
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY, file_id INTEGER, path TEXT, start_line INTEGER, end_line INTEGER, text TEXT
);
CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(path, text, content='chunks', content_rowid='id',
    tokenize='porter unicode61');
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, path, text) VALUES (new.id, new.path, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, path, text) VALUES ('delete', old.id, old.path, old.text);
    DELETE FROM vectors WHERE chunk_id = old.id;
END;
CREATE TABLE IF NOT EXISTS vectors (chunk_id INTEGER PRIMARY KEY, vec BLOB);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS answers (
    qnorm TEXT PRIMARY KEY, question TEXT, answer TEXT, created REAL, hits INTEGER DEFAULT 0
);
"""

_STOP = set("""a an and are as at be by can could did do does for from had has have how i if in into is it
its me my of on or our please show tell that the their them then there these this to was we were what
when where which who why will with would you your about find search look give jarvis kurama code project
file files notes note""".split())


def fts_query(text: str) -> str | None:
    words = re.findall(r"[a-z0-9ऀ-ॿ]{2,}", text.lower())
    words = list(dict.fromkeys(w for w in words if w not in _STOP))[:12]
    return " OR ".join(f'"{w}"' for w in words) if words else None


def normalize_question(q: str) -> str:
    q = re.sub(r"[^\w\s]", " ", (q or "").lower())
    words = [w for w in q.split() if w not in ("jarvis", "kurama", "please", "hey")]
    return " ".join(words)


@dataclass
class Hit:
    id: int
    path: str
    start: int
    end: int
    text: str
    score: float = 0.0
    sources: list[str] = field(default_factory=list)

    @property
    def loc(self) -> str:
        return f"{self.path}:{self.start}-{self.end}"


class Index:
    def __init__(self, db_path: str | Path | None = None, embedder: Embedder | None = None):
        self.path = Path(db_path or config.MEMORY_DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder or Embedder()
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30,
                                    isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(_SCHEMA)
        self._gen = 0  # bumped on every index change

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def _q(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    def vec_dtype(self) -> str:
        """Storage dtype of the vectors: float16 for new indexes (half the disk/IO), float32 legacy."""
        row = self._q("SELECT value FROM meta WHERE key='vec_dtype'")
        if row:
            return row[0][0]
        dt = "float32" if self._q("SELECT 1 FROM vectors LIMIT 1") else "float16"
        self._q("INSERT OR REPLACE INTO meta(key,value) VALUES ('vec_dtype', ?)", (dt,))
        return dt

    # --- display path ---
    @staticmethod
    def display_path(path: Path, root: Path) -> str:
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = path.name
        if root == Path(config.ROOT).resolve():
            return rel or path.name
        return f"{root.name}/{rel}" if rel and rel != "." else path.name

    # --- indexing ---
    def index_path(self, path: str | Path, progress: Callable[[str], None] | None = None,
                   cancel: Callable[[], None] | None = None) -> dict:
        """Incremental (mtime+size, then sha1) index of path; removed files are deleted."""
        t0 = time.monotonic()
        root = Path(path).expanduser().resolve()
        if not root.exists():
            raise FileNotFoundError(f"no such path: {root}")
        base = root.parent if root.is_file() else root
        st = {"files": 0, "indexed": 0, "unchanged": 0, "deleted": 0, "chunks_added": 0, "embedded": 0}
        seen: set[str] = set()
        for f in iter_files(root):
            if cancel:
                cancel()
            key = str(f)
            seen.add(key)
            st["files"] += 1
            try:
                if self._index_file(f, base):
                    st["indexed"] += 1
                else:
                    st["unchanged"] += 1
            except OSError as e:
                log.info("skip %s: %s", f, e)
            if progress and st["files"] % 100 == 0:
                progress(f"{st['files']} files scanned, {st['indexed']} (re)indexed")
        prefix = key_prefix = str(root) if root.is_file() else str(root) + os.sep
        with self._lock:
            rows = self.conn.execute("SELECT id, path FROM files WHERE path = ? OR substr(path, 1, ?) = ?",
                                     (str(root), len(key_prefix), prefix)).fetchall()
            gone = [r["id"] for r in rows if r["path"] not in seen]
            if gone:
                self.conn.execute("BEGIN")
                for fid in gone:
                    self.conn.execute("DELETE FROM chunks WHERE file_id=?", (fid,))
                    self.conn.execute("DELETE FROM files WHERE id=?", (fid,))
                self.conn.execute("COMMIT")
        st["deleted"] = len(gone)
        st["chunks_added"] = self._added
        self._added = 0
        st["embedded"] = self.embed_missing(progress=progress, cancel=cancel)
        if st["indexed"] or st["deleted"]:
            self.clear_answers()
            self._gen += 1
        st["chunks_total"] = self.count_chunks()
        st["seconds"] = round(time.monotonic() - t0, 2)
        log.info("indexed %s: %s", root, st)
        return st

    _added = 0

    def _index_file(self, f: Path, root: Path) -> bool:
        stt = f.stat()
        key = str(f)
        row = self.conn.execute("SELECT id, mtime, size, hash FROM files WHERE path=?", (key,)).fetchone()
        if row and row["mtime"] == stt.st_mtime and row["size"] == stt.st_size:
            return False
        data = f.read_bytes()
        digest = hashlib.sha1(data).hexdigest()
        if row and row["hash"] == digest:
            self._q("UPDATE files SET mtime=?, size=? WHERE id=?", (stt.st_mtime, stt.st_size, row["id"]))
            return False
        if b"\0" in data[:4096]:  # binary
            chunks: list[Chunk] = []
        else:
            chunks = chunk_file(f, data.decode("utf-8", errors="replace"))
        disp = self.display_path(f, root)
        with self._lock:
            c = self.conn
            c.execute("BEGIN")
            try:
                if row:
                    c.execute("DELETE FROM chunks WHERE file_id=?", (row["id"],))
                    c.execute("UPDATE files SET root=?, mtime=?, size=?, hash=?, chunks=?, indexed=? WHERE id=?",
                              (str(root), stt.st_mtime, stt.st_size, digest, len(chunks), time.time(), row["id"]))
                    fid = row["id"]
                else:
                    fid = c.execute("INSERT INTO files(path,root,mtime,size,hash,chunks,indexed) VALUES (?,?,?,?,?,?,?)",
                                    (key, str(root), stt.st_mtime, stt.st_size, digest, len(chunks),
                                     time.time())).lastrowid
                c.executemany("INSERT INTO chunks(file_id,path,start_line,end_line,text) VALUES (?,?,?,?,?)",
                              [(fid, disp, ch.start, ch.end, ch.text) for ch in chunks])
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
        self._added += len(chunks)
        return True

    def embed_missing(self, progress: Callable[[str], None] | None = None,
                      cancel: Callable[[], None] | None = None) -> int:
        """Embed every chunk without a vector (new chunks, a changed model, an earlier failure)."""
        import numpy as np

        model = self._q("SELECT value FROM meta WHERE key='embed_model'")
        if not model or model[0][0] != config.EMBED_MODEL:
            self._q("DELETE FROM vectors")
            self._q("INSERT OR REPLACE INTO meta(key,value) VALUES ('embed_model', ?)", (config.EMBED_MODEL,))
            self._q("INSERT OR REPLACE INTO meta(key,value) VALUES ('vec_dtype', 'float16')")
            self._gen += 1
        dtype = np.dtype(self.vec_dtype())
        todo = [r[0] for r in self._q("SELECT c.id FROM chunks c LEFT JOIN vectors v ON v.chunk_id=c.id "
                                      "WHERE v.chunk_id IS NULL ORDER BY c.id")]
        done = 0
        batch = max(1, int(config.EMBED_BATCH))
        for i in range(0, len(todo), batch):  # texts are read per batch, never all at once
            if cancel:
                cancel()
            ids = todo[i:i + batch]
            part = self._q(f"SELECT id, path, text FROM chunks WHERE id IN ({','.join('?' * len(ids))})", tuple(ids))
            if not part:
                continue
            try:
                vecs = self.embedder.embed([f"{r['path']}\n{r['text']}" for r in part])
            except Exception as e:
                log.warning("embedding failed (search stays BM25-only until the next index): %s", e)
                break
            with self._lock:
                self.conn.execute("BEGIN")
                self.conn.executemany("INSERT OR REPLACE INTO vectors(chunk_id, vec) VALUES (?,?)",
                                      [(r["id"], np.asarray(v, dtype=dtype).tobytes())
                                       for r, v in zip(part, vecs)])
                self.conn.execute("COMMIT")
            done += len(part)
            if progress and (i // batch) % 10 == 9:
                progress(f"embedded {done}/{len(todo)} chunks")
        if done:
            self._gen += 1
        return done

    # --- search ---
    def scan_vectors(self, qv: Any, n: int, block: int = 4096) -> list[int]:
        """Top-n chunk ids by cosine, streaming the vectors from SQLite in blocks (nothing is kept
        in RAM after the call: at most `block` vectors + the running top-n are alive at a time)."""
        import numpy as np

        dtype = np.dtype(self.vec_dtype())
        best_ids = np.empty(0, dtype=np.int64)
        best_sims = np.empty(0, dtype=np.float32)
        with self._lock:
            cur = self.conn.execute("SELECT chunk_id, vec FROM vectors")
            while rows := cur.fetchmany(block):
                ids = np.fromiter((r[0] for r in rows), dtype=np.int64, count=len(rows))
                raw = b"".join(r[1] for r in rows)
                if len(raw) != len(rows) * qv.shape[0] * dtype.itemsize:
                    continue  # dimension mismatch (stale vectors): skip
                mat = np.frombuffer(raw, dtype=dtype).reshape(len(rows), -1)
                sims = (mat @ qv.astype(dtype)).astype(np.float32)
                best_ids = np.concatenate([best_ids, ids])
                best_sims = np.concatenate([best_sims, sims])
                if len(best_sims) > n:
                    keep = np.argpartition(-best_sims, n - 1)[:n]
                    best_ids, best_sims = best_ids[keep], best_sims[keep]
                del mat, raw, sims
        order = np.argsort(-best_sims)
        return [int(i) for i in best_ids[order]]

    def bm25(self, query: str, n: int) -> list[int]:
        q = fts_query(query)
        if not q:
            return []
        try:
            rows = self._q("SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? "
                           "ORDER BY bm25(chunks_fts, 2.0, 1.0) LIMIT ?", (q, n))
        except sqlite3.OperationalError as e:
            log.info("fts query failed: %s", e)
            return []
        return [r[0] for r in rows]

    def vector(self, query: str, n: int) -> list[int]:
        if not self._q("SELECT 1 FROM vectors LIMIT 1"):
            return []
        try:
            qv = self.embedder.embed([query], query=True)[0]
        except Exception as e:
            log.warning("query embedding failed, BM25 only: %s", e)
            return []
        return self.scan_vectors(qv, n)

    def search(self, query: str, k: int | None = None) -> list[Hit]:
        """Hybrid search: BM25 + cosine, merged by reciprocal rank fusion."""
        k = int(k or config.KNOWLEDGE_K)
        n = max(config.SEARCH_CANDIDATES, k)
        scores: dict[int, float] = {}
        sources: dict[int, list[str]] = {}
        for name, ids in (("bm25", self.bm25(query, n)), ("vector", self.vector(query, n))):
            for rank, cid in enumerate(ids):
                scores[cid] = scores.get(cid, 0.0) + 1.0 / (config.RRF_K + rank + 1)
                sources.setdefault(cid, []).append(name)
        best = sorted(scores, key=lambda c: -scores[c])[:k]
        if not best:
            return []
        marks = ",".join("?" * len(best))
        rows = {r["id"]: r for r in self._q(f"SELECT id, path, start_line, end_line, text FROM chunks "
                                            f"WHERE id IN ({marks})", tuple(best))}
        return [Hit(c, rows[c]["path"], rows[c]["start_line"], rows[c]["end_line"], rows[c]["text"],
                    round(scores[c], 5), sources[c]) for c in best if c in rows]

    # --- answer cache ---
    def cached_answer(self, question: str) -> str | None:
        qn = normalize_question(question)
        rows = self._q("SELECT answer FROM answers WHERE qnorm=?", (qn,))
        if rows:
            self._q("UPDATE answers SET hits=hits+1 WHERE qnorm=?", (qn,))
            return rows[0][0]
        return None

    def cache_answer(self, question: str, answer: str) -> None:
        self._q("INSERT OR REPLACE INTO answers(qnorm,question,answer,created,hits) VALUES (?,?,?,?,0)",
                (normalize_question(question), question[:500], answer, time.time()))

    def clear_answers(self) -> None:
        self._q("DELETE FROM answers")

    # --- stats ---
    def count_chunks(self) -> int:
        return int(self._q("SELECT COUNT(*) FROM chunks")[0][0])

    def stats(self) -> dict:
        size = sum(p.stat().st_size for p in self.path.parent.glob(self.path.name + "*") if p.is_file())
        return {"files": int(self._q("SELECT COUNT(*) FROM files")[0][0]), "chunks": self.count_chunks(),
                "vectors": int(self._q("SELECT COUNT(*) FROM vectors")[0][0]),
                "db_mb": round(size / 1e6, 2), "model_loaded": self.embedder.loaded}


# --------------------------------------------------------------------------- module API
_index: Index | None = None
_index_lock = threading.Lock()


def get_index() -> Index:
    global _index
    with _index_lock:
        if _index is None:
            _index = Index()
        return _index


def set_index(index: Index | None) -> None:
    """Swap the module index (tests); closes the previous one."""
    global _index
    with _index_lock:
        if _index is not None and _index is not index:
            _index.embedder.unload()
            _index.close()
        _index = index


def index_path(path: str | Path, progress=None, cancel=None) -> dict:
    return get_index().index_path(path, progress=progress, cancel=cancel)


def index_roots(progress=None, cancel=None) -> dict:
    total: dict[str, Any] = {}
    for root in config.MEMORY_ROOTS:
        if Path(root).exists():
            for k, v in index_path(root, progress, cancel).items():
                total[k] = v if k == "chunks_total" else total.get(k, 0) + v
    return total


def search(query: str, k: int | None = None) -> list[Hit]:
    return get_index().search(query, k)


def format_hits(hits: list[Hit], max_chars: int | None = None, snippet: int | None = None) -> str:
    """'path:a-b: snippet' lines, each snippet <= snippet chars, total <= max_chars."""
    max_chars = max_chars or config.KNOWLEDGE_MAX_CHARS
    snippet = snippet or config.KNOWLEDGE_SNIPPET_CHARS
    if not hits:
        return ""
    heads = [f"{h.loc}: " for h in hits]
    room = max_chars - sum(len(x) + 1 for x in heads)
    per = max(40, min(snippet, room // len(hits)))
    lines = []
    for head, h in zip(heads, hits):
        text = " ".join(h.text.split())
        lines.append(head + (text[:per - 1] + "…" if len(text) > per else text))
    out = "\n".join(lines)
    return out[:max_chars]


def build_context(hits: list[Hit], max_chars: int | None = None) -> str:
    """Compact context for the LLM: '[path:a-b]' + chunk text, total <= max_chars."""
    max_chars = max_chars or config.ASK_CONTEXT_CHARS
    if not hits:
        return ""
    per = max_chars // len(hits)
    parts = []
    for h in hits:
        head = f"[{h.loc}]\n"
        body = re.sub(r"[ \t]+", " ", h.text).strip()
        body = re.sub(r"\n{2,}", "\n", body)
        room = max(0, per - len(head) - 1)
        parts.append(head + body[:room])
    return "\n".join(parts)[:max_chars]


ASK_PROMPT = ("Answer the question using only the context from the user's own files. Be brief (2-4 plain "
              "sentences) and cite file paths like path:lines. If the context does not answer it, say so.")


def ask(question: str) -> dict:
    """{answer, cached, hits, context_chars}. One fast-tier call unless the answer is cached."""
    from jarvis.core import llm

    idx = get_index()
    if config.ASK_CACHE and (hit := idx.cached_answer(question)):
        return {"answer": hit, "cached": True, "hits": [], "context_chars": 0}
    hits = idx.search(question, k=config.ASK_K)
    if not hits:
        return {"answer": "", "cached": False, "hits": [], "context_chars": 0}
    ctx = build_context(hits)
    msgs = [{"role": "system", "content": ASK_PROMPT},
            {"role": "user", "content": f"Context:\n{ctx}\n\nQuestion: {question}"}]
    answer = str(llm.chat(msgs, tier="fast", purpose="ask_knowledge", max_tokens=config.ASK_MAX_TOKENS)).strip()
    if answer and config.ASK_CACHE:
        idx.cache_answer(question, answer)
    return {"answer": answer, "cached": False, "hits": hits, "context_chars": len(ctx)}


def start_index_job(path: str | Path | None = None, lang: str = "en") -> Any:
    """Index path (default: MEMORY_ROOTS) as a background JobManager job."""
    from jarvis.core import jobs

    label = Path(path).name if path else "your project and notes"

    def run(ctx: Any) -> None:
        st = (index_path(path, progress=ctx.progress, cancel=ctx.check) if path
              else index_roots(progress=ctx.progress, cancel=ctx.check))
        ctx.progress(f"{st.get('files', 0)} files, {st.get('indexed', 0)} (re)indexed, "
                     f"{st.get('deleted', 0)} removed, {st.get('chunks_total', 0)} chunks in "
                     f"{st.get('seconds', 0)} s")
        return None

    return jobs.get_manager().submit(f"index {label}", "index", run, request=str(path or "roots"), lang=lang)


def _rss_mb() -> float:
    import psutil

    return psutil.Process().memory_info().rss / 1e6


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["_worker"]:
        _worker_loop()
        return 0
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cmd = args.pop(0) if args else "stats"
    idx = get_index()
    print(f"rss start {_rss_mb():.0f} MB")
    if cmd == "index":
        st = index_roots() if not args else {p: index_path(p) for p in args}
        print(json.dumps(st, indent=1))
        child = getattr(idx.embedder._model, "child_rss_mb", None)
        print(f"rss model loaded {_rss_mb():.0f} MB (loaded={idx.embedder.loaded}, child process {child} MB)")
        idx.embedder.unload()
        print(f"rss after unload {_rss_mb():.0f} MB")
    elif cmd == "search":
        print(format_hits(idx.search(" ".join(args))))
    elif cmd == "ask":
        print(ask(" ".join(args))["answer"])
    print(json.dumps(idx.stats()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
