You are continuing work on **KURAMA**, my personal always-on voice + text assistant, in `/media/leo/Project1/New_project/KURAMA` (git branch `master`). Don't scan the whole project: this prompt, `CLAUDE.md` and the tail of `PROGRESS.md` are enough. Read files only when a task needs them, and use grep and line ranges.

## How I want you to work
- Read `CLAUDE.md` (my hard rules, they override defaults) and `tail -40 PROGRESS.md` first. `docs/HANDOFF_FULL.md` has deeper background if you need it.
- Keep answers short and simple; I'm a Nepali speaker. Do one step at a time and fix exactly what I ask. If a request is ambiguous, pick a sensible default and say so; ask only if blocked.
- After each step:
  1. run only the related tests plus `venv/bin/python scripts/eval_routing.py`; it must stay 110/110, 32/32, 27/27;
  2. append one line to `PROGRESS.md`;
  3. `git commit` ending with `Co-Authored-By: <the model named in your system reminder> <noreply@anthropic.com>`;
  4. restart KURAMA.
- Run the full suite (`venv/bin/python -m pytest -q`, ~740 tests, ~85 s) before telling me something is done. Show only failures.
- Never install torch or TensorFlow, and pin versions. Secrets live only in `.env`: never print or commit them.
- Token care: the Groq free tier is small. Prefer 0-token fast paths (regex) and local code; use 1 LLM call per request at most.
- **Never drive my screen to test** (no xdotool clicks or typing, no opening windows). Use mocked or "fake desktop" tests and say clearly what wasn't tested live. Never run commands through the live API that do real things (I once got dictation started by a test). Reading is fine.
- sudo: print the command for me and never run it yourself.

## Operating KURAMA (important gotchas)
- **Start:** `scripts/kurama-power.sh on`. **Stop:** `scripts/kurama-power.sh off`. Health: `curl -s localhost:8000/api/v1/health` (`agent_ready:true`).
- **Restart server and workers** (the safe way):
  `scripts/kurama-power.sh off; ps -eo pid,args | grep -E "[j]arvis\.(server|workers)" | awk '{print $1}' | xargs -r kill; scripts/kurama-power.sh on`
  then poll health. To also restart the screen: `scripts/kurama-wallpaper.sh stop` before `on`.
- **Never use `pkill -f` / `pgrep -f`.** Never put "kurama_wallpaper", "scripts/kurama_wall" or "jarvis.server" as plain text in the same bash command as a `ps | grep ... | xargs kill`: the grep matches your own shell and kills it (exit 144).
- Logs live in `data/logs/`: `server.log`, `workers.out`, `stt.log` (every speech recognition, with confidence), `wallpaper.log`, and `worker_*.log`. History is in `data/jarvis.db`: tables `messages` (id, ts, role, text, session), `routing` (query, groups, method, latency_ms), `llm_calls`, `tool_calls`, `kv`.
- `/media/leo/Project1/New_project/KURAMA/test.py` is my scratch file for trying VS Code features.

## Hardware and stack (from CLAUDE.md)
- Ubuntu X11, no GPU, 8 GB RAM, 12 cores. KURAMA must stay light (it measures about 405 MB with the full dashboard and about 220 MB minimized).
- **LLM:** Groq only (LangChain ChatGroq + LangGraph).
  - Smart tier: `openai/gpt-oss-120b`. Fast tier: `openai/gpt-oss-20b`. Voice and vision tier: `qwen/qwen3.8-27b`.
  - Model IDs live only in `config.py`.
  - Every tier has a fallback model.
  - Groq also has `canopylabs/orpheus` TTS, but its terms aren't accepted, so it's unused.
- **Speech to text:** Groq Whisper (`whisper-large-v3-turbo`, fallback `v3`), plus Google free web speech for Nepali dictation.
- **Text to speech:** edge-tts at +15% speed (`JARVIS_TTS_RATE`).
- **Languages:** English, Nepali, Hindi.
- **Local "understanding model":** `bge-small-en-v1.5` ONNX (fastembed) in a child process, about 250 MB while loaded. It only picks which tool group a free-form sentence needs (the semantic router) and powers search over my own notes. Settings → Memory chooses always / auto (default: load when needed, freed after 10 min) / off. With "off", keyword rules and the LLM classifier route instead.

