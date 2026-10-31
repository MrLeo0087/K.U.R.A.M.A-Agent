# Night Shift Agent + heavy tools — build plan (agreed with the owner 2026-10-31)

Goal: KURAMA does big, multi-step jobs on its own, by day on request and overnight from a queue, within token and
time budgets, safely, and reports the result. Only KURAMA can do this: it lives on the laptop (files, terminal,
VS Code, browser tab, training runs), runs all day, and reaches the owner's phone (Telegram).

## Rules for every part
- Build in steps; each step leaves KURAMA working and is tested (unit tests with fakes + one live check), committed,
  recorded in PROGRESS.md; then stop for the owner to test.
- Tokens: local work first (0 tokens: reading files, searching, parsing logs/errors, diffs, running code/tests,
  comparing numbers); send the AI only the relevant piece; small model (fast tier) for summaries/decisions, big model
  (smart tier) only to write/fix code; patches not whole files; error memory + caches; every job has a token cap and
  asks first above config.AGENT_ASK_ABOVE_TOKENS (4k). Requests go through llm.chat + the shared rate limiter
  (background priority, never starving interactive replies).
- Safety: never delete, never install packages unless the job's plan allowed it, never push to git, send only to the
  owner's own Telegram; code changes only in a Safe Copy, applied by the owner's yes; hard caps on time and tokens.
- RAM: 8 GB laptop; one CPU-heavy job at a time; lazy imports; nothing loaded while idle.
- Reuse what exists: jarvis/core/jobs.py (background jobs, progress, then_send), ratelimit.py, training.py +
  workers/process_watch.py (Training Guard), kaggle_gpu.py, errmem.py, coderun.py, timemachine.py (snapshots),
  automation.py (download/backup), ytdl.py, lecture.py, study.py, notes.py, datacheck.py, diskclean.py, notify.py,
  jarvis/agents/ (agent framework) and jarvis/agents/coding/ (changes.py = staged change + undo, blocks.py = code
  blocks -> safe patches, fixer.py = crash -> fix, project.py = templates).

## Step order
### Foundation (0 tokens except the Brain)
1. **Long Job Engine** (DONE 2026-10-31: jarvis/core/longjobs.py, see PROGRESS.md): durable jobs that survive crashes and KURAMA restarts (state + checkpoints in SQLite/data),
   resume, per-job time/token caps, pause on low RAM / battery < 30% / not charging (night), step log, cancel.
   Extends jobs.py; never blocks the voice loop or chat.
2. **Safe Copy**: a job works on a copy of the project (git worktree when it's a git repo, else a copy in
   data/sandbox/<job>); at the end one diff (workspace) + "apply" (with undo, via agents/coding/changes.py) or discard.
3. **Agent Brain**: a reusable loop: goal -> short plan (1 small call) -> run tools -> check results locally ->
   re-plan only when something unexpected happens -> stop when done / stuck (same failure twice) / out of budget.
   Keeps a short run memory (what was tried and why it failed) so it never repeats a failure. LangGraph like the agent.

### Heavy agents (each useful by itself, built on 1-3)
4. **Experiment Runner** (ML): run the owner's training script with several settings (local CPU, Kaggle GPU via
   kaggle_gpu.py); read metrics from logs locally; compare; keep the best model; chart; 1 small call per round to
   choose the next settings (~300-800 tokens/round).
5. **Make-It-Run**: a folder or GitHub repo -> read README -> .venv (asks before installing) -> run -> error -> fix
   (fixer.py, in the Safe Copy) -> run again, up to N tries -> "how to run" note (~0.5-1.5k tokens per error).
6. **Test & Fix**: run the tests, fix failures in the Safe Copy, one diff.
7. **Doc Writer**: map the project locally, small summary calls per file group, then README / docstrings (~3-8k, asks).
8. **Research**: web search -> fetch pages -> extract text locally -> small-model summary per page (~150 words) ->
   one final note with sources into ~/Notes (~8-15k, asks; good night job).
9. **Study Builder**: PDF / notes / lecture recording (Whisper) -> summary + flashcards + quiz per section; daily review
   questions on Telegram (~2-5k per chapter).
10. **Media Worker**: playlists / lectures download, transcribe, convert, compress (0 tokens; optional summary).
11. **Data Doctor**: dataset checks + cleaning + charts locally (pandas), 1 short explanation call.
12. **Laptop Keeper**: backups, cleanup list, duplicate finder, update report (0 tokens; never deletes by itself).
13. **Project Guardian**: when code breaks, bisect over KURAMA's timemachine snapshots to find the breaking change,
    then one fix call.

### Night Shift Agent (last)
- **Input**: by day, text / voice / Telegram ("tonight: ...", `/night add ...`, `/night list`, `/night start`,
  `/night cancel <n>`); before the shift KURAMA shows the plan (tasks, est. time + tokens, total vs what's left
  today) and waits for a yes or an edit.
- **Process**: scheduler worker; one CPU-heavy job at a time, network jobs alongside; AI calls spread to stay under
  the per-minute limit and the night's token cap; keeps the laptop awake while running (needs the charger), lets it
  sleep after; each task = Agent Brain loop (do -> check -> fix -> retry up to 2 -> note why and move on); hard end
  time (e.g. 6:30 AM); everything logged; unfinished tasks can carry over.
- **Output**: morning report on Telegram + dashboard (per task: done/failed, results, file paths, chart, tokens and
  time used, changes waiting for a yes with their diff); files under data/outputs/night/<date>/.

## Open decisions (ask the owner before the step that needs them)
- Night start: fixed time (e.g. 11:30 PM), when the laptop is locked at night, or only on "start night shift".
- Confirm that code changes at night go to a Safe Copy and are applied in the morning with one yes.
- AI provider for the night: Groq (what's left of today + the next day's budget after the reset) or a second provider
  with its own account (e.g. Gemini API free tier: Flash / Flash-Lite; read the real limits in Google AI Studio;
  CLAUDE.md currently says Groq only). NEVER rotate several Groq accounts/keys to get past limits (refused: Groq terms).
- Which heavy agents the owner wants first after the foundation (suggested: 4 Experiment Runner, 5 Make-It-Run).
