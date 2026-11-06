# KURAMA monitoring

Every request to KURAMA is recorded as one **trace**, and the voice, wake word, hold-to-talk, Files app and job list
keep small side logs. Every 2-3 days of normal use, read them, find what went wrong, prove the cause and fix the
class of problem: **yourself** (section "Do it yourself" below, and LEARN.md sections 19-20) or with a Claude Code
session (the prompt below). Tracing started with v2 on **2026-10-29**; the side logs on **2026-11-01**; step results,
answers to KURAMA's questions and the model per call since the memory + multitasking rebuild (**2026-11-01 night**).

## Prompt to paste into a new Claude Code session

> You are continuing work on KURAMA, my always-on voice/text assistant in /media/leo/Project1/New_project/KURAMA
> (Ubuntu X11, no GPU, 8 GB RAM, Groq free tier). Read, in this order and nothing else first: `CLAUDE.md`, the top
> "CURRENT STATE" section of `docs/HANDOFF.md`, this file (`MONITORING.md`) and the last ~30 lines of `PROGRESS.md`.
>
> For how the code works, `LEARN.md` is the map (sections 2-4: a request, short-term memory, the task graph; section
> 20: the monitoring routine).
>
> Then run `venv/bin/python scripts/trace_report.py --days 3` (traces + the side logs: speech, wake word,
> hold-to-talk, Files app, job list) and open the worst traces with `--show <id>`.
>
> Tell me in short, simple English the top problems I hit in the last days, grouped by CLASS (wrong tool / area,
> no tool, a mistake I corrected, dropped or misheard speech, wake word misses, hold-to-talk cut-outs, Files
> "this folder" picking the wrong thing, "it / that image" pointing at the wrong thing, multi-step requests with
> failed / skipped steps, short replies ("yes") routed wrongly, model fallbacks (gemini / qwen in use), job list
> failures, slow or expensive requests), with trace ids or log lines
> as proof, the root cause of each (proven from traces / logs / code, not guessed) and the fix you suggest. Also list
> AI requests that should become 0-token shortcuts. If a cause can't be proven, say what evidence is missing.
>
> Work style: core problem first, then the solution. Prove the root cause before touching code, then make one
> general fix for it. Be efficient with Claude Code tokens: read only the files and line ranges you need, don't
> re-read what you wrote, run the related tests while working and the full suite + scorecard ONCE at the end of a
> fix (not after every edit), no repeated live checks, short reports.
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
| **👍 / 👎** | `data/traces.db`, table `feedback` (trace_id, vote, note) | the owner's verdict on each reply: 👎 rows are the first thing to read |
| Learned shortcuts | `data/recipes.json` (`/learned_shortcuts list`) | 0-token shortcuts + kept answers the owner approved (👍 / praise) or taught (a correction), uses, tokens saved per day |
| The owner's words | `data/my_words.json`, `data/app_names.json` | "when I say X, do Y" / "when I say X, open <app>", kept until changed |
| Reply rules | `data/style.json` | "from now on keep answers short": added to every AI request, max 6 |
| (all of the learning above) | **docs/LEARNING.md** | the full guide: what is learned, commands, limits, files, settings |
| Long jobs | `data/jarvis.db`, tables `jobs`, `job_state`, `job_steps` | background jobs, checkpoints, step log |
| Server / workers | `data/logs/server.log`, `data/logs/worker_*.log` | yes/no answers, errors |
| **Claude Code watch** | `data/claude_watch.json` (+ `data/claude_watch.on` = on), `data/logs/claude_say.log` | each watched conversation: prompt, steps, files, to-do, status, final answer; what `/claude say` ran |
| Telegram sections / offers | `data/jarvis.db` table `kv`: `tg_topics`, `tg_group_candidate`, `next_offer`, `setting_once` | the group topics in use; the "say yes to…" offer waiting; a one-time setting to keep |
| Owner's settings | `data/user_settings.json` | the safe settings changed by voice (values + history for undo) |
| Nepal documents service | `KURAMA_RAG_API_URL` in `.env`; jobs `kind = nepal_docs` in `data/jarvis.db` | each question asked of it (a background job), its status, the answer as the job's `» ` progress |
| Live numbers | `GET /api/v1/metrics` (`make metrics`) | tokens per model, tool calls, routing, jobs, RAM, broken plug-ins (last 24 h) |
| Code that writes them | `jarvis/core/trace.py`, `stt.py`, `wake.py` (`wake_log`), `ptt.py` (`pttlog`) + `scripts/kurama_wallpaper.py`, `filemanager.py`, `jobqueue.py`, `longjobs.py` | |

