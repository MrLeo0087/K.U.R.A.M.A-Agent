# 0007: In-process caches, rate limiter and job queue

**Status:** Accepted

**Context.** Industry systems use Redis (cache), Celery/RQ (jobs) and a gateway (rate limits). Each is another
process and more RAM, for one user.

**Decision.** TTL caches in memory (weather, web, answers), a shared per-model token limiter (`budget.py`), and a
job queue stored in SQLite (`jobqueue.py`, `jobs.py`) that survives restarts and never blocks the voice loop.

**Consequences.** + No extra services, same ideas (TTL, backoff, idempotent jobs, progress). - Caches are lost on
restart and are per process; with several servers you would move them to Redis without changing the callers.
