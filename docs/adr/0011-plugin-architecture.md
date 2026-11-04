# 0011: Plug-in architecture for tools, memory sources and agents

**Status:** Accepted

**Context.** The owner wants to keep adding tools, kinds of memory and agents, and a new one must never break or
require editing an old one. Tools were already one file each (found by `registry.discover`), but a new agent meant
editing three central lists, and each kind of memory had its own shape and its own search.

**Decision.** Three extension points, all found through `core/plugins.py` (import each plug-in alone, catch its
errors, list failures in `plugins.broken()` and the `kurama_plugins_broken` metric):

- **Tool**: a file in `jarvis/tools/general/` with `@tool(group, safety, description)`.
- **Memory source**: a file in `jarvis/memories/` with `SOURCE = MemorySource(name, description, search, heavy)`;
  `memories.search()` asks every light source, isolates failures and fuses the results with reciprocal rank fusion.
- **Agent**: a folder in `jarvis/agents/` with `SPEC = AgentSpec(...)` (aliases, welcome and status hooks included)
  and an optional `tools.py`; its tool groups are kept out of normal routing automatically (`agents.groups()`).

`tests/test_plugin_contracts.py` checks every tool, source and agent, plus the isolation; `scripts/new_plugin.py`
(`make new-tool` / `new-memory` / `new-agent`) writes a skeleton and a test.

**Consequences.** + Adding is local and safe; a broken plug-in is visible, not fatal. + Agents' coding-specific code
left the shared module. - Discovery happens at run time, so a typo in a plug-in shows up as a log line and in
`plugins.broken()`, not as a crash: check `make metrics` (or the log) after adding one.
