# 0004: Hybrid retrieval (FTS5 BM25 + vectors, fused with RRF)

**Status:** Accepted

**Context.** Keyword search misses meaning ("my bike" vs "motorcycle"); vector search misses exact names, numbers
and code. Both must fit in a few MB of RAM.

**Decision.** `memory.py` stores chunks in SQLite: `chunks_fts` (FTS5, BM25) and `vectors` (float32 blobs from
fastembed `bge-small-en-v1.5`, ONNX, no torch). A query runs both and fuses the ranks with reciprocal rank fusion
(`1 / (RRF_K + rank)`). Vectors are scanned with numpy; no FAISS.

**Consequences.** + The best of both searches, one store, no sync problems. - A brute-force scan is fine to about
50k chunks; past that, add an ANN index (FAISS / sqlite-vec) behind the same function.