- Settings: `config.py` `TRACING` (env `KURAMA_TRACING=0` turns it off), `TRACE_DB`, `TRACE_KEEP_DAYS` (90). Side logs
  trim themselves (~100-250 KB). Reset KURAMA does not wipe traces. The data never leaves the laptop.
- Not traced: the test suite and the scorecard (their own temporary data), background jobs' own AI calls after the
  reply (in `jarvis.db` → `llm_calls`, purpose `job<N>:...`).

## What one trace holds

| Column | Meaning |
|---|---|
| `id`, `ts`, `day` | trace id (12 letters), start time, date |
| `channel`, `mode` | `telegram` or empty (the laptop); `text` / `voice` / `talk` |
| `text` | what the user said, as KURAMA got it (after speech-to-text for voice) |
| `path` | `fastpath` (instant shortcut or `/command`, 0 tokens), `multi` (several tasks split), `ai` (the agent), `no_ai` (AI switched off), `error` |
| `intent` | the shortcut's intent name (`choice` = a pick from KURAMA's numbered list, `tgmsg` = Telegram message...), or the first tool the AI called |
| `route_method`, `route_groups` | how the router decided (`rules`, `semantic`, `classifier`, `meta` = the AI asked for tools, `fastpath`, `answer` = a short reply routed by KURAMA's own question, `followup`, `graph` = a multi-step request) and the tool groups it picked |
| `tools_sent` | the tools the AI was given (at most 3 of the 17 general tools) |
| `tools` | every tool that ran: name, args, ok, ms, outcome (`allowed` / `denied` / `blocked` / `error`), first 300 chars of the result, `safety: confirm` when it asked yes/no |
| `plan` | a multi-task request: `method` (`rules` / `learned` = 0-token plan, `llm` = one planning call, `single`), `tasks` with `depends_on`, `steps` (`1:ok 2:skipped 3:waiting 4:after`), `replanned` (`from` → `to`) |
| `tier`, `llm_calls`, `tokens_in`, `tokens_out`, `tokens`, `llm` | AI size, number of AI calls, tokens, and each call: model (gpt-oss / **gemini** / qwen), purpose (`agent_text`, `router`, `planner`, `replan`, `summary`...), tokens, ms, error |
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
**multi-step requests with a failed / skipped / waiting step or a re-plan**, multi-step plan methods, **short
replies routed by KURAMA's question** (route `answer`), **choices**, **models used** (with failures), requests asked
the AI most often (0-token shortcut candidates), tools used.
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
| The window froze / "not responding" | `data/logs/hang.log` (stacks of every thread), `hang_guard` in `scripts/kurama_wallpaper.py` |
| Hold-to-talk stops / sticks | `jarvis/core/ptt.py` (keys), `scripts/kurama_wallpaper.py` `Mini.ptt` / `Caption`, `kuramaPTT` in `frontend/app.js` |
| "this folder / file" wrong | `scripts/kurama_fm.py` (window, selection), `jarvis/core/filemanager.py`, `focus.refer` |
| A job-list job failed | `jarvis/core/jobqueue.py` (runner, retries, Telegram questions) |
| "it / that image / the folder" pointed at the wrong thing | `workmem.py` (what was recorded: is the full path in the tool's result?), `focus.refer` order, `WORKMEM_FRESH_S` |
| "yes" got the wrong tools / "nothing waiting" | `agent._open_question` (`_OFFER`, `QUESTION_TTL_S`), route method `answer` in `_route_node` |
| A pick from a list ("2") did nothing | `workmem.choose` / `_offer` (the list must be numbered real paths) |
| Tasks split / linked wrongly | `planner.py` (`split_clauses`, `_REF`, `PLAN_PROMPT`, `parts`), `FILLER_EXAMPLES` |
| A step failed / was skipped wrongly | `taskgraph.judge` (claims, `error:` results: `workmem._FAILED`), `taskgraph.settle` |
| A learned plan was reused wrongly | `data/learned_plans.json` (delete the row), `TASK_PLAN_MATCH` |
| Requests fail on a model that hit its limit | `llm._chain` / `_on_error` (cooldown), `TIER_CHAIN`, `LLM_COOLDOWN_S` |
| A short action's reply needed the AI's wording | `config.DIRECT_REPLY_SINGLE` / `DIRECT_REPLY_STEPS` / `DIRECT_REPLY_MAX_WORDS` |
| A request about the open file got no text tool | `agent._about_context` (`CONTEXT_TOOL_SEL_MIN`, `CONTEXT_TOOL_MARGIN`) |
| A key / private file showed up in a reply | `jarvis/tools/interactive/_secrets.py` (`private`, `private_file`), `context.snapshot`, `rewrite.peek/grab` |

## How KURAMA works now (2026-11-01, after the memory + multitasking rebuild)

- **Short-term memory** (LEARN.md section 3): working memory of real things (`workmem.py`), choices, KURAMA's open
  question routes short replies, tool lines in history, the laptop chat resumes after a restart.
- **Multitasking** (LEARN.md section 4): the task graph (`taskgraph.py` + agent `schedule → step → finish`): steps
  get what the steps they need made, shortcut first, no chat history, checked, one re-plan, skipped with the reason,
  follow-up jobs, learned plans, filler by meaning, "close X" only closes what the plan opened.
- **Models** (LEARN.md section 10): gpt-oss → Gemini → qwen; used-up models cool down.
- **Tokens** (LEARN.md section 11): direct replies for short actions, the text tool only by meaning, 0-token
  Telegram messages.
- **Privacy**: private files (.env, keys) and highlighted keys never reach the AI.

Older notes (still true):

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
  mislabels the language. **Hold Alt** (alone, 0.3 s; Ctrl until 11-01; the hidden panel is preloaded and kept, so the first hold never waits) = talk, let go = send, **double-tap Shift** = close the reply
  (KURAMA Settings > Shortcuts). Wake: "hey KURAMA", "KURAMA wake up", "wake up", "start system" + mishearings.
- **Yes/no:** risky actions use the real Yes/No card; the AI never asks yes/no in chat first.
- **Telegram files:** one upload try (Telegram may answer an error yet deliver: no duplicates); a folder zip <= 50 MB
  goes directly, bigger ones (up to 20 GB) as a gofile.io download link.
- **Mini UI:** glass panel (Blur my Shell, `scripts/kurama_glass.py`, Look button: blur / light / corners / tint /
  font), Inter font, job strip, panel page kept 20 min and shown only when loaded.

- **Since 11-01 (round 1 of the trace fixes):** the meaning model is loaded before routing (~0.6 s once; the word
  rules no longer decide the first request after idle). One embedding-model process is shared by the router and the
  document search. 0-token actions by MEANING (`config.MEANING_SHORTCUTS` + `fastpath.meaning_intent`): save / list
  links (unknown words are masked as X; the left-over words are the name), copy this folder's path, open it in VS
  Code, start / list jobs, clean RAM / KURAMA / storage; the router also offers the masked action's area. The link
  store is its own area ("links", served by `memory`), with list / open / delete (name, number, all) / rename. A
  tool-less "done" claim in any grammar, or a tool-less answer in a saved-things area (`config.DATA_AREAS`), is
  retried with the turn's tools. Junk gpt-oss streams are held and replaced by the tool's result. Talk mode keeps
  greetings and clear requests by meaning. "Free RAM" offers (asks) to close windowless idle apps; `/clear ram |
  storage | kurama`. The architecture guide for humans is `LEARN.md`.

## Since the last report (11-01, afternoon) — check these first in the next report

- New since round 1: tab control by name (extension 1.3: list / switch / close tabs), scroll by meaning, keys go to
  the app below KURAMA's chat, home screen (window desktop), Super key, Colab/Kaggle training cell (copied),
  organize uses the folder in use, qwen is the last model fallback (both gpt-oss hit Groq's 200k/day on 11-01: a
  new key in the same Groq account shares that limit), Super+J puts the cursor in the chat box and back (the chat stays open),
  KURAMA puts your clipboard back after reading a highlight or pasting a rewrite, spoken requests are never dropped
  behind a stuck turn, a frozen window logs its stacks (data/logs/hang.log) and restarts itself.
- **Test rounds** (`scripts/tool_round.py --round N [--real] [--failed]`): owner-style questions for ~25 tools,
  read-only tools real, the rest fake, heavy-AI tools left out, 40k Groq tokens per round. Round 1: 38/45 judged
  right (84%); 30 questions not judged (internet cut, then Groq's daily limit): finish them with
  `--round 1 --real --failed` on a fresh day. Results: data/eval/round<N>.json, `--report` prints the summary.
- **Memory rebuild, Phase 1 (11-01 evening)**: working memory (`jarvis/core/workmem.py`). Every tool call's real
  paths become "things" (kv `workmem_things`); "it / that image / the folder" resolve to them (0 tokens); a numbered
  list of real paths is a choice ("2", "the second one"); KURAMA's own question/offer (any channel or alert, 10 min)
  routes a short reply by the QUESTION's meaning (route method `answer`); history replies carry
  `[tools this turn: ...]` (last 2 only); the laptop chat resumes after a restart. Keys/passwords: a private file
  (.env, *.pem, id_rsa...) or a highlighted key is never context, never sent. Watch: route method `answer` with
  wrong tools, `choice` intents, a "Things from this chat" line naming the wrong file, BARE replies after a question.
- **Memory rebuild, Phase 2 (11-01 night)**: task graph (`jarvis/core/taskgraph.py`, config.TASK_GRAPH; False =
  the old chains). Trace `plan.method` rules / learned / llm; agent `last.steps` = status per step (ok / failed /
  skipped / waiting / after), `last.replanned`. Steps run without chat history, shortcut first when the steps they
  need made things. Watch: steps "failed" that really worked (a tool answering "error"-like text), "skipped" chains,
  filler dropped wrongly (FILLER_EXAMPLES), learned plans reused for a different request (data/learned_plans.json,
  TASK_PLAN_MATCH 0.93), "close X" asking when it shouldn't.
- **Phase 3 (11-01 night)**: Gemini (`gemini-2.5-flash`, then `gemini-flash-lite-latest`) answers after Groq's
  gpt-oss models and before qwen; a model that answers 429 past the wait limit is skipped (`llm._cool`, log
  "is rate-limited: skipped for N s"). Token cuts: short single actions end on the tool's own sentence (no second AI
  call: config.DIRECT_REPLY_SINGLE); the text tool joins an AI request only when it means the open file
  (`_about_context`); "send hello to telegram" = 0-token `tg_message`. Watch: llm entries with gemini (Groq used up),
  a short action whose reply should have been worded by the AI, a request about the open file answered without the
  text tool, tg_message sending words that meant a thing ("send the result to telegram").
- Watch: `path: fastpath` traces with intents tab / tabs / desktop / colab / links / clean (meaning actions taking
  the wrong request), "llm" entries with model qwen (the fallback in use = daily limit reached), hang.log dumps,
  stt.log lines with no trace (speech heard but not sent).

## Watch in the next report (11-06: request kinds, Claude Code watch, Telegram)

- **The request KIND (core/querykind.py)**: help / explain / again / Nepal documents are decided first. In traces:
  `find_capability` (help), `explain_self`, `nepal_docs` with `path: fastpath`. Wrong kind = a question that DID
  something (a help question with an action tool), or a command answered with "say ...". Fix by
  `config.QUERY_OPENINGS` / `LANE_EXAMPLES["nepal"]` examples, never word rules.
- **Nepal documents**: `nepal_docs` traces should cost 0 tokens and their job finish in 5-15 s. A live-data question
  (news, prices) going there, or a law question going to the web, is a lane example to add.
- **Claude Code watch**: `data/claude_watch.json`. `/claude say` must go into the VS Code chat (editor link v5+, after
  a window reload) or a visible terminal window ("Opened Claude Code in a terminal window"), never hidden. A ❓
  question that `/claude yes` didn't release: check the hook got `PermissionRequest` (status "waiting for you").
  The finished message must carry the whole answer (Stop hook `last_assistant_message`).
- **Telegram**: long replies must arrive whole (folded "show more", .md file when very long); screenshots in ~1-2 s
  (IPv4 only: `config.TELEGRAM_IPV4`). The bot log `data/logs/worker_telegram_bot.log` has "answered '<cmd>' in N s".
- **Offers**: "Say yes to send it to your Telegram" / "clean your RAM": a bare "yes" within 3 min must run it at 0 tokens.

## Watch in the next report (round 2)

- **Meaning actions taking the wrong request**: a link saved under a wrong name (a word of the request taken as the
  name), copy-path / VS Code / clean actions firing on something else. Look at `path: fastpath` traces with intents
  `links`, `copypath`, `openpath`, `clean`, `jobs`. Fix by examples (`MEANING_SHORTCUTS`), never by word rules.
- **Retries that cost tokens for nothing**: `retried: 1` traces whose second answer is the same (the claim check or
  the data-area rule fired on a real answer). The server log has "junk-looking stream held (garbled|kept)".
- **Talk mode**: room talk now answered (a TV line taken as a request), or your speech still ignored. Compare
  `data/logs/stt.log` lines with traces (a recognition with no trace = ignored or dropped).
- **RAM**: `data/logs/worker_resource_guard.log`. Core should stay near 390 MB with the model loaded, ~140 MB without.
  Answers "Left the background apps running" = you said no to closing idle apps.
- **Hold-to-talk (Alt since 11-01)**: `data/logs/ptt.log`. The hidden panel is preloaded and never closed
  ("panel page ready (shown=False)" ~8 s after start), so "Getting ready" should only appear right after a restart.
  In VS Code a lone Alt may focus the menu bar (`window.customMenuBarAltFocus`).
- **Window freezes** ("KURAMA-mini is not responding", 11-01 09:17 after a burst of hold-to-talk presses: the window's
  main thread blocked on a lock while another of its threads ran at 100% CPU; no stack could be read: ptrace is
  off on this laptop). Now `hang_guard` in the window script writes every thread's Python stack to
  `data/logs/hang.log` after 20 s frozen and exits; `kurama-wallpaper.sh` starts a fresh window. The report's
  "Window freezes" section shows the last dump: that stack is the root cause to fix.
- **Still open from round 1**: Alt-Tab pressed but no switch (needs a look at what the window manager did); the AI
  sometimes refuses with its tools in hand ("I can't save without a URL"): more 0-token meaning actions are the fix.

## Do it yourself (without Claude)

The routine (every 2-3 days, ~15 minutes) is in LEARN.md section 20. Handy queries on `data/traces.db` (open it with
`venv/bin/python` + `sqlite3`, or any SQLite viewer):

```bash
# tokens and AI requests per day
venv/bin/python - <<'PY'
import sqlite3; c=sqlite3.connect("data/traces.db")
for r in c.execute("select day, count(*), sum(tokens), sum(path='ai'), sum(path='fastpath') from traces group by day order by day desc limit 7"): print(r)
PY

# multi-step requests and how their steps ended
venv/bin/python - <<'PY'
import sqlite3, json; c=sqlite3.connect("data/traces.db")
for i, t, p in c.execute("select id, text, plan from traces where path='multi' order by ts desc limit 15"):
    p = json.loads(p or "{}"); print(i, p.get("method"), p.get("steps"), t[:60])
PY

# which models answered (gemini / qwen = Groq used up) and which failed
venv/bin/python - <<'PY'
import sqlite3, json, collections; c=sqlite3.connect("data/traces.db"); n=collections.Counter()
for (l,) in c.execute("select llm from traces where ts > strftime('%s','now','-3 days')"):
    for x in json.loads(l or "[]"): n[(x["model"], x["ok"])] += 1
print(n.most_common())
PY

# what KURAMA remembers right now (working memory) and a waiting choice
venv/bin/python -c "from jarvis.core import workmem; print(workmem.things()[:5]); print(workmem.choice())"
```

Rules that keep fixes healthy: fix the class (every phrasing, every tool of that kind), by meaning (examples, tool
descriptions) before words, a test with 3+ of your real phrasings, the full suite + the scorecard green, one live
check, a line in PROGRESS.md and in the Fix history.

## Known shortcuts that are still word patterns (replace them by meaning when touched)

`fastpath.link_play_intent`, `fastpath.clean_intent`, `fastpath.to_file_intent` (since 11-01 the "into the file" part
must be in the same clause as the write request: "create folder X and open it in vs code" is two tasks),
`fastpath._code_not_file`, the "this video now" rule in `video_dl_intent`, the filler-word list in
`tools/general/video_download.py`, the Telegram message extraction (`fastpath.tg_message_text`: which words are the
message; the action itself is chosen by meaning), the reference nouns (`workmem._NOUNS`, `focus.is_anaphora`).

## Which document to update (after every fix)

| Document | Update when |
|---|---|
| `PROGRESS.md` | every step: what was broken, the proven cause, the fix, the tests / live check (append) |
| `MONITORING.md` (this file) | a new log or report section, a new class of problem in the fix table, the Fix history line |
| `docs/HANDOFF.md` (top section) | the current state changes: what is done, what is next, open decisions |
| `docs/FIX_PLAN.md` | a planned step is done (mark DONE) or a new plan is agreed |
| `docs/NIGHT_SHIFT.md` | Night Agent / heavy-tool steps are done or decided |
| `LEARN.md` | a new layer, a new kind of mechanism, a moved / renamed core file (keep the map true) |
| `CLAUDE.md` | only when the owner changes a rule |
| `COMMAND.md` | never by Claude (the owner's own file) |

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
- 2026-11-01 08:10: the freed meaning model is loaded before routing (no more word-routing on the first request
  after idle); save / list links by meaning with the name taken from the left-over words; saved-things areas
  never answered from old replies. Watch: links saved under a wrong name (a word of the request taken as the name).
- 2026-11-01 08:45: one shared embedding-model process (the 611 MB core alert was two copies); talk-mode greetings
  by meaning; free RAM offers idle windowless apps (asks); /clear ram|storage|kurama. Watch: resource_guard log,
  "Left the background apps running" answers.
- 2026-11-01 19:15: memory rebuild Phase 1 (working memory, answers to KURAMA's questions by the question's meaning,
  choices, tool lines in history, laptop chat resumes) + private files/keys never in context (a 'yes' with .env open
  printed the Groq key). Test fixture time bomb fixed (Telegram tests went stale once the suite ran > 4 min).
- 2026-11-01 19:45: memory rebuild Phase 2: task graph (steps with real inputs/outputs, shortcut-first steps, no
  history per step, checked steps, one re-plan, skipped-with-reason, follow-ups after jobs, learned plans, filler by
  meaning, close only what the plan opened); new folder in a named real place (0 tokens); "Done. Folder X created in
  Downloads" with no tool is now caught as a claim; "list files in this folder" is its own task.
- 2026-11-01 20:20: memory rebuild Phase 3: Gemini fallback (after gpt-oss, before qwen), used-up models skipped
  (cooldown), direct replies for short single actions, text tool only by meaning, 0-token Telegram message.
- 2026-11-01 20:35: LEARN.md rewritten for the rebuild (short-term memory, task graph, models, tokens, privacy, the
  do-it-yourself routine); the trace's `plan` column now holds step results and re-plans, and the report shows
  multi-step problems, answers routed by KURAMA's question, choices and models. Fixed: "create a folder X in
  downloads and open it in vs code" was taken as "write code into the file" (one request) instead of two tasks;
  root folders ("/") are never remembered as "it".
- 2026-11-01 20:55: Telegram photos shrunk to 1280 px JPEG before upload (354 -> 73 KB), uploads on their own
  connection, every upload logged with its speed (`grep "telegram upload" data/logs/server.log`).
- 2026-11-01 21:25: music controls by meaning while KURAMA's player is on (pause / continue / next / volume max...);
  volume/brightness max-min words; the learner no longer takes a plain next request for a correction (wrong vetoes
  removed). Watch: `learned.json` rows with src correction (each should be a real correction).
- 2026-11-02 08:50: the window's web process: open-file limit raised + leak guard (hang.log "web process has N open
  files (kinds)"), mini chat self-reload, wallpaper pause re-sent (idle CPU 25-60% -> 0%). Watch: hang.log open-file
  lines after voice use (they name the leaking file kind), "panel page not ready ... restarting" in ptt.log.

- 2026-11-02 09:30 (master plan phase 0, docs/MASTER_PLAN.md): Gemini's thought signatures kept through the tool
  round (every Gemini call after a tool answered 400 "missing a thought_signature"), a used-up Gemini quota is not
  retried and stays skipped until it resets (per day: 1 h; else its retryDelay), flash-lite in the voice chain, a
  refused key is said plainly, a window started by hand goes through the restart loop. Watch: llm entries with
  "thought_signature" (should be none), two 2.5-flash 429s in one trace (should be one per hour).
- 2026-11-02 09:55 (master plan phase 1): lanes by meaning (jarvis/core/lanes.py, config.LANE_EXAMPLES). A confident
  general request (chat, knowledge, feelings) = route method `general`: one call on the voice tier, no tool schemas;
  a general request after "What can I do for you?" is no longer routed as an answer to it. Small talk in several
  parts ("Hello, bro. How are you?", "Thanks. Thanks.") = template; Roman Hindi / Nepali greetings added. Unsure
  speech (foreign label, low confidence) that means nothing to any lane -> "Sorry, I didn't catch that" at 0 tokens
  (agent._unheard, STT_UNSURE_LANE_MIN). Watch: route `general` traces that needed a tool (retried: 1 = the
  refusal retry rescued it), intent `unheard` on real speech.
- 2026-11-02 10:00 (master plan phase 2): each tool waits for its own usual run time (most of its last 20 real runs
  +25%, 3-8 s; kv `tool_run_seconds`, safety._wait_for) before "That's taking a while"; a tool-less answer that MEANS
  "done" (config.CLAIM_EXAMPLES vs NOT_CLAIM_EXAMPLES) is retried with tools like the worded claims; "generate a
  random image (and send it to Telegram)" and image typos are one 0-token generate_image. Watch: retried: 1 on real
  answers (a false claim by meaning), "That's taking a while" on tools that usually finish in < 8 s.
- 2026-11-02 10:15 (master plan phase 3): 0-token commands the traces sent to the AI: volume to N (also > 100, "make
  / keep"), "more volume", close all tabs (= the browser), list the tabs in any wording, key combos with "and /
  together". A name-slot meaning action needs the word all its examples share ('Open sitting.' switched to a tab
  named "sitting"). apps(action=tab) with no name lists the tabs (was "tab:None"). Watch: intents tab / tabs / close
  on requests that meant something else.
- 2026-11-02 10:35 (master plan phase 4): names are resolved or KURAMA asks. A longer / differently numbered name is
  never another folder ('project_3' opened Project, 'project3' ~ clz_project); two folders that fit the same words
  are a numbered choice ("I found more than one 'kurama'. Which one?"), the pick is remembered for those words
  (kv path_picks); open_folder offers look-alikes instead of opening the closest; 'this / that / here' is never part
  of a folder name; weather 'here / my place / near me' = home, a misheard own place by spelling (Nepal guns =
  Nepalgunj); app names that sound the same ('sitting' = Settings); 'remove second' / 'delete 2' act on the list
  KURAMA showed last (links, read later, to-do). Watch: "Which one?" on names that should be clear (delete a wrong
  pick from kv path_picks), intent changes from todo to saved_links / read_later.
- 2026-11-02 14:35 (master plan phase 5 + the owner's test session): the window froze for good every 2-8 min since
  08:45 -> JSC_SIGNAL_FOR_GC=40 (proof below in PROGRESS); invisible hold panel shrunk (no empty glass box);
  the chat page preloads in an invisible 1x1 panel (no "Getting ready" on the first hold); the background note is
  never spoken; "type X then press Enter"; "open A and B" opens both; "Ok, <request>" is not a yes; "replace it"
  while the improve still runs applies it when ready; sports: league scoreboard games (playoffs) + first team of
  "A vs B"; "this project" = the VS Code project when VS Code is in use; chart / graph / plot = the latest picture
  ("send graph on telegram" sent the word); only the chart kind asked for; dictation reads the raw mic and logs
  "dictation ... audio, stt ..., waiting" lines in stt.log; hold-to-talk "stop dictation" works during dictation.
  Watch: hang.log "Timeout" (should be none), stt.log dictation lines (stt time / waiting > 0 = lag source).
- 2026-11-03: owner session 17:57-18:07. "open browser" = the system default browser (xdg-settings), and a word the
  owner names for an app is kept (apps action `name` -> data/app_names.json; "I'll remember that" with no tool is now
  a claim -> retried). A song title alone ("play us mod se shuru kare") plays at 0 tokens (meaning-gated); the AI
  keeps the title in the query. Music never spills to a background job under 12 s; it starts at 100 (mpv's cubic 60
  was ~-13 dB) and keeps the user's last music volume; a song started while ducked gets the right volume once mpv
  answers. Alt: only modifier keys spoil a solo Alt press; a spoiled press logs "alt ignored: a shortcut (...)" in
  ptt.log. Watch: ptt.log "ignored" lines when Alt seems dead; whole-system volume drop was NOT reproduced (echo
  canceller measured at the same level) - note the time if it happens again. Later: time / date / battery / git
  status / daily summary and "when I say X, open Y" are meaning shortcuts (0 tokens); "Hello, bro." small talk.
- 2026-11-03 (evening): KURAMA learns from the owner's feedback. Every reply in the chat has 👍 / 👎 (POST
  /api/v1/feedback). An AI request done with one safe tool becomes a 0-token learned shortcut after a 👍 or two
  clean runs (words also in an argument are slots: 'tell me the wikipedia summary of X'); a 👍 plain answer is kept
  for a nearly identical question (never today / news / prices). 👎 removes what served it, vetoes that shortcut for
  that meaning, and pre-fills "No, I meant " so the correction teaches the right way. The report starts its
  learning part with the 👎 list, learned-shortcut savings per day and Groq's prompt-cache reuse (llm_calls
  .cached_tokens). Watch: 👎 lines first; `/learned_shortcuts` for anything learned wrongly (forget N).
- 2026-11-03 (night): learning only from the owner: 👍 / 👎, praise or a complaint in the next message (each becomes a
  feedback row; a spoken one keeps the words as its note), a correction that says what to do (taught). Silence
  teaches nothing. "When I say X, <command>" is kept forever (my_words.json). Watch: feedback notes ("wanted: ...")
  and `/learned_shortcuts list` for anything taught wrongly.
- 2026-11-03 (late): learning gaps closed: per-channel judging, a new task after a complaint is not taught, failing
  learned shortcuts switch off (shown in /learned_shortcuts), late complaints find their reply, misheard speech is
  never feedback, reply rules reach every AI reply (on the request itself), 👍 on multi-step replies keeps the plan
  and each clear step. Watch: /learned_shortcuts for "off: its tool failed", feedback notes on late complaints.
- 2026-11-03 (21:40): sound through Bluetooth stays on Bluetooth with KURAMA (the echo canceller had sent it to the
  laptop speaker and KURAMA had written the laptop speaker as the system's remembered output). Watch: if sound
  is quieter with KURAMA, `pactl list short modules | grep echo` (sink_master=) and
  `pw-metadata 0 default.configured.audio.sink`.
- 2026-11-03 (21:45): FRESH START - full reset (backups in data/reset-backups/20261103-214142). Traces start again
  from here; learning starts empty and grows only from the owner's 👍 / 👎 / words. Routine: docs/LEARNING.md
  section 18.
