# KURAMA: handoff for a new session

## CURRENT STATE (2026-11-01) — read this first
Owner's working rules (strict): limited budget on BOTH sides (Groq free tier for KURAMA, and the owner's Claude usage
for you) -> read the issue, PROVE the root cause with evidence (traces, side logs, code, a reproduction) before
changing code; no guessing / repeated attempts; one step at a time, each step leaves KURAMA working, then STOP for the
owner to test. Fix the CLASS of problem, never one sentence. Routing by MEANING, never new word rules. You may restart
KURAMA (scripts/kurama-power.sh off; on — run it from a script file: a command line that contains the window script's
name gets killed by its pkill). Don't drive the owner's screen (no clicks / typing / selecting); offscreen WebKit
checks and reading the screen region are fine. COMMAND.md and jarvis/core/diagram.py hold the owner's own uncommitted
edits: never commit or overwrite them.

### How to find problems
`MONITORING.md` has the paste-in prompt, every data source and the fix table. In short:
`venv/bin/python scripts/trace_report.py --days 3` (traces + side logs: data/logs/stt.log, wake.log, ptt.log, fm.log,
the job list), `--show <id>`; live check: `curl -sN -X POST http://127.0.0.1:8000/api/v1/chat -H 'Content-Type:
application/json' -d '{"text":"..."}'`; tests `venv/bin/python -m pytest -q` (~1100, ~2.5 min; related files first);
scorecard `venv/bin/python -m tests.eval.harness` (65% instant / 100% right / 98% router: must not drop).

### Done 2026-10-31 / 11-01 (details: PROGRESS.md, MONITORING.md "How KURAMA works now")
Night Shift step 1 = Long Job Engine (jarvis/core/longjobs.py). Mini UI v4 (glass via Blur my Shell, Look controls,
Inter font, job strip, tiny header, hold Alt to talk (was Ctrl until 11-01) / double-tap Shift to close, KURAMA Settings > Shortcuts).
FIX_PLAN steps 1-6 all DONE (docs/FIX_PLAN.md). Job list (jarvis/core/jobqueue.py: add/edit/remove/start, Telegram
questions, retries, notices). Files app context (scripts/kurama_fm.py + jarvis/core/filemanager.py). Telegram: one
upload try (no duplicates), big folders as gofile.io links. New side logs for evidence.

### Done 2026-11-01 morning (trace report round 1; details: PROGRESS.md, MONITORING.md "Since 11-01")
Link store through the AI + 0-token save/list by meaning; model loaded before routing; one shared embedding process
(the 611 MB alert); fake "done" claims and saved-things answers retried with tools; junk streams replaced; talk-mode
greetings by meaning; free RAM / `/clear ram|storage|kurama`. `LEARN.md` = the architecture guide for the owner.

### Done 2026-11-01 afternoon
Test round 1 + its fixes, tabs / scroll / home screen / Super key, Colab-Kaggle cell, Ctrl+Alt+L focus toggle,
clipboard kept, qwen fallback, hang guard. Details: PROGRESS.md (11-01 entries), MONITORING.md "Since the last
report". The owner now uses KURAMA for a few days; the next session reads the traces (MONITORING.md prompt).

### Unproven / watch in the next report (see MONITORING.md "Watch in the next report (round 2)")
- Hold-to-talk: a caption auto-hide timer fired during a hold (ptt.log); hides are now blocked while Ctrl is held and
  logged with their caller — find which timer it was.
- Files: with two windows on the same folder the TOP one is matched by creation order (one data point); fm.log "pick".
- Wake word after the phrase fixes and the mic at 70% (wake.log).
- The AI sometimes answers from chat history without calling the tool ("too large" with no tool) — the honesty retry
  doesn't catch refusals.
- gpt-oss occasionally streams a garbled reply ("Folder … has been … It seems…").