## Architecture
- `jarvis/core/`: config, llm, stt, tts, agent (LangGraph), planner, router, semantic, fastpath, safety, store, jobs, workspace, focus, paths, plus feature modules.
- `jarvis/tools/{general,interactive}/`: one file per tool, registered with `@tool(group=..., safety=...)`. A group may hold **at most 5 tools**, and the meta schema must stay under 200 tokens: tests enforce both.
- `jarvis/workers/`: supervisor daemons (Telegram bot, scheduler, process watch, guard, location tracker, and so on).
- `jarvis/api/`: FastAPI on 127.0.0.1:8000. `turns.py` is the Engine; routes are chat, voice, info (outputs, resources, jobs) and wake.
- `frontend/`: plain ES modules (app.js, api.js, voice.js, orb.js, styles.css, index.html).
- `scripts/kurama_wallpaper.py`: a GTK + WebKit window behind the desktop that shows the dashboard. It runs with the system python3, not the venv.
- **Routing order per message:**
  1. `fastpath.match()`, regex at 0 tokens. Order: self → plan answers (pending yes/no) → ui → convert → wifi → contacts → messages... → everyday → live → ... → `fresh_intent` last.
  2. Router: keyword rules (`config.ROUTER_RULES`) → semantic router (`config.ROUTER_EXAMPLES` + `TOOL_EXAMPLES` paraphrases) → LLM classifier.
  3. The agent, with only 1–3 tool groups.
- Talk mode has an "ambient" gate: speech more than 45 s after KURAMA last spoke must name KURAMA or be a fast-path command.
- **Background jobs:** `jobs.get_manager().submit(title, kind, fn)` automatically adds the job to the current turn's watch list. If the job's final `ctx.progress("» message")` starts with `» `, the UI announces that message when the job finishes. Results go to `data/outputs/`, which is the workspace.
- **Fast-path long answers:** an answer over 700 chars, or with code or paths, goes to the workspace in full; the chat gets 2–3 speakable sentences. Voice speaks at most about 420 chars, then says "the rest is on the screen".

## UI facts
- **Dashboard (full KURAMA):**
  - Cards: clock and weather, System (click for details; it includes "KURAMA resources" per part, real PSS memory and whole-laptop CPU), Workspace (Delete one item / Clear all, both to the trash), chat with text / mic / talk modes.
  - The speaker button mutes and frees the mic instantly.
  - Settings → Memory: understanding model mode, live memory use, "Free now".
- **Mini mode (minimize):**
  - The big dashboard view is destroyed and the desktop shows my real still wallpaper.
  - A floating button: left-click opens the chat panel; right-click → "Restore full KURAMA" is the only way back.
  - A `WakeBridge` keeps the wake word ("KURAMA" / "wake up") working and opens the panel in talk mode.
  - The workspace is a separate small window, "KURAMA · Workspace", that refreshes itself.
  - Workspace windows and panels are created on demand and destroyed on restore.

## Tools I have (about 100, all routed)
- **Daily:**
  - calculate, convert_file (pdf↔md, md→pdf, images, media, tables, OCR, office via LibreOffice if installed; slow conversions run in the background)
  - disk_cleaner, organize_files:
    - the plan is made in the background and shown in the workspace (grouped by folder)
    - I answer yes / no / "keep the pictures where they are" within 120 s (`KURAMA_PLAN_TTL_S`)
    - topic folders are only for documents, only junk names are renamed
    - Duplicates/, Videos/Movies, undo
