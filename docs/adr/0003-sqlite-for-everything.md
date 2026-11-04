# 0003: One SQLite file for logs, memory, jobs and settings

**Status:** Accepted

**Context.** One user, one laptop, all day. A database server (PostgreSQL, Chroma, Redis) would cost RAM and setup for no gain.

**Decision.** `data/jarvis.db` via stdlib `sqlite3` with WAL (readers never block the writer), one lock per
process, indexed `ts` columns. Tables: llm_calls, tool_calls, routing, messages, jobs, notes, todos, kv... Memory
uses FTS5 inside the same file.

**Consequences.** + Zero extra processes, a backup is one file copy, SQL is the same skill as PostgreSQL.
- One writer at a time: fine for one user, wrong for a multi-user server. The path up is PostgreSQL with the same
SQL and the same table design (see LEARN.md section 23).