### Next (ask the owner which; one at a time)
1. After 2-3 more days: trace report round 2 (MONITORING.md prompt + its "Watch" list).
2. Night Shift steps 2-3 (docs/NIGHT_SHIFT.md: Safe Copy, Agent Brain), then heavy agents. The owner wants the job
   list as the night agent's input, started by hand (no timer), and advanced tools later.
3. Old open items: merge the coding agent into normal tools; offline /commands for every tool.
4. Providers: CLAUDE.md says Groq only. Rotating several Groq accounts/keys was REFUSED (Groq terms) — don't build it.

---


Read this, then CLAUDE.md (hard rules) and the tail of PROGRESS.md. Don't re-explore the repo; grep for what you need.

**v2 (2026-10-29):** the AI sees 17 general tools (`jarvis/tools/core/`) that call the specialised tools; to-dos are
their own table; Reset KURAMA is a factory reset. Every request is traced in `data/traces.db`: read `MONITORING.md`
for the data and the report. User guide: `COMMAND.md`. Scorecard: `venv/bin/python -m tests.eval.harness`.
Some details below predate v2 (test counts, tool counts); trust the code and PROGRESS.md.

## What it is
KURAMA (formerly Jarvis; the user-facing name is changeable, default KURAMA, never "Jarvis" in UI/replies) is an
always-on personal voice/text assistant on the owner's laptop. It runs on Ubuntu 24.04 on X11 (an Acer Aspire A14),
with no GPU and 7.5 GB RAM. It uses English, Nepali and Hindi, and only free services: Groq (LLM + Whisper STT),
edge-tts, Open-Meteo, DuckDuckGo, Google News RSS and Cloudflare image workers. The Python package is still `jarvis/`.
Repo: /media/leo/Project1/New_project/KURAMA, branch master. The venv is Python 3.12 (`venv/`). 523 tests pass
(`venv/bin/python -m pytest -q`, about 35 s).

## How it runs
- **API server:** `venv/bin/python -m jarvis.server --port 8000` (FastAPI, `jarvis/api/`). It also serves `frontend/`.
- **Workers:** `venv/bin/python -m jarvis.workers` runs one supervisor process with these threads: scheduler
  (reminders), telegram_bot, resource_guard, crash_watchdog, process_watch, daily_digest and auto_theme.
- **Live wallpaper:** `scripts/kurama_wallpaper.py` uses the SYSTEM python3 (GTK3 + WebKit2 4.1, Wnck). It is a
  desktop-type window showing `/?wallpaper=1`.
  - It pauses the page (`window.kuramaPause`) while a maximized window covers it.
  - Minimize gives a floating DOCK bubble plus a mini chat panel (`/?mini=1`). The panel shares the web process
    (related-view) and is dropped after 3 minutes hidden; its chat is restored from localStorage.
    In talk mode, closing the panel keeps it alive (invisible, click-through) so talking goes on: the button's
    ring shows the voice state and a caption beside it shows what was said and the reply (`Caption`).
  - It saves a dashboard snapshot to `~/.local/share/kurama/desktop.png` every 10 minutes and uses it as the GNOME
    background and as a startup cover, so login shows KURAMA instantly. The real wallpaper is stored in
    `real-wallpaper.json`; `set_wallpaper.current()` reads it from there.
  - The WebKit memory budget is 320 MB.
- **Launch:**
  - `scripts/kurama-wallpaper.sh [stop|--window]` starts the window first and the API in parallel. `stop` restores
    the real wallpaper.
  - `scripts/kurama-login.sh` starts the workers and the wallpaper.
  - Autostart: `~/.config/autostart/kurama-wallpaper.desktop` → `~/.local/bin/kurama-autostart`. That script waits
    for the project drive and respects the off flag. Installed by `scripts/install_wallpaper_autostart.sh`.
- **Power:** `scripts/kurama-power.sh on|off|toggle|status`.
  - `off` kills every KURAMA process (0 RAM/CPU) and sets `~/.local/share/kurama/off`, which survives a reboot.
  - You can also use the UI ⏻ button (click twice, `POST /api/v1/power/off`), Super+K, or the "KURAMA" app icon
    (`~/.local/bin/kurama-power`).
