# Jarvis (KURAMA)

A free, all-day voice assistant for an Ubuntu laptop. Say **"Hey Jarvis"** (or press **Ctrl+Alt+J**),
talk in English, Nepali or Hindi, and Jarvis answers out loud and controls your desktop: apps, windows,
volume, brightness, media, files, git, web search, reminders, memory and more.
Heavy AI runs on the Groq free tier; everything local stays small (≈ 80 MB idle, no GPU, no PyTorch).

## Requirements
- Ubuntu on **X11** (GNOME tested), Python **3.12**, a microphone and speakers.
- apt packages:
  ```bash
  sudo apt install ffmpeg xdotool wmctrl xclip brightnessctl playerctl portaudio19-dev libnotify-bin
  ```
- A free **Groq API key** (https://console.groq.com). Optional: a Telegram bot for phone control.

## Setup
```bash
cd KURAMA
python3.12 -m venv venv
venv/bin/pip install -r requirements.txt
cat > .env <<'EOF'
GROQ_API_KEY=gsk_...
TELEGRAM_BOT_TOKEN=          # optional: from @BotFather
TELEGRAM_CHAT_ID=            # optional: your chat id (the bot only obeys this chat)
EOF
chmod 600 .env
```
Secrets live only in `.env`; Jarvis never prints or logs them.

## Run
| What | Command |
|---|---|
| Voice, wake word (default) | `venv/bin/python -m jarvis --voice` |
| Voice, hotkey/Enter only | `venv/bin/python -m jarvis --voice --no-wake` |
| Text chat in the terminal | `venv/bin/python -m jarvis` |
| Web UI (chat, mic, confirm cards) | `venv/bin/python -m jarvis.server` → http://127.0.0.1:8000 |
| Background workers (watchdogs, Telegram, reminders, digest) | `venv/bin/python -m jarvis.workers` (`--list`, `--only a,b`) |
| Everything (workers + voice) | `scripts/jarvis-start.sh` |

### Talking to Jarvis (wake word)
- **Sleeping**: Jarvis only listens for *"hey / hi / hello / ok Jarvis"* (or *Kurama*; the name alone works too).
  You can say the command in the same breath: *"Hey Jarvis, what's the time?"*
- **Awake**: a short chime, then just talk; no hotkey needed between turns.
- Back to sleep after 45 s of silence, or say *"sleep Jarvis"*, *"go to sleep"*, *"stop listening"*, *"bye Jarvis"*, *"so jao"*, *"sut"*.
- *"stop"* while Jarvis is talking interrupts it. The hotkey also interrupts, and also wakes it.
- *"exit Jarvis"* / *"shut down Jarvis"* quits (after a yes).
- How it works without a wake-word model: a cheap VAD loop finds short speech bursts (0.4–2.5 s), and only
  those are checked with the free Google Web Speech recognizer (`SpeechRecognition`, no key), with Groq Whisper as the
  fallback. At most 12 checks per minute. Sleeping uses about 2% CPU.

## Example commands
| Category | Say… |
|---|---|
| Time, weather | "what time is it in Tokyo", "weather tomorrow", "मौसम कस्तो छ" |
| Apps & windows | "open VS Code", "close Spotify", "snap this window left", "what's open", "start my coding workspace" |
| System | "volume 40", "mute", "brightness down", "lock the screen", "battery status", "mic mute" |
| Desktop | "do not disturb on", "night light on", "dark mode", "change wallpaper", "focus mode for 25 minutes" |
| Media & YouTube | "pause", "next song", "play lo-fi on YouTube", "search YouTube for Nepali songs" |
| Reminders & schedules | "remind me in 20 minutes to drink water", "every day at 9 run the digest", "list my reminders" |
| Web & knowledge | "search the web for…", "wikipedia Mount Everest", "read this page", "what does PROGRESS.md say about P7" |
| Files | "make a folder demo in projects", "move report.pdf to Documents", "find files named invoice" |
| Dev & git | "git status", "summarize my diff", "commit with a message", "run the tests", "review this code" |
| Memory | "remember my locker code is 42", "what did I tell you about the locker", "forget that" |
| Long jobs (background) | "write a 1000-line essay about Nepal and open YouTube": the essay goes to `data/outputs/` |
| Phone | Telegram the bot: "battery?", "send me the report.pdf" |
| New abilities | "make a tool that converts CSV to JSON": the toolsmith writes, tests and saves it (asks first) |

Full tool list: see the table at the end.

## Safety model
Every tool has a safety level:
- **safe**: runs at once (read-only or easy to undo: time, volume, open an app).
- **confirm**: Jarvis asks first ("Say yes or no" in voice, `[y/N]` in text, a card in the web UI, buttons in Telegram).
  Covers deleting files, shell, closing or killing apps, suspend, git commit, sending messages, installs. Silence or
  an unclear answer means **no**.
- **blocked**: never runs (for example power off by voice).
- Shell commands go through an allowlist; dangerous git (push, reset, clean, --force) is refused.
- **Toolsmith** (new tools from code generation) asks for consent before writing any code, checks the code with an AST
  allowlist, runs it in a sandbox (memory, CPU and time limits, no env secrets) and asks again before anything touching
  the system, network or files. Every tool call is logged in `data/jarvis.db`.

## Memory & privacy
- Everything stays on this laptop in `data/` (folder mode 700, files 600; the entry points set `umask 077`):
  `jarvis.db` (chat history, notes, facts, logs, token usage), `memory.db` (knowledge index), `outputs/`, `skills/`, `logs/`.
- Only the text of a request (plus up to 3 relevant facts) goes to Groq; wake-word checks send short audio clips to Google.
- Delete: say "forget that" / "forget everything", or remove files: `rm -r data/` deletes all memory (it is recreated empty).

## Token-saving design (Groq free tier)
- **Fast path**: clear commands ("volume 30", "open YouTube", "what time is it") are answered by regex templates with **0 LLM tokens**.
- **Router**: keyword rules pick the 1–3 relevant tool groups; only their schemas are sent (never all tools).
- **Meta-tool**: unclear requests get one tiny `request_tools` tool (~200 tokens) that loads the right groups on demand.
- Short system prompt (<250 tokens), last 6 turns + rolling summary, tool output capped at ~800 chars, cached weather/search,
  per-model rate limiter with fallback between models. `token usage` shows today's spend.

## Start on login (optional)
```bash
scripts/install_autostart.sh     # workers as a systemd --user service + voice via ~/.config/autostart
scripts/uninstall_autostart.sh   # undo
```
No sudo. The workers start now and on every boot (`systemctl --user status jarvis-workers`); the voice session starts with
your desktop (it needs the display and audio). Logs: `data/logs/voice.log`, `data/logs/workers.out`.

## Troubleshooting
| Problem | Fix |
|---|---|
| Turns never end / noise counted as speech | raise the gate: `JARVIS_VAD_MIN_RMS=1500` (default 900); shorter pause: `JARVIS_VAD_SILENCE_MS=700` |
| Wake word too sensitive / not sensitive | `JARVIS_WAKE_NAME_ALONE=0` (require "hey"), `JARVIS_WAKE_DEBUG=1` prints every check |
| No wake word wanted | `--no-wake` or `JARVIS_WAKE=0` (hotkey only) |
| Nepali comes out as Hindi/English | `JARVIS_STT_LANG=ne` |
| Groq `429` (rate limit) | wait a minute; long jobs are paced automatically; `JARVIS_STT_DUAL=0` halves Whisper calls |
| Jarvis hears itself | use headphones (voice barge-in is off by default; say "stop" or press the hotkey) |
| Hotkey does nothing | X11 only; set another one: `JARVIS_HOTKEY="<ctrl>+<alt>+k"` |
| "cannot open microphone" | `sudo apt install portaudio19-dev`, pick a device: `JARVIS_INPUT_DEVICE=<index>` |

## Tools
Generated by `venv/bin/python scripts/list_tools.py` (re-run it to refresh this table).

91 tools in 30 groups.

| Group | Tool | Safety | What it does |
|---|---|---|---|
| apps | `close_app` | confirm | Close all open windows of an app by name (may lose unsaved work). |
| apps | `focus_app` | safe | Switch to (focus) an already open app window by name. |
| apps | `kill_app` | confirm | Force-quit an app that is frozen or won't close (kills its processes). |
| apps | `launch_workspace` | safe | Launch a named workspace: a set of apps and sites (coding, study, research, writing). |
| apps | `open_app` | safe | Open/launch an installed desktop app by name (vs code, files, terminal, settings, firefox). |
| audio | `mic_mute` | safe | Mute, unmute or toggle the microphone, or say whether it is muted. |
| audio | `mute_audio` | safe | Mute, unmute or toggle the speakers, or say whether they are muted. |
| audio | `volume` | safe | Get, set (0-100) or step the speaker volume up/down. |
| automation | `add_watchdog_target` | confirm | Add a dev server for the crash watchdog to keep running and restart if it crashes. |
| automation | `n8n_trigger` | confirm | Trigger an n8n workflow webhook with a JSON payload. |
| automation | `watchdog_status` | safe | Show crash-watchdog targets, their state and restarts. |
| browser | `open_url` | safe | Open a website (URL or a name like youtube, github, gmail) in the browser. |
| clipboard | `clipboard_history` | safe | List text Jarvis copied recently, or copy item N back to the clipboard. |
| clipboard | `read_clipboard` | safe | Read the text currently on the clipboard. |
| clipboard | `write_clipboard` | safe | Copy the given text to the clipboard. |
| codequality | `dependency_doctor` | safe | Check a Python project's dependencies: unpinned, duplicate, missing, unused, outdated, vulnerable, torch/GPU baggage. |
| codequality | `precommit_gate` | safe | Pre-commit checks on staged files (syntax, lint, secrets, big files, conflicts, breakpoints); can install a git hook. |
| codequality | `repo_hygiene` | safe | Repo tidiness check: README/LICENSE/.gitignore gaps, tracked junk, big files, stale branches, TODOs, empty dirs. |
| codequality | `review_code` | safe | AI code review of the staged diff, a file or the last commit; returns up to 8 findings with file:line. |
| codequality | `secrets_audit` | safe | Scan a repo's files and recent git history for leaked keys/tokens/passwords; checks .env is ignored. |
| desktop | `auto_theme` | safe | Turn automatic dark/light mode at sunset/sunrise on or off, or check it. |
| desktop | `do_not_disturb` | safe | Turn Do Not Disturb (hide notification pop-ups) on or off. |
| desktop | `focus_mode` | safe | Start or stop a timed focus (pomodoro) session: Do Not Disturb on, alert when done. |
| desktop | `night_light` | safe | Turn Night Light (warm screen) on or off, or set its warmth in kelvin. |
| desktop | `set_wallpaper` | safe | Change the desktop wallpaper (an image path or name, next, random) or tell the current one. |
| dev | `run_tests` | safe | Run pytest on a project/file; returns pass/fail counts and the first failure. |
| dev | `env_doctor` | safe | Environment doctor: python/venv/pip, disk, RAM/swap, CLI tools, API key check. |
| dev | `scaffold_project` | confirm | Scaffold a new Python project (python-cli, fastapi, langgraph-agent or data-science). |
| devutils | `add_docstrings` | confirm | Add missing docstrings and type hints to a Python file's functions (diff first, .bak kept). |
| devutils | `benchmark_table` | safe | Build a markdown benchmark/results table (best per metric bold) from CSV/JSON/log files. |
| devutils | `config_diff` | safe | Snapshot a project's config files and show what changed since the last snapshot (secrets masked). |
| devutils | `generate_requirements` | safe | Generate requirements.generated.txt from a project's imports, pinned to installed versions. |
| devutils | `notebook_to_script` | safe | Convert a Jupyter notebook (.ipynb) to a .py script next to it; optional main() wrapper. |
| display | `brightness` | safe | Get, set (percent) or step the screen brightness up/down. |
| display | `set_theme` | safe | Switch the desktop between light mode and dark mode (keeps your icons and cursor). |
| files | `copy_path` | confirm | Copy a file or folder. |
| files | `delete_to_trash` | confirm | Move a file or folder to the trash (can be restored). |
| files | `make_folder` | safe | Create a folder (and missing parent folders). |
| files | `move_path` | confirm | Move or rename a file or folder. |
| files | `write_file` | safe | Create or write a text file with the given content (makes missing folders). |
| filesearch | `find_files` | safe | Find files by name (glob or part of name) or by text content under a folder. |
| general | `get_time` | safe | Get the current date and time, locally or in any city or country. |
| git | `git_branch` | confirm | Create a new git branch (and switch to it) or switch to an existing one. |
| git | `git_commit` | confirm | Commit staged git changes; auto-writes a short message if none is given. Never pushes. |
| git | `git_diff_summary` | safe | Summarize git changes (diff --stat) for staged and unstaged files. |
| git | `git_log` | safe | Show the last N git commits, one line each. |
| git | `git_status` | safe | Git status of a repo: branch, ahead/behind, changed files. |
| jobs | `cancel_job` | safe | Cancel a background job by its id or words from its title. |
| jobs | `job_result` | safe | Show a background job's output file path and its beginning. |
| jobs | `list_jobs` | safe | List background jobs and their status/progress. |
| jobs | `resume_job` | safe | Resume an interrupted or cancelled writing job from its next section. |
| jobs | `write_document` | safe | Write a long essay/article/story/report or code file in the background; returns a job id at once. |
| knowledge | `ask_knowledge` | safe | Answer a question about the user's own code, docs or notes (also 'what is this project about'), citing file paths. |
| knowledge | `index_folder` | safe | Index a folder of code or notes (incremental, runs in the background) so it can be searched. |
| knowledge | `search_knowledge` | safe | Search the user's own code, docs and notes; returns file:lines with short snippets. |
| media | `media_control` | safe | Control music/video playback: play, pause, next, previous, stop, or what's playing. |
| media | `playlist` | safe | Play one of the user's named playlists (web link or music folder), or list them. |
| media | `youtube` | safe | Play a YouTube video for a query, search YouTube, or pause/next/fullscreen the YouTube tab. |
| memory | `forget` | confirm | Delete remembered notes (last, all, or by id) or a learned fact about the user. |
| memory | `recall` | safe | Recall remembered notes (all, last, search) or what you know about the user (profile). |
| memory | `recall_session` | safe | Recall past conversations: the last session, a day (yesterday, a weekday, YYYY-MM-DD) or a topic. |
| memory | `remember` | safe | Save a short note or fact the user asks you to remember. |
| power | `battery_status` | safe | Battery level, charging state, time remaining and battery health. |
| power | `lock_screen` | safe | Lock the screen. |
| power | `power_off` | blocked | Shut down or restart the computer (blocked: not allowed). |
| power | `suspend_computer` | confirm | Put the computer to sleep (suspend). |
| schedule | `add_reminder` | safe | Set a reminder at a time (once or repeating); alerts on desktop, Telegram and by voice. |
| schedule | `cancel_schedule` | safe | Cancel a reminder or scheduled command by its id or words from it. |
| schedule | `list_schedules` | safe | List pending reminders and scheduled commands. |
| schedule | `schedule_command` | confirm | Schedule a Jarvis command to run later or repeatedly (e.g. 'weather in Kathmandu' every day at 8). |
| screen | `screenshot` | safe | Take a screenshot (full screen, active window, or a selected area); returns the file path. |
| speech | `read_aloud` | safe | Read text aloud, or "clipboard" to read the clipboard aloud. |
| system | `resource_status` | safe | System health: RAM, swap, CPU load, disk use, Jarvis memory, top memory hogs, workers. |
| telegram | `send_file_telegram` | confirm | Send a file from this computer to the user's Telegram. |
| telegram | `send_message_telegram` | confirm | Send a text message to the user's Telegram. |
| toolsmith | `delete_skill` | confirm | Delete a saved skill. |
| toolsmith | `list_skills` | safe | List the saved skills (small tools Jarvis built earlier). |
| toolsmith | `make_tool` | safe | When no other tool can do a real task (calculation, conversion, data, a desktop setting), offer to build a small tool for it. It asks the user before making anything. |
| toolsmith | `use_skill` | safe | Run a saved skill (a small tool Jarvis built earlier). |
| usage | `daily_digest` | safe | Give the daily digest (conversations, jobs, alerts, notes, tokens, git commits, weather). |
| usage | `token_usage` | safe | Report LLM token usage, budget, fast-path savings, speech seconds and API cost. |
| watch | `list_watches` | safe | List process and log watches and their state. |
| watch | `stop_watch` | safe | Stop a process/log watch by number or name, or 'all'. |
| watch | `watch_log` | safe | Tail a log file (e.g. a training run) and alert on errors, NaN loss, OOM or completion. |
| watch | `watch_process` | safe | Watch a running process (PID or name) and alert when it exits, with its runtime. |
| weather | `weather` | safe | Current weather and up to 3-day forecast for any city or country. |
| web | `read_webpage` | safe | Read a web page (URL) and return its main text, e.g. to summarize an article. |
| web | `web_search` | safe | Search the web for current info, people, news or facts: top results with title, URL and snippet. |
| web | `wikipedia` | safe | Wikipedia summary of a person, place or topic (fuzzy names ok); lang en, ne or hi. |
| windows | `list_windows` | safe | List the open windows (title and app). |
| windows | `snap_window` | safe | Snap the active or a named window left/right, maximize, minimize or restore it. |

## KURAMA UI as a live wallpaper

```bash
scripts/kurama-wallpaper.sh            # starts the API if needed, shows the UI full-screen BEHIND all windows
scripts/kurama-wallpaper.sh --window   # same page in a normal window (testing)
scripts/kurama-wallpaper.sh stop       # closes it (the API keeps running)
```
It is a native GTK + WebKit window (`scripts/kurama_wallpaper.py`, run by the system `/usr/bin/python3`:
needs `python3-gi gir1.2-webkit2-4.1`, optional `gir1.2-wnck-3.0`) with the desktop window type, on every
workspace and hidden from the taskbar. While a maximized or full-screen window covers the desktop (checked
every 2 s with libwnck) the page is paused (`window.kuramaPause(true)`), so it costs ~0 CPU while you work.
Use Super+D (show desktop) to see it; the chat, Mic and Conversation modes work there (the page records WAV
itself, no MediaRecorder needed). To make it start at login, add `scripts/kurama-wallpaper.sh` to GNOME
"Startup Applications".
