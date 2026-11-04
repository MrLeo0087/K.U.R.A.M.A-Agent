# KURAMA

A free, all-day voice assistant for an Ubuntu laptop. Say **"Hey KURAMA"** (or press **Ctrl+Alt+J**),
talk in English, Nepali or Hindi, and KURAMA answers out loud and controls your desktop: apps, windows,
volume, brightness, media, files, git, web search, reminders, memory and more.
Heavy AI runs on the Groq free tier; everything local stays small (≈ 80 MB idle, no GPU, no PyTorch).

## Requirements
- Ubuntu on **X11** (GNOME tested), Python **3.12**, a microphone and speakers.
- apt packages:
  ```bash
  sudo apt install ffmpeg xdotool wmctrl xclip brightnessctl playerctl portaudio19-dev libnotify-bin
  ```
- A free **Groq API key** (https://console.groq.com). Optional: a Telegram bot for phone control.

## Developer commands
`make help` lists them: `make test` (full suite, offline), `make lint` (the commit gate), `make type` (type gate),
`make js-check` (frontend parses), `make cov` (coverage with a floor), `make eval` (routing scorecard), `make check`
(all of these, what CI runs), `make restart`, `make report` (recent failures), `make rss`, `make metrics` (live
Prometheus metrics from `/api/v1/metrics`). Developer tools: `make install-dev`. Hooks:
`venv/bin/pip install pre-commit && venv/bin/pre-commit install`. Design decisions: [docs/adr/](docs/adr/). How it all works and how to learn it:
[LEARN.md](LEARN.md).

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
Secrets live only in `.env`; KURAMA never prints or logs them.

## Run
| What | Command |
|---|---|
| Voice, wake word (default) | `venv/bin/python -m jarvis --voice` |
| Voice, hotkey/Enter only | `venv/bin/python -m jarvis --voice --no-wake` |
| Text chat in the terminal | `venv/bin/python -m jarvis` |
| Web UI (chat, mic, confirm cards) | `venv/bin/python -m jarvis.server` → http://127.0.0.1:8000 |
| Background workers (watchdogs, Telegram, reminders, digest) | `venv/bin/python -m jarvis.workers` (`--list`, `--only a,b`) |
| Everything (workers + voice) | `scripts/jarvis-start.sh` |

### Talking to KURAMA (wake word)
- **Sleeping**: KURAMA only listens for *"hey / hi / hello / ok KURAMA"* (or *Kurama*; the name alone works too).
  You can say the command in the same breath: *"Hey KURAMA, what's the time?"*
- **Awake**: a short chime, then just talk; no hotkey needed between turns.
- Back to sleep after 45 s of silence, or say *"sleep KURAMA"*, *"go to sleep"*, *"stop listening"*, *"bye KURAMA"*, *"so jao"*, *"sut"*.
- *"stop"* while KURAMA is talking interrupts it. The hotkey also interrupts, and also wakes it.
- *"exit KURAMA"* / *"shut down KURAMA"* quits (after a yes).
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
- **confirm**: KURAMA asks first ("Say yes or no" in voice, `[y/N]` in text, a card in the web UI, buttons in Telegram).
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
| KURAMA hears itself | use headphones (voice barge-in is off by default; say "stop" or press the hotkey) |
| Hotkey does nothing | X11 only; set another one: `JARVIS_HOTKEY="<ctrl>+<alt>+k"` |
| "cannot open microphone" | `sudo apt install portaudio19-dev`, pick a device: `JARVIS_INPUT_DEVICE=<index>` |

## Tools and how to use them
See [COMMAND.md](COMMAND.md): the architecture, the 17 general tools and every tool underneath, every `/command`, daily use.
Monitoring (traces of every request): [MONITORING.md](MONITORING.md).

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
