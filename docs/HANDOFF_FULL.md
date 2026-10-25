# KURAMA — full project handoff

Paste this whole file (or point the new session at `docs/HANDOFF_FULL.md`) to continue the project.

## 0. Read these first, in order
1. `CLAUDE.md` (repo root) — the owner's hard rules. They OVERRIDE defaults.
2. This file.
3. `PROGRESS.md` (tail) — chronological log; the most recent entries are the latest state.
4. `docs/COMMANDS.md` — how to start/stop/restart and every Telegram command.

## 1. What KURAMA is
An always-on, free-stack voice + text personal assistant for one user ("Leo"), controllable from the laptop
(a holographic dashboard shown as the live wallpaper) and from the phone (a Telegram bot). The package is still
named `jarvis/` for history; the user-facing name is **KURAMA** (never "Jarvis"). It is a real daily tool the
owner uses, not a demo.

## 2. Hard constraints (from CLAUDE.md — do not violate)
- **Ubuntu on X11, NO GPU, 8 GB RAM** shared with VS Code/Chrome. Idle RSS and idle CPU matter most.
- **Never install PyTorch/TensorFlow** into KURAMA. Prefer ONNX, small CPU libs, or APIs. Heavy inference is on Groq.
- RAM budget: core idle < 600 MB, hard cap 1.5 GB. Lazy-import heavy modules (cv2, mediapipe, fastembed, playwright),
  release after use. Measure idle RSS after each phase.
- **LLM: Groq only.** Model IDs live ONLY in `config.py`: smart `openai/gpt-oss-120b`, fast `openai/gpt-oss-20b`,
  voice/vision `qwen/qwen3.8-27b`. STT: Groq `whisper-large-v3-turbo` (fallback `-v3`). TTS: edge-tts.
- **Framework: LangChain + LangGraph** are primary (the user reads them). Raw Groq SDK only where LangChain can't (STT).
- **Secrets in `.env` only** (gitignored). Never commit or print them. The owner's password is stored only as a hash.
- **sudo:** print the command, never run it yourself. **Don't drive the user's screen** (no xdotool clicks/typing to test;
  scrot/offscreen GTK renders are fine). Confirm-level actions (delete/shell/sudo/install/send email/kill) need a yes.
- **Token care (Groq free tier ~8k tokens/min/model, daily budget too):** system prompt < 250 tokens; voice replies
  1–2 short sentences; router sends only 1–3 relevant tool groups; history = last 6 turns + rolling summary;
  truncate tool output ~800 chars. Fast path (regex, 0 tokens) handles most commands. The owner's daily fast-model
  budget often runs out — expect fallbacks and keep things 0-token where possible.

## 3. Working rules for the assistant (owner's style)
- Read PROGRESS.md first; keep answers short and token-light; fix exactly what's asked.
- Do work one step at a time; **commit after each step** and update PROGRESS.md.
- Use grep/head/line-ranges, not big file dumps; don't re-read files you just wrote.
- Run only tests for code you changed; show only failures.
- Pin dependency versions; check each new dep for torch/GPU baggage.
- When ambiguous, pick a sensible default, note it, ask only if blocked.
- **Attribution on commits** (current reminder): end commit messages with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (use whatever the live system-reminder says; owner rules win).
- Tone: professional, organized, **no emojis** in KURAMA's own tool messages (the LLM prompt already forbids them).

## 4. Architecture / layout
```
jarvis/core/{config,llm,stt,tts,audio,wake,agent,memory,budget,safety,planner,router,fastpath,
             geolocate,locationlog,devaudio,guard,phone,training,reset,focus,telesec,remotedesk,...}.py
jarvis/tools/{general,interactive}/<one tool per file>   (@tool(group, safety); 140 tool files)
jarvis/workers/<one daemon per file>  (supervisor runs them)
jarvis/api/  (FastAPI: routes/{chat,voice,info,wake,dash}, turns.py=Engine, app.py, security.py, settings.py)
frontend/  (plain ES modules: app.js, orb.js, dust.js, voice.js, api.js, config.js, styles.css, index.html)
scripts/  (kurama-power.sh, kurama-wallpaper.sh, jarvis-start.sh, restart helpers, eval_routing.py)
tests/  docs/  PROGRESS.md  CLAUDE.md
```
- **Voice loop:** hotkey/wake word → VAD (webrtcvad) → Groq STT → LangGraph agent (stream) → split sentences →
  edge-tts per sentence while the LLM keeps generating → play; barge-in stops playback.
- **Routing:** `fastpath.py` (0-token regex intents) first; then keyword rules → semantic router (fastembed
  bge-small, 0 tokens) → 8b classifier only if unclear. `scripts/eval_routing.py` must stay 110/110 + 32/32 held-out.
