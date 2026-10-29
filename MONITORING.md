# KURAMA monitoring

Every request to KURAMA is recorded as one **trace**, so that after a week (or 100 or 1,000 requests) a Claude Code
session can find what goes wrong and fix it. Tracing started fresh with v2 on **2026-10-29**; older chats were wiped.

## Prompt to paste into a new Claude Code session

> Read `MONITORING.md` and `CLAUDE.md` in `/media/leo/Project1/New_project/KURAMA` (don't scan the rest of the repo).
> Run `venv/bin/python scripts/trace_report.py --days 7` and look at the traces it points to with `--show <id>`.
> Tell me in short, simple English the top 5 problems (wrong tool, no tool, mistakes I had to correct, slow or
> expensive requests, errors) with the trace ids as proof, and for each one the fix you suggest. Also list the AI
> requests that should become 0-token shortcuts. Don't change code until I say which fixes to do. After fixing,
> add a test, run the related tests and `venv/bin/python -m tests.eval.harness`, then commit.

## Where the data is

| What | Where |
|---|---|
| **Traces** (one row per request) | `data/traces.db`, table `traces` (SQLite) |
| Code that records them | `jarvis/core/trace.py`; hooked in `Agent.run` / `Agent.stream` (`jarvis/core/agent.py`), `store.log_llm`, `store.log_tool` |
| Report | `scripts/trace_report.py` |
| Settings | `config.py`: `TRACING` (env `KURAMA_TRACING=0` turns it off), `TRACE_DB`, `TRACE_KEEP_DAYS` (90) |

- **Reset KURAMA does not wipe traces**: they are improvement data, not KURAMA's memory. To start the data over:
  `venv/bin/python -c "from jarvis.core import trace; print(trace.clear())"`.
- Rows older than 90 days are removed by themselves.
- Not traced: the test suite (its own temporary file), the scorecard (`tests/eval`), and background jobs' own AI
  calls after the reply was given (an essay's writing is logged in `jarvis.db` → `llm_calls`, purpose `writer`).
- Cost: about 0 RAM/CPU (one small SQLite insert per request). The data never leaves the laptop.

## What one trace holds

| Column | Meaning |
|---|---|
| `id`, `ts`, `day` | trace id (12 letters), start time, date |
| `channel`, `mode` | `telegram` or empty (the laptop); `text` / `voice` / `talk` |
| `text` | what the user said, as KURAMA got it (after speech-to-text for voice) |
| `path` | `fastpath` (instant shortcut or `/command`, 0 tokens), `multi` (several tasks split), `ai` (the agent), `no_ai` (AI switched off), `error` |
| `intent` | the shortcut's intent name, or the first tool the AI called |
| `route_method`, `route_groups` | how the router decided (`rules`, `semantic`, `classifier`, `meta` = the AI asked for tools, `fastpath`) and the tool groups it picked |
| `tools_sent` | the tools the AI was given (at most 3 of the 17 general tools) |
| `tools` | every tool that ran: name, args, ok, ms, outcome (`allowed` / `denied` / `blocked` / `error`), first 300 chars of the result, `safety: confirm` when it asked yes/no |
| `plan` | the split of a multi-task request |
| `tier`, `llm_calls`, `tokens_in`, `tokens_out`, `tokens`, `llm` | AI size, number of AI calls, tokens, and each call: model, purpose (`agent_text`, `router`, `planner`, `summary`...), tokens, ms, error |
| `retried` | 1 = the AI said "I can't" or claimed an action without a tool, so it was retried with tools |
| `asked`, `denied` | a yes/no question was asked / the user said no |
| `jobs` | background jobs started (essays, images, videos...) |
| `answer` | the reply (first 2000 chars) |
| `ms` | total time until the reply |
| `error` | an exception, or `stopped early` (barge-in: the reply was cut off) |

## How to use the report

```bash
venv/bin/python scripts/trace_report.py               # last 7 days
venv/bin/python scripts/trace_report.py --days 30
venv/bin/python scripts/trace_report.py --show 3fa9c1  # one request in full (id or its first letters)
venv/bin/python scripts/trace_report.py --csv /tmp/traces.csv   # everything, for a spreadsheet
```

The report shows:
1. **Totals:** requests by path (how many were free), channel and mode; median / p90 / max time; tokens per day and per AI request.
2. **Errors.**
3. **Likely mistakes:** a request followed within 2 minutes by a correction ("no", "not that", "I said", "it didn't", "hoina", "galat", "nahi"...). These are the most valuable rows.
4. **AI answered a command without any tool:** "turn off bluetooth" answered with words only (a lie or a refusal).
5. **Retries** and **"no" to yes/no questions**.
6. **Failed tool calls** with their arguments and error.
7. **Slowest** and **most expensive** requests.
8. **Asked the AI most often:** repeated requests that cost tokens; the best ones to make 0-token shortcuts.
9. **Tools used** most.

For your own questions, query the table directly, e.g.:

```bash
venv/bin/python - <<'EOF'
import sqlite3; c = sqlite3.connect("data/traces.db")
for r in c.execute("SELECT id, path, tokens, ms, text, answer FROM traces WHERE path='ai' ORDER BY tokens DESC LIMIT 20"):
    print(r)
EOF
```

## How to fix what the report finds

| Problem | Where to fix it |
|---|---|
| A common phrase goes to the AI | add a shortcut in `jarvis/core/fastpath.py` (and a case in `tests/eval/cases.jsonl`) |
| Speech-to-text heard a word wrong | `config.STT_FIXES` |
| The router picked the wrong area | `config.ROUTER_RULES` / `config.CORE_COVERS`, examples for the semantic router in `config` |
| The AI picked the wrong action / argument | the general tool's description and args in `jarvis/tools/core/<tool>.py` |
| A tool failed | the specialised tool in `jarvis/tools/{general,interactive,external}/` |
| Slow or expensive | check `llm` in the trace: planner / router / summary calls that could be skipped, a big tier where the fast one would do |

After a fix: add a test, run the related tests and the scorecard (`venv/bin/python -m tests.eval.harness`; add `--ai`
for the full agent, which costs tokens), update `PROGRESS.md`, commit.
