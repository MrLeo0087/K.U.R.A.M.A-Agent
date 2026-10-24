# KURAMA: handoff for a new session

Read this, then CLAUDE.md (hard rules) and the tail of PROGRESS.md. Don't re-explore the repo; grep for what you need.

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
  (reminders), telegram_bot, resource_guard, crash_watchdog, process_watch, daily_digest, auto_theme and n8n_inbound.
- **Live wallpaper:** `scripts/kurama_wallpaper.py` uses the SYSTEM python3 (GTK3 + WebKit2 4.1, Wnck). It is a
  desktop-type window showing `/?wallpaper=1`.
  - It pauses the page (`window.kuramaPause`) while a maximized window covers it.
  - Minimize gives a floating DOCK bubble plus a mini chat panel (`/?mini=1`). The panel shares the web process
    (related-view) and is dropped after 3 minutes hidden; its chat is restored from localStorage.
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
- **`fastpath.py`:** zero-token regex intents for open, volume, math, news, image, wallpaper, self-knowledge, password
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
  find_files and find_and_send (whole-laptop search; numbered picks "2"/"all" handled by the bot at 0 tokens),
  calculate, convert_currency, news_headlines, focus_timer, cleanup_scan, gesture_control, about_me,
  find_capability, set_my_name, set_wallpaper, open_url (find_site falls back to a DuckDuckGo jump).
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
    find_and_send from the phone.
- **Git:** there is no remote yet and `gh` isn't installed. `kurama_2.zip` (217 MB) is now untracked, but it is
  still in history (commit b4c5ddc). GitHub will reject a push until the history is rewritten
  (`git filter-repo --path kurama_2.zip --invert-paths`). That needs the user's OK.
- **Possible next phase (not started):** a cloud/laptop split. The cloud part (Telegram bot, reminders, chat, alerts)
  would run on a free Oracle Always Free VM. The laptop agent would do desktop/file actions. Tailscale gives phone
  access to the laptop UI meanwhile.
- **Deferred:** P8c, P10 extras, P11, piper offline TTS, a light colour theme.