- **Agent:** `jarvis/core/agent.py` — LangGraph route→llm→tools loop, plus a planner that fans out independent tasks
  (quick run concurrently, long ones become background jobs under `data/outputs/`). History + rolling summary.
- **Tools:** `@tool(group=..., safety="safe"|"confirm"|"blocked")`. `safety.execute` runs them; long outputs go to the
  Workspace (data/outputs). `registry.alias(old, new, ...)` keeps retired names working.
- **Workers (supervisor):** process_watch, resource_guard, crash_watchdog, telegram_bot, daily_digest, auto_theme,
  scheduler, timemachine, guard, location_tracker. All tiny (psutil+watchdog, poll ≥5 s, log rotation).
- **Store:** SQLite `data/jarvis.db` (watches, kv, errors, jobs, schedules, alerts, messages, sessions, notes,
  locations, profile) + `data/memory.db` (FTS5 + fastembed vectors). Use `store.kv_*` for cross-process state.
- **Frontend wallpaper:** `scripts/kurama_wallpaper.py` = GTK + WebKit2GTK window behind everything. WebKitGTK
  renders in SOFTWARE — only ONE animation loop (the orb drives the dust); no heavy CSS animation.
- **LLM fallback:** every tier has a second model; `llm._on_error` falls to the next model on ANY error (even 400),
  raises only when all fail. Final tool round drops tools (never sends tool_choice="none" — gpt-oss 400s on it).

## 5. Major features built (this is a mature project)
- **Voice/UI:** wake word (openwakeword-style, server listens cheaply while asleep), 3 modes (text/mic/talk),
  holographic orb + neural-dust (particles pull to the orb when you speak), redesigned symmetric HUD dashboard
  (big clock mirrored by big weather; System, Now&today, Coding, Laptop, Workspace cards; detail sheets; action
  buttons). Voice is MUTED by default (replies as text; unmute with the speaker button). Mic audio pipeline:
  anti-alias resampler, level lift, real-time VAD, Whisper-own noise rule, self-echo stripping.
- **Telegram bridge (primary phone interface):** text/voice-note chat, send/receive files, `/camera` `/video`
  `/screen`, `/clip`/`copy:`, `/where` (location), `/here` (label Wi-Fi), `/guard`, `/history`/`/track`, `/status`,
  `/jobs`, `/help`. Typing indicator; 90 s answer timeout so it can't hang. **Send folders**: zips (skips
  venv/.git/node_modules), sends directly if ≤50 MB, else uploads to **gofile.io** and sends ONE download link
  (jarvis/core/cloudshare.py). "send this folder"/"send it" use **conversation focus** (jarvis/core/focus.py).
- **File management:** find files/folders anywhere (all disks) with FUZZY matching ("final rag"/"finalrag"/
  "final drag" → Final_RAG); open a folder in the file manager by name; list folders. 0-token fast paths.
- **Location:** browser Geolocation API (Google-backed, accurate, moves with the laptop) is primary via POST
  /api/v1/location; falls back to a pinned Wi-Fi, then beacondb Wi-Fi/IP. Place names via OSM Nominatim; map links.
  Movement history (locationlog) + Leaflet trail (served at /map/<file>, Carto tiles). "find my phone" opens Google
  Find My Device. Phone trail via Telegram live-location.
- **Training watch (ML):** local runs (reads the log, 0 extra deps) and **Google Colab** (paste the KURAMA cell from
  "set up colab"; it now gives an .ipynb at data/outputs/colab/). KuramaKeras/KuramaCallback report every epoch +
  step/ETA; status is on-demand real-time and formatted (Epoch/Step/Loss/Accuracy/Remaining/Last update/Error);
  stop from the phone; crash/NaN alerts.
- **Laptop control:** open/close apps, window tiling, volume/brightness/theme/night-light/DND, screenshots, power
  (confirm), laptop_doctor, internet_doctor, disk_cleaner, downloads/backup automation, clipboard, "hear device
  sound" echo-canceller setting (default ON = no canceller, after it made speakers quiet).
- **Dev tools:** time_machine (project snapshots — "protect my project"), where_was_i, command_alerts, fix_error,
  check_dataset, python_env, run_tests, scaffold, review_code, repo_check, notebook_to_script.
- **Chat control:** `/stop` (abort + reset), `/clear` (chat+reminders), `/clearchat`, `/reset` (wipe all but
  password+settings); UI buttons; natural phrases ("clear chat", "reset kurama"). Cross-process clear via a kv
  "conversation_epoch" bump (jarvis/core/reset.py).
- **Security (Telegram):** jarvis/core/telesec.py — risky actions (shutdown/delete/shell/send file/camera/location/
  guard/remote desktop) need a PIN once per 30 min (config.TELEGRAM_RISKY_PIN, default 1500, in .env). `/lock`
  blocks everything risky until `/unlock <pin>` (TELEGRAM_LOCK_PIN, default 0087). Harmless things never ask.
