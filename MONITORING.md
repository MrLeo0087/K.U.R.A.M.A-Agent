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
venv/bin/python scripts/trace_report.py --mark-fixed   # after fixing what a report found: later reports start from now
venv/bin/python scripts/trace_report.py --all          # include requests from before the last --mark-fixed
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

## How to fix what the report finds (rules: fix the CLASS of problem, never one sentence)

The owner's standing rule: no cheap per-query fixes. A fix must work for every way of saying the thing and for
every tool of that kind, not just the sentence in the trace.

1. **Find the class.** Group the bad traces: is it routing (wrong area / tool not offered), the AI's choice
   (wrong action / argument), a tool bug, missing context, or cost? One class = one fix.
2. **Prefer meaning over words.** In this order: the tool's description and arguments (the AI decides by
   meaning) → semantic router examples (`config.ROUTER_EXAMPLES`) → the context line (`jarvis/core/context.py`)
   → learning (`data/learned.json` fills itself from corrections). A new regex shortcut in `fastpath.py` is the
   LAST resort and only for a WHOLE-request command whose wording is fixed (`/clean ram`, "<link> play this").
   Never add a "if word X appears do Y" rule (CLAUDE.md).
3. **Prove it is general.** Add 3+ different phrasings of the case to `tests/eval/cases.jsonl` (not just the one
   from the trace), a unit test for the mechanism, run the related tests, the full suite, and the scorecard
   (`venv/bin/python -m tests.eval.harness`; `--ai` runs the real agent and costs tokens). For a live check, send
   it through the API: `curl -sN -X POST http://127.0.0.1:8000/api/v1/chat -H 'Content-Type: application/json'
   -d '{"text":"..."}'`.
4. `scripts/trace_report.py --mark-fixed`, update `PROGRESS.md` and the Fix history below, commit, restart
   (`scripts/kurama-power.sh off; scripts/kurama-power.sh on`).

| Problem | Where to fix it |
|---|---|
| The router picked the wrong area | examples for the semantic router (`config.ROUTER_EXAMPLES`), `config.CORE_COVERS`; `config.ROUTER_RULES` only adds candidates now |
| The AI picked the wrong action / argument | the general tool's description and args in `jarvis/tools/core/<tool>.py` |
| "this / it / the code / this page" misunderstood | `jarvis/core/context.py` (VS Code file + selection, browser tab via `browser_ext/`) |
| A shortcut fired on the wrong meaning | `fastpath.meaning_ok` (meaning gate) / learned vetoes; fix the pattern only if it is a fixed command |
| Speech-to-text heard a word wrong | `config.STT_FIXES` |
| A tool failed | the specialised tool in `jarvis/tools/{general,interactive,external}/` |
| Slow or expensive | `llm` in the trace: planner / router / summary calls that could be skipped, a big tier where the fast one would do; long work belongs in a background job (`jobs.get_manager().submit`) |

## How KURAMA works now (after the 2026-10-30 fixes)

- **Routing:** meaning first (`semantic.py`, warm model) + learned wordings (`learn.py`, `data/learned.json`);
  word rules only add candidates or stand in while the model loads. Shortcuts run only if the meaning agrees.
- **Learning:** each turn is judged when the next one arrives (a correction by meaning within 2 min teaches the
  right area and vetoes the wrong shortcut; a correction after a FAILED action does not veto it).
- **Context:** the VS Code file + selected code, or the browser tab, go into the prompt as one short line.
- **Code workflow:** `code_to_file` (generate / complete / put code into the open file): Python files get a
  patch (only changed or new functions, applied in place), a blank file is written at once, every other change
  waits for a typed "yes" (backup in `data/backups/`); long generation runs as a background job. Selected code:
  the assist flow (improve / complete the selection, "Should I replace it?"). VS Code auto-save is on.
- **Honesty:** no "done" when every tool failed or was refused (`agent.honest`); no retries after a "no" or on
  emoji; garbled "… … …" streams replaced.
- **Downloads:** yt-dlp with live progress (`ytdl.py`), 1080p default, cookie retry for the bot check, bars +
  library in the workspace (`/api/v1/downloads`, `/api/v1/videos`).
- **Audio:** the echo canceller runs only while a page records the mic (`devaudio.mic_use`); music ducks only in
  voice / talk mode.
- **Cleanup:** `/clean ram | storage | kurama` (`jarvis/core/cleanup.py`).

## Known shortcuts that are still word patterns (replace them by meaning when touched)

These were added on 2026-10-30 to make urgent cases work; each is a whole-request pattern, but they are the first
candidates to turn into meaning-based intents (examples + the meaning gate) if a report shows them misfiring:
`fastpath.link_play_intent` (YouTube link + "play this"), `fastpath.clean_intent` ("clean my RAM / storage /
KURAMA"), `fastpath.to_file_intent` (code + "in this file / path", "complete <file/function>", "replace it" after
code in the chat), `fastpath._code_not_file` ("where is this function" -> code search), the "this video now" source
rule in `video_dl_intent`, and the filler-word list in `tools/general/video_download.py`.

## Fix history

- 2026-10-30: the first report's problems (wrong tools, downloads, open tab / code / small talk, honest replies, mic/sound) were fixed; see PROGRESS.md (FIX 1-5). Reports start after this (`traces_fixed_at`).
- 2026-10-30 (later): downloads (progress, pause/resume/delete, library, cookies, speed), laptop alerts beside the
  mini button, Ctrl+Alt+K, resizable mini chat, music links in KURAMA's player, cleanup tool, mic/echo canceller only
  while recording, context line (VS Code + browser tab), code workflow (patches, typed yes, background jobs, no
  overwrite loop), passwords masked in traces. 14 eval cases added (scorecard: 64% instant at 100%, router 92%).