- **Project drive:** `/media/leo/Project1` (nvme0n1p3, ext4, UUID dc023c08-16b5-44f8-a090-81b64caf06de) is NOT in
  fstab yet. The user was given the line to add (`defaults,nofail,x-gvfs-show`). Until then KURAMA can't start at
  login.
- **Voice loop (optional):** `scripts/jarvis-start.sh`.

## Architecture (key files)
- **`jarvis/core/config.py`:** the only place for model IDs, ROUTER_RULES keywords, TOOL_GROUP_DESCRIPTIONS/GLOSS and
  limits.
  - Groq models (the Llama models are retired): smart tier openai/gpt-oss-120b, fast tier openai/gpt-oss-20b, voice
    and vision tier qwen/qwen3.8-27b; STT whisper-large-v3-turbo.
- **`agent.py`:** a LangGraph StateGraph (route → llm ⇄ tools; planner with Send fan-out for multi-task requests,
  chain/join nodes).
  - History is 6 turns plus a rolling summary.
  - The Telegram chat resumes after a restart (`_resume`).
  - `notify.context_line` adds "messages you sent the user" only when relevant.
  - The system prompt must stay under 250 tokens (a test enforces it).
- **`fastpath.py`:** zero-token regex intents for open, volume, math, news (web_search), image, wallpaper, self-knowledge, password
  unlock, gesture, digest and more. `planner.py` splits multi-task requests. `router.py` uses keywords first, then the
  fast-tier classifier, and sends only 1–3 tool groups (at most 5 tools per group). The meta tool `request_tools`
  must stay under 200 tokens (a test enforces it).
- **Other core modules:**
  - `jobs.py`: background jobs → `data/outputs/`. Done/failed jobs go to Telegram.
  - `reminders.py`: due reminders, a heads-up 10 min before (`REMINDER_LEAD_S`), and a missed notice if more than
    1 h late.
  - `notify.py`: desktop, Telegram and the SQLite alerts table.
  - `store.py`: SQLite (sessions, messages, alerts, schedules, kv, tool logs, tokens).
  - `identity.py`: the name. `selfknow.py` plus `docs/kurama_self.md`: self-knowledge; sections marked `[locked]`
    need the owner password, stored only as a salted sha256 hash in config.
  - `paths.py` `all_disks()`: home plus every mounted data disk.
- **Tools:** `jarvis/tools/{general,interactive}/<one file per tool>.py`, registered with
  `@tool(group=..., safety="safe|confirm|blocked")`. Notable tools: generate_image (IMAGE_APIS list, then Pollinations),
  find_files and send_file_telegram (path or name; whole-laptop search; numbered picks "2"/"all" handled by the bot
  at 0 tokens), calculate (math, units, currency), cleanup_scan, gesture_control, about_me, find_capability,
  set_my_name, set_wallpaper, open_url (find_site falls back to a DuckDuckGo jump).
  - Step 0 cleanup (108 -> 81 tools): small tools were merged into one tool with an `action` (audio, clipboard,
    jobs, skills, schedules, window, git_info, git_change, repo_check; auto theme -> set_theme, currency ->
    calculate, find_and_send -> send_file_telegram, playlist -> media_control, focus_timer -> focus_mode). The old
    names still work through `registry.alias` / `registry.resolve` (fast path, Telegram bot, saved commands) but are
    never sent to the LLM. Removed: add_docstrings, benchmark_table, read_aloud, news_headlines, n8n (tool + worker).
- **Gesture control:** the user's module is at
  /media/leo/Project1/Project/Gen_AI/Big_project/02_K.U.R.A.M.A/Version_4/Extra_tools_file/Youtube_vision_control.
  It runs unmodified in `data/vision_venv` through `scripts/gesture_runner.py` (xdotool keyboard shim).
- **API** (`jarvis/api/routes/`): chat (SSE), confirm, stt, tts, status/stream, jobs, alerts, tools, weather, outputs,
  wallpaper(/info), identity, device ("This laptop" card), power/off.