- **Remote desktop:** jarvis/core/remotedesk.py + remote_desktop tool + fast path ("/control laptop", "start remote
  desktop", "real-time preview", "control my laptop from my phone") → launches **RustDesk** with unattended access
  and returns ID + password (to Telegram if asked there, else the dashboard).

- **Added 2026-10-25/26:** screen agent `app_control` (0-token app shortcuts, click by name via AT-SPI helper
  scripts/atspi_dump.py, learned replays, LLM/vision steps); `video_download` (yt-dlp + yt-dlp-ejs/deno, any
  quality, MP3, playlists); `convert_file` (pdf<->md, md->pdf via fpdf2, images, media, tables, OCR, office via
  LibreOffice if installed); `install_app` (apt/snap/flatpak, pkexec popup, confirm); `wifi_share` (LAN link + QR,
  token path, auto-stop); `contacts` (Excel sheet ~/Documents/KURAMA/contacts.xlsx); `live_search` (ESPN scores,
  Google News RSS, gold/forex/crypto/stock APIs, fresh-source answers). Remote desktop password is set via the
  root helper /usr/local/sbin/kurama-rustdesk (sudoers), expires after 15 min, only given on Telegram after the PIN.
  The messages/notification tool was built and then REMOVED at the owner's request.
- **Path memory (focus.py = current folder):** history of 10, 12 h; "this/it/here", "previous folder",
  "parent folder", bare sub-folder names, cwd-relative lookups; send refuses home/disk roots.
- **Token savers:** 0-token small talk/everyday commands, TYPO_FIXES, talk-mode ambient gate (speech > 45 s after
  KURAMA last spoke must name KURAMA or be a fast-path command), history messages capped at 420 chars.

## 6. Current in-progress / pending
- RustDesk is installed and working (helper + sudoers in place). Owner may ask for a dashboard button.
- Optional owner actions: "enable screen control" + restart Brave/VS Code (accessibility for app_control);
  `sudo apt install libreoffice-writer` for Word/PowerPoint conversions; accept Groq Orpheus terms if TTS is wanted.
- **Owner setup still open:** turn on command alerts ("turn on command alerts"); paste the Colab cell/notebook; set a
  backup drive; paste the timetable; turn on Telegram's own Passcode Lock; label home Wi-Fi with `/here`.
- The owner's Groq **daily fast-model budget often runs out** → more fallbacks/slow replies late in the day. Not a bug.

## 7. How to run / verify
- Start/stop everything: `scripts/kurama-power.sh on | off`. Status: `scripts/kurama-power.sh status`.
- Clean restart (avoids a known restart race that can leave workers stopped — if Telegram goes silent, this fixes it):
  `scripts/kurama-power.sh off && scripts/kurama-power.sh on`.
- Manual: server `venv/bin/python -m jarvis.server --port 8000`; workers `venv/bin/python -m jarvis.workers`;
  wallpaper `scripts/kurama-wallpaper.sh` (stop with `... stop`). Health: `curl -s localhost:8000/api/v1/health`.
- **Kill by exact PID**, never `pkill -f` (it matches your own shell → the agent has been killed that way before).
  A helper exists in the scratchpad: `restart.sh jarvis.server jarvis.workers`.
- Tests: `venv/bin/python -m pytest -q` (~707 pass). Routing: `venv/bin/python scripts/eval_routing.py` (110/110,
  32/32). Offscreen UI render with JS-error check: a `shot2.py` in the scratchpad injects the API token and reports
  `window.__errs`. Reload the wallpaper after frontend changes.
- Logs: `data/logs/{server.log,workers.out,worker_telegram_bot.log,wallpaper.log,stt.log}`.

## 8. Gotchas learned the hard way
- `pkill -f`/`pgrep -f` match the assistant's own command line → kill by exact PID (awk on `$2`/`$4`).
- Don't leave test artifacts under `data/outputs/` — the file finder once sent a leftover `clz_project_demo` zip
  instead of the real folder. find_and_send now excludes `config.DATA_DIR`, but clean up after tests.
- WebKitGTK is software-rendered: one-shot animations only; the wallpaper may lack browser geolocation/camera —
  for accurate location open the dashboard in Brave at http://127.0.0.1:8000.
- Telegram linkifies "x.zip" (.zip is a TLD) into a dead link — don't print raw filenames in replies.
- gpt-oss ignores `tool_choice="none"` → Groq 400; the agent drops tools on the final round instead.
- Battery auto-suspend froze the workers (Telegram went silent until a click) — it was disabled via gsettings
  (`sleep-inactive-battery-type 'nothing'`).

## 9. Where to look for the latest truth
`PROGRESS.md` tail + `git log --oneline` (each commit message says exactly what changed and why). On branch `master`; see `git log --oneline` for the latest commit.
