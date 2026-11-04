# 0005: A zero-token fast path, gated by meaning

**Status:** Accepted

**Context.** Most requests are everyday commands (volume, open an app, the time). Sending them to the LLM wastes
tokens and a second of latency, and the free tier is small.

**Decision.** `fastpath.match()` (with the intents in `jarvis/core/intents/`) turns a request into one tool call
and a template answer, with no LLM call. A shortcut only runs if `meaning_ok` agrees (the local semantic router
judges the whole request), so a rule can never hijack a different request. New word-based intent rules are not
added; new wordings are learned from the owner's corrections.

**Consequences.** + Most commands cost 0 tokens and answer in milliseconds. - The intent code is large and needs
its own tests (tests/eval is the scorecard).