- **Frontend** (`frontend/`, plain ES modules, no build step): `app.js` (controller), `api.js`, `voice.js` (Mic,
  Recorder, Player, Conversation; the AudioContext closes after 20 s idle because an open one costs ~12% CPU),
  `orb.js`, `dust.js`, `styles.css`.
  - Cards: clock, weather (Nepalgunj), top processes, KURAMA core, This laptop, performance, workspace (last 8
    outputs, swipeable), conversation.
  - Header buttons: tool finder (Ctrl+K), voice mute, clear, info, settings, minimize.
  - Animations are one-shot. Infinite CSS animations are banned because WebKitGTK repaints in software.

## Added on 2026-10-24 (big session; details in PROGRESS.md)
- **Routing:** keyword rules -> `semantic.py` (bge-small by meaning, 0 tokens, plain-chat class) -> 8b classifier.
  `scripts/eval_routing.py` measures it (101 cases + 30 held-out, both 100% at the time of writing).
- **Coding/ML:** `training.py` + workers/process_watch.py (Training Guard: run/proc/log/colab via ntfy.sh, crash ->
  error memory), `cmdalerts.py` (bash hook, not installed until the owner says "turn on command alerts"),
  `errmem.py` (fix_error), `timemachine.py` (+ worker, shadow repos in data/timemachine, code/text only),
  where_was_i, `datacheck.py` (check_dataset), python_env (install into the project venv).
- **Laptop:** `doctor.py` (laptop_doctor), `netdoctor.py` (internet_doctor), `diskclean.py` (disk_cleaner),
  `automation.py` (download_file, tidy_downloads, backup), `guard.py` (+ worker; laptop_guard), `phone.py` (Telegram:
  voice notes, files in, clipboard, /screen, /guard, /where).
- **Study:** `notes.py` (study_notes, ~/Notes), `lecture.py` (record + Whisper transcript job), `study.py`
  (timetable + quiz).
- **Merged tools:** many small tools became one tool with an `action`; old names live on in `registry.alias`.
- Workers now: process_watch, resource_guard, crash_watchdog, telegram_bot, daily_digest, auto_theme, scheduler,
  timemachine, guard (n8n removed).

## Owner preferences
- Be fast and spend few tokens. Fix exactly what is asked; no long explorations; short reports.
- Build one phase at a time, then stop for the user to test. Commit at the end of each step and update PROGRESS.md.
- Idle RAM and CPU come first (the app runs all day). Never add torch or TF; lazy-load heavy modules.
- Don't drive the user's screen (no xdotool clicks or typing to test). Screenshots (scrot) and offscreen
  GTK/WebKit checks are fine.
- When a step needs sudo, print the command; never run sudo yourself. Secrets live only in `.env`; never print them.
- Watch out: `pkill -f` patterns can match your own shell command line. Build the pattern in pieces
  (`P="kurama_[w]all""paper.py"`) and run pkill in a separate command from anything that names the script.

## Open items / ideas
- **User actions:**
  - Add the fstab line.
  - Revoke the Telegram token and Groq keys that were exposed in an old chat.
  - Test gesture control with the camera, the mic/wake word, the mini panel voice, the reminder heads-up and
    sending files from the phone.
- **Git:** there is no remote yet and `gh` isn't installed. `kurama_2.zip` (217 MB) is now untracked, but it is
  still in history (commit b4c5ddc). GitHub will reject a push until the history is rewritten
  (`git filter-repo --path kurama_2.zip --invert-paths`). That needs the user's OK.
- **Possible next phase (not started):** a cloud/laptop split. The cloud part (Telegram bot, reminders, chat, alerts)
  would run on a free Oracle Always Free VM. The laptop agent would do desktop/file actions. Tailscale gives phone
  access to the laptop UI meanwhile.
- **Deferred:** P8c, P10 extras, P11, piper offline TTS, a light colour theme.
