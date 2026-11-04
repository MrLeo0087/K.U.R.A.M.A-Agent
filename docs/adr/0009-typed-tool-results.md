# 0009: Tools may return `Reply`: text plus exact data

**Status:** Accepted

**Context.** Tools returned plain sentences and the next step (`open the second one`, `send it`) parsed paths back
out of the text with regexes. Display text is cut to 140 characters, so a long path could never be picked again.

**Decision.** `jarvis/core/results.py`: `Reply(str)` is still a string (LangChain, the LLM and old callers see the
same text) and carries `.data` (for example `paths=[...]`). `registry.call` copies it into `ToolResult.data`, and
`safety.execute` hands it to `workmem.record_call`, which uses the exact paths first and the old text parsing
only as a fallback. `find_files` is the first tool that returns one.

**Consequences.** + Picks and chains use exact values. + No breaking change: tools move over one at a time.
- Two ways exist until every lister returns a Reply.
