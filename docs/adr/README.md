# Architecture Decision Records (ADRs)

One short file per big choice: what we decided, why, and what we gave up. Write a new one when a choice is hard
to undo (a database, a framework, a model, a file layout). Never edit an old decision: write a new ADR that
replaces it and mark the old one "Superseded by NNNN".

| # | Decision | Status |
|---|---|---|
| [0001](0001-groq-free-tier-llms.md) | Groq free tier for all LLM work, model IDs only in config | Accepted |
| [0002](0002-langchain-langgraph.md) | LangChain tools + LangGraph for the agent | Accepted |
| [0003](0003-sqlite-for-everything.md) | One SQLite file (WAL) for logs, memory, jobs and settings | Accepted |
| [0004](0004-hybrid-retrieval.md) | Hybrid retrieval: FTS5 BM25 + fastembed vectors, fused with RRF | Accepted |
| [0005](0005-zero-token-fast-path.md) | A zero-token fast path, gated by meaning | Accepted |
| [0006](0006-cpu-only-lazy-loading.md) | CPU only, no torch, lazy-load and unload heavy modules | Accepted |
| [0007](0007-in-process-cache-and-jobs.md) | In-process caches, rate limiter and job queue (no Redis/Celery) | Accepted |
| [0008](0008-frontend-no-build-step.md) | Frontend stays plain ES modules with no build step | Accepted |
| [0009](0009-typed-tool-results.md) | Tools may return `Reply`: text plus exact data | Accepted |
| [0010](0010-fastpath-split.md) | fastpath.py split into `jarvis/core/intents/` with re-exports | Accepted |
| [0011](0011-plugin-architecture.md) | Plug-ins for tools, memory sources and agents | Accepted |
