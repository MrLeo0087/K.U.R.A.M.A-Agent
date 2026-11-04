# 0010: fastpath.py split into `jarvis/core/intents/`

**Status:** Accepted

**Context.** `fastpath.py` was 4,587 lines: hard to read, slow to search, costly for an AI assistant to open.

**Decision.** Self-contained areas moved, unchanged, into `jarvis/core/intents/`: `base` (Intent, FastResult,
yes/no, small helpers), `files`, `desktop`, `media`, `todo`, `control`. `fastpath.py` re-imports every moved name
at the place it used to be defined, so `fastpath.X`, import order and tests behave exactly as before. The move was
done by a script that checked every name each block needs (no block may depend on code still in fastpath), and
the full test suite passed unchanged. `fastpath.py` is now about 2,900 lines: matching, the meaning gate and
rendering stay there.

**Consequences.** + Each area is one file of 100-600 lines. - New intents go in the area's module; anything that
tests monkeypatch (`match`, `meaning_ok`, `_internal`) must stay in fastpath.py.