- **Selected text and code: `text_assist`** (one tool, group clipboard; `rewrite_text` is an alias):
  - explain a selection (a 1–3 word selection gets a dictionary meaning);
  - meaning of a word in Nepali (typed works too: "what does X mean", "X ko meaning ke ho");
  - translate (to Nepali / Hindi / English; shown in chat + clipboard; "and replace it" puts it in place);
  - improve text in place;
  - **improve code**: a background job; the result goes to the workspace and asks "Should I replace it?"; on yes it replaces only the selected block in the file on disk (backup in `data/code_backups`), or pastes if the editor has unsaved changes;
  - write code at the VS Code cursor (the language comes from the window title `name - folder - Visual Studio Code`);
  - explain a whole file.
  - The selection is copied from the app itself (`rewrite.grab()` / `put()`; if the request came from KURAMA's own window, it uses the previous window in the X stacking order).
- **Voice:**
  - dictate (voice typing into any app; spoken commands like new line / change paragraph / give space / tab / undo / stop, Nepali too; Google speech for Nepali; my names in the vocabulary through `JARVIS_MY_WORDS`);
  - the wake word ("KURAMA" or "wake up" alone);
  - TTS mute.
- **Screen:** app_control (0-token shortcuts like "new tab" or "tab 3", click by name via AT-SPI, learned replays, LLM/vision steps); window.
- **Files:**
  - find_files (whole laptop, fuzzy, scoped "X in Y"), list_folder, open_folder;
  - a **current-folder memory** (`focus.py`: "this / it / here / previous folder / parent folder", relative names, 12 h);
  - make_folder, write_file, move / copy, delete_to_trash, folder_lock (AES via gpg, password typed in a zenity box, never in chat).
- **Phone and sharing:**
  - Telegram bot: PIN for risky actions, /lock;
  - send_file_telegram (refuses home or disk roots), wifi_share (LAN link + QR), share_wifi (Wi-Fi QR);
  - remote_desktop (RustDesk; the password is only on Telegram after the PIN and expires in 15 min; `/control`, `/changepass`).
- **Web:** live_search (ESPN scores, Google News RSS, gold FENEGOSIDA / forex / crypto / stocks, fresh answers), web_search, read_webpage, wikipedia, web_watch.
- **Media:** video_download (yt-dlp, any quality, MP3), youtube, media_control, generate_image (background; shows in the workspace).
- **Apps:** open / close / kill_app, install_app (apt / snap / flatpak through a pkexec popup), launch_workspace.
- **Dev:** fix_error, run_tests, python_env, review_code, git tools, time_machine, where_was_i, kaggle_train (free Kaggle GPU; the CLI is in `data/kaggle_venv`; **needs `~/.kaggle/kaggle.json` from me**), training watch, Colab.
- **Others:** contacts (Excel `~/Documents/KURAMA/contacts.xlsx`), reminders, alarms, timers, weather, time, **date** (`get_date`: full date + weekday + week of year; Bikram Sambat with the weekday by default, English only if I ask "in AD"; `jarvis/core/nepdate.py` over `nepali-datetime`), notes, quiz, lecture, laptop_doctor, internet_doctor, battery, brightness, volume, theme, DND, focus_mode, backup, downloads, status_now, token_usage, daily_digest.
- **Sleep vs suspend:** in talk mode "sleep now" / "good night" puts **KURAMA** to sleep (frontend `wantsSleep`), never the laptop. Suspending the machine needs an explicit device word ("suspend the laptop").
- **0-token small talk:** hi, thanks, how are you; plus TYPO_FIXES and STT_FIXES in config.
- The messages / notification watcher was built and then **removed** at my request. Don't re-add it.

## Not tested live / waiting on me
- **Never confirmed on my real screen:**
  - text_assist replacing code in VS Code, and writing at the cursor;
  - the mini workspace window;
  - the mute and scroll fixes;
  - "wake up" sensitivity.
  If I report a problem, ask for exactly what I said and what happened. My pasted chat logs show route, tier, tokens and ms for each message, so use them.
- **My own actions still open:** `kaggle.json`, optionally `sudo apt install libreoffice-writer`, "enable screen control" plus restarting Brave / VS Code (for AT-SPI clicks).

## Where we stopped
Last commit: "Date tool with Bikram Sambat (weekday + week); 'sleep now' sleeps KURAMA in talk mode, not the laptop" (`d70da9e`). Routing eval 110/110 + 32/32 + 27/27, tool tests pass, KURAMA restarted. Recent work before that: talk mode now listens immediately when I click the talk button; read-later / OCR / copy-history / clipboard fixes; Telegram PIN + /lock; RustDesk remote desktop; power modes with in-process workers. Next, I'll tell you what to work on.
