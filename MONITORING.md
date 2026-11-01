# KURAMA monitoring

Every request to KURAMA is recorded as one **trace**, and the voice, wake word, hold-to-talk, Files app and job list
keep small side logs. After 2-3 days of normal use, a Claude Code session reads them, finds what went wrong, proves
the cause and fixes the class of problem. Tracing started with v2 on **2026-10-29**; the side logs on **2026-11-01**.

## Prompt to paste into a new Claude Code session

> You are continuing work on KURAMA, my always-on voice/text assistant in /media/leo/Project1/New_project/KURAMA
> (Ubuntu X11, no GPU, 8 GB RAM, Groq free tier). Read, in this order and nothing else first: `CLAUDE.md`, the top
> "CURRENT STATE" section of `docs/HANDOFF.md`, this file (`MONITORING.md`) and the last ~30 lines of `PROGRESS.md`.
>
> Then run `venv/bin/python scripts/trace_report.py --days 3` (traces + the side logs: speech, wake word,
> hold-to-talk, Files app, job list) and open the worst traces with `--show <id>`.
>
> Tell me in short, simple English the top problems I hit in the last days, grouped by CLASS (wrong tool / area,
> no tool, a mistake I corrected, dropped or misheard speech, wake word misses, hold-to-talk cut-outs, Files
> "this folder" picking the wrong thing, job list failures, slow or expensive requests), with trace ids or log lines
> as proof, the root cause of each (proven from traces / logs / code, not guessed) and the fix you suggest. Also list
> AI requests that should become 0-token shortcuts. If a cause can't be proven, say what evidence is missing.
>
> Don't change code until I say which ones to fix. Then: one class at a time, fix the class (never one sentence),
> add tests (3+ phrasings), run the related tests, the full suite and `venv/bin/python -m tests.eval.harness`
> (must stay >= 65% instant / 100% right / 98% router), one live check, update PROGRESS.md + this file's Fix
> history, commit, and stop for me to test. Be efficient with tokens (mine and Groq's). Never commit COMMAND.md.

## Where the data is

| What | Where | What it tells |
|---|---|---|
| **Traces** (one row per request) | `data/traces.db`, table `traces` | text, path, route, tools + results, AI calls, tokens, answer, time |
| Speech-to-text | `data/logs/stt.log` | every recognition: language Whisper guessed, confidence, DROPPED or not |
| Wake word | `data/logs/wake.log` | every wake check: what was heard, WAKE / no match, rate-limit skips, too-quiet near-misses |
| Hold-to-talk | `data/logs/ptt.log` | key down/up/cancel (server), what the panel window did, page mic start / recording size, every caption hide and who hid it |
| Files app context | `data/logs/fm.log` | per request when Files is the latest app: window title, folder, selection, which window was chosen and why (`pick`) |
| Job list | `data/jarvis.db`, table `job_queue` | jobs kept for later, status, tries, result / error note |
| Long jobs | `data/jarvis.db`, tables `jobs`, `job_state`, `job_steps` | background jobs, checkpoints, step log |
| Server / workers | `data/logs/server.log`, `data/logs/worker_*.log` | yes/no answers, errors |
| Code that writes them | `jarvis/core/trace.py`, `stt.py`, `wake.py` (`wake_log`), `ptt.py` (`pttlog`) + `scripts/kurama_wallpaper.py`, `filemanager.py`, `jobqueue.py`, `longjobs.py` | |

- Settings: `config.py` `TRACING` (env `KURAMA_TRACING=0` turns it off), `TRACE_DB`, `TRACE_KEEP_DAYS` (90). Side logs
  trim themselves (~100-250 KB). Reset KURAMA does not wipe traces. The data never leaves the laptop.
- Not traced: the test suite and the scorecard (their own temporary data), background jobs' own AI calls after the
  reply (in `jarvis.db` → `llm_calls`, purpose `job<N>:...`).

## What one trace holds

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
venv/bin/python scripts/trace_report.py --days 3        # traces + side logs (speech, wake, hold-to-talk, Files, job list)
venv/bin/python scripts/trace_report.py --show 3fa9c1   # one request in full (id or its first letters)
venv/bin/python scripts/trace_report.py --csv /tmp/traces.csv
venv/bin/python scripts/trace_report.py --mark-fixed    # after fixing what a report found: later reports start from now
venv/bin/python scripts/trace_report.py --all           # include requests from before the last --mark-fixed
venv/bin/python -m tests.eval.harness                   # the scorecard (0 tokens; never reads the live desktop)
```

Traces part: totals, errors, **likely mistakes** (a request followed within 2 min by a correction: the most valuable
rows), commands answered without a tool, retries, "no" to yes/no questions, failed tool calls, slowest, most tokens,
requests asked the AI most often (0-token shortcut candidates), tools used.
Side part: speech drops, wake checks (woke / no match / too quiet / rate-limited), hold-to-talk (caption hides,
mic failures, page reloads), Files reads with several windows (window guessed), the job list (failed jobs + why).

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
| Speech dropped / misheard | `stt.py` (`not_ours`, `_gate`), `config.STT_FIXES`, the mic volume (Settings > Voice; it was 39%) |
| Wake word missed | `wake.py` `match_wake` (+ `config.WAKE_PHRASES`), the page fallback `wakeRest` in `frontend/app.js` |
| Hold-to-talk stops / sticks | `jarvis/core/ptt.py` (keys), `scripts/kurama_wallpaper.py` `Mini.ptt` / `Caption`, `kuramaPTT` in `frontend/app.js` |
| "this folder / file" wrong | `scripts/kurama_fm.py` (window, selection), `jarvis/core/filemanager.py`, `focus.refer` |
| A job-list job failed | `jarvis/core/jobqueue.py` (runner, retries, Telegram questions) |

## How KURAMA works now (2026-11-01)

- **Routing:** meaning first (`semantic.py`) + learned wordings; typos are read as the nearest area word for routing
  (`router.fix_typos`, never real English words); word rules only add candidates. Areas served by two general tools
  pick the one whose description fits the request's meaning (`registry.schemas_for(groups, text)`). Shortcuts run
  only if the meaning agrees (`fastpath.meaning_ok`; free-text shortcuts like the sports search must be the best
  area: `MEANING_GATE_STRICT`). The open VS Code adds the text tool but never forces the big model.
- **Context:** the VS Code file + selection, the browser tab + highlight, and the **Files app** (folder open or item
  selected, when Files is the latest app; one window: the focused one, else the top one). "this / it / here / the
  selected" resolve in that order: a pasted path, Files, KURAMA's remembered folder.
- **Multi-task:** numbered items stay independent; a step that only starts a background job makes the next steps a
  follow-up job that waits for the real output.
- **Jobs:** essays / reports / code run on the **Long Job Engine** (`longjobs.py`: checkpoints, resume after a
  restart, token/time caps, pause on low RAM / battery). **Job list** (`jobqueue.py`): add / list / edit / remove
  keep jobs; "start" runs them (questions go to Telegram, 2 min, then the next job; retries only on temporary
  failures; notices on laptop + Telegram). "Keep for later" vs "do it now" is decided by meaning (cold model: it
  loads first).
- **Voice:** mic input 70%; real speech from the forced English/Nepali pass is kept even when Whisper's auto pass
  mislabels the language. **Hold Ctrl** (alone, 0.3 s) = talk, let go = send, **double-tap Shift** = close the reply
  (KURAMA Settings > Shortcuts). Wake: "hey KURAMA", "KURAMA wake up", "wake up", "start system" + mishearings.
- **Yes/no:** risky actions use the real Yes/No card; the AI never asks yes/no in chat first.
- **Telegram files:** one upload try (Telegram may answer an error yet deliver: no duplicates); a folder zip <= 50 MB
  goes directly, bigger ones (up to 20 GB) as a gofile.io download link.
- **Mini UI:** glass panel (Blur my Shell, `scripts/kurama_glass.py`, Look button: blur / light / corners / tint /
  font), Inter font, job strip, panel page kept 20 min and shown only when loaded.

## Known shortcuts that are still word patterns (replace them by meaning when touched)

`fastpath.link_play_intent`, `fastpath.clean_intent`, `fastpath.to_file_intent`, `fastpath._code_not_file`, the "this
video now" rule in `video_dl_intent`, the filler-word list in `tools/general/video_download.py`.

## Which document to update (after every fix)

| Document | Update when |
|---|---|
| `PROGRESS.md` | every step: what was broken, the proven cause, the fix, the tests / live check (append) |
| `MONITORING.md` (this file) | a new log or report section, a new class of problem in the fix table, the Fix history line |
| `docs/HANDOFF.md` (top section) | the current state changes: what is done, what is next, open decisions |
| `docs/FIX_PLAN.md` | a planned step is done (mark DONE) or a new plan is agreed |
| `docs/NIGHT_SHIFT.md` | Night Agent / heavy-tool steps are done or decided |
| `CLAUDE.md` | only when the owner changes a rule |
| `COMMAND.md` | never by Claude (the owner's own file) |

## Fix history

## Fix history

- 2026-10-30: the first report's problems (wrong tools, downloads, open tab / code / small talk, honest replies, mic/sound) were fixed; see PROGRESS.md (FIX 1-5). Reports start after this (`traces_fixed_at`).
- 2026-10-30 (later): downloads (progress, pause/resume/delete, library, cookies, speed), laptop alerts beside the
  mini button, Ctrl+Alt+K, resizable mini chat, music links in KURAMA's player, cleanup tool, mic/echo canceller only
  while recording, context line (VS Code + browser tab), code workflow (patches, typed yes, background jobs, no
  overwrite loop), passwords masked in traces. 14 eval cases added (scorecard: 64% instant at 100%, router 92%).
- 2026-10-31 / 11-01 (see PROGRESS.md): Long Job Engine; mini UI glass redesign + hold-to-talk + shortcuts settings;
  fix plan steps 1-6 (job tool by meaning, chain waits for jobs, writer on the engine, editor context no longer forces
  the big model; mic 39% -> 70% and forced-pass speech kept; wake phrases + mishearings; router 90% -> 98% with
  typo-tolerant routing; no yes/no loops); job list with Telegram questions; Files app context; Telegram: no
  duplicate uploads, big folders as links. New side logs: wake.log, ptt.log, fm.log (+ stt.log) in the report.
- 2026-11-01 (morning): link store through the AI (own "links" area, list/delete/rename/clear, only this message's
  link/name, learned wordings follow their tool), fake "done" claims in any grammar retried with the turn's tools,
  junk streams held and replaced by the tool result, 0-token actions by meaning (copy path, VS Code here, start /
  list jobs), video link kept when words come before it, "Slowest" without yes/no waits. Watch: "junk-looking stream
  held" in server.log, link-store traces, meaning shortcuts taking a request they shouldn't.
