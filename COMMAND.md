# KURAMA: what it can do and how to use it

This is the one page to read when you forget something. It covers:

1. How to start KURAMA and how to talk to it
2. How it works inside (the v2 architecture), and how it saves tokens
3. How it keeps your tasks apart (to-do, reminders, long tasks, reading list, code work)
4. How it does many things at once
5. Every tool, with example sentences
6. Every `/command`
7. Ideas for using it every day
8. **Every tool in detail:** the 17 tools the AI chooses from (8a) and the 129 specialised tools underneath them (8b)

> **Key idea:** you never have to remember exact words. Say it your own way (English, Nepali or Hindi).
> The example sentences below are only ideas. When you want zero tokens and zero guessing, type a `/command`.

---

## 1. Start KURAMA and talk to it

### Start and stop

| What | How |
|---|---|
| Turn on | `scripts/kurama-power.sh on`, or **Super+K** |
| Turn off (frees all RAM/CPU) | `scripts/kurama-power.sh off`, or the power button on the screen |
| Is it running? | `scripts/kurama-power.sh status` |

When KURAMA is on, it runs by itself all day. You don't have to start anything else.
- **The dashboard** sits behind your desktop windows. Minimize it and it becomes a small floating button.
- **The helpers** (reminders, alerts, Telegram, the morning brief) run in the background.

### Five ways to give a command

| Way | How | Best for |
|---|---|---|
| **Talk mode** | Click the wave button, or say **"KURAMA"** / **"wake up"** | Hands-free. After it answers, keep talking for 2 minutes without the name |
| **Mic button** | Click the mic, speak, click again | One sentence by voice |
| **Typing** | Type in the box and press Enter | Exact names, long requests |
| **`/commands`** | Type `/` and pick from the list | 0 tokens, exact, works offline from the AI |
| **Telegram** | Message your KURAMA bot from the phone | Using the laptop from anywhere |

- **Press-to-talk hotkey:** Ctrl+Alt+J.
- **Go to sleep:** say "sleep now" or "good night" in talk mode. This puts KURAMA to sleep, never the laptop.

### Do I need to copy or select anything first?

Usually not. Some tools work on what you point at:

| You want to... | Do this first | Then say |
|---|---|---|
| Explain / translate / summarize some text | **Highlight it** in any app (no need to copy) | "explain this", "translate this to Nepali", "summary of this paragraph" |
| Help with code | **Highlight it in VS Code** | "find this function", "is this correct syntax", "run this code" |
| Reply to a chat | Highlight the messages, **or just have the chat open on screen** | "what should I reply to my friend" |
| Save a link | Have the page open in Brave, or highlight the link | "save this link as facebook" |
| Ask about a web page | Have it open in Brave | "what is this page about" |
| Make an MP3 of text | Highlight it | "make an audio of this" |

KURAMA remembers your last highlight outside its own window for 10 minutes, so you can highlight first, then come back and ask.

### Settings worth knowing

- **"Let KURAMA hear the laptop's own sound": keep it OFF.**
  - OFF means music, videos and KURAMA's own voice are removed from what the mic hears, so it understands you while music plays.
  - Turn it ON only to make KURAMA listen to a video or song.
- **Settings → Memory → understanding model:** *auto* (the default) loads the small local AI only when needed and frees its memory after 10 minutes.

---

## 2. How KURAMA works, and how it saves tokens

KURAMA uses **Groq's free AI**, which has a daily limit of tokens: about 180,000 per model per day, and about 8,000 per minute. So it tries to **not use the AI at all** whenever it can.

### What happens when you say something

```
Your words (voice -> Groq Whisper speech-to-text, typing, or Telegram)
   │
   ├─ 0. Several jobs in one sentence?  -> split; each part runs on its own (long ones in the background)
   ├─ 1. /command?                       -> run that tool directly                          0 tokens
   ├─ 2. Instant shortcut (rules)?       -> hundreds of known ways of saying things:        0 tokens
   │                                        run the tool, answer from a ready template
   ├─ 3. Router: which kind of help is this?
   │       a. keyword rules                                                                 0 tokens
   │       b. local "understanding model" (small, on the laptop)                            0 tokens
   │       c. a tiny AI question "which group?" (only if still unclear)                    ~100 tokens
   │
   └─ 4. The AI agent, given at most 3 of the 17 general tools (part 8a)
           -> it picks one + an action ("laptop", action "bluetooth", value "off")
           -> the general tool hands the job to the right specialised tool (part 8b)
           -> anything risky (delete, shutdown, run a command) asks you yes/no first
           -> a short ready-made answer is used when possible (no second AI call)
```

**Why this design (v2):** before, the AI had to choose between ~130 small tools, and often chose the wrong one or none.
Now it chooses between **17 clear tools** (apps, laptop, files, telegram, schedule, todo, media, web, info, memory,
create, text, code, life, kurama, run_command, run_python), and each one knows how to reach the specialised tool.

**Safety nets:**
- If the AI says "I can't" or claims "I've set a timer" without really using a tool, KURAMA retries once and lets it load the right tools.
- If nothing fits, the AI can use `run_command` (one terminal command) or `run_python` (a short program). **These ask you before every run.** `sudo`, formatting disks, `rm -rf /` and similar are always refused.

**Measured on 200 of your real requests** (`venv/bin/python -m tests.eval.harness`, add `--ai` for the full test, which costs tokens):
62% are answered by instant shortcuts (0 tokens, 100% right); the router offers the right tools 92% of the time;
the full agent is right 96% of the time with about 490 tokens and 0.5 s per request.

### The other token savers

- **Three AI sizes:**
  - a small fast model for chat and simple tool use;
  - the big model only for reasoning, coding and long writing;
  - a vision model for pictures and screens.
  - When one model is busy or out of tokens, it moves to the other.
- **A short system prompt:** under 250 tokens.
- **Short memory:** the last 6 turns plus a short rolling summary, never the whole chat.
- **Tool results cut to about 800 characters** before the AI sees them.
- **Long answers go to the Workspace:** the full text goes to the Workspace card, and the chat shows one short line. Voice reads at most about 420 characters, then says "the rest is on the screen".
- **Caching:** repeated results (weather, searches, song searches) are kept for a few minutes to 12 hours.
- **Local work instead of AI:**
  - dictionary meanings (offline WordNet);
  - money and habits, charts, diagrams, files, ports, code navigation;
  - dates (Nepali BS), reminders, music.
- **The token guard:** when an explanation would be long, KURAMA first asks "Want the long version?".
- **See your use:** say "token usage" or `/tokens`. Every AI call is logged.

### Where things are stored (all on your laptop)

| What | Where |
|---|---|
| Chats, alerts, logs of every tool call | `data/jarvis.db` |
| Results (essays, code, charts, images, MP3s, videos) = the **Workspace** | `data/outputs/` |
| To-do list, reminders, alarms | `data/jarvis.db` (KURAMA's own database: fast, never mixed) |
| Your editable sheets | `~/Documents/KURAMA/` → `read_later.xlsx` (reading list only), `goals.xlsx` (long tasks), `expenses.xlsx`, `habits.xlsx`, `links.xlsx`, `contacts.xlsx` |
| Secrets (API keys) | `.env` only |

---

## 3. How it keeps your tasks apart

KURAMA keeps **five kinds of things** apart and never mixes them:

| Kind | Words that mean it | Examples |
|---|---|---|
| **To-do** (things to do; never rings by itself) | task, to-do, to do list | "add buy milk to my to-do #shopping tomorrow", "add finish the report, it's urgent", "show my to-do list", "done 2", "delete the bank task", "edit 3 to friday" |
| **Reminder / alarm / timer** (rings at a time) | remind me, alarm, timer, schedule | "remind me to call mom at 5", "alarm at 6 am", "timer 10 minutes", "schedule reading at 9 pm", "what are my reminders", "move the call reminder to 7" |
| **Both** | a to-do that should also ring | "add call the bank to my to-do and remind me tomorrow at 10 am" (finishing the to-do cancels its reminder) |
| **Reading list** | read later | "save this to read later", "show my reading list" |
| **Long tasks** (weeks or months: exams, projects) | long task, goal, monthly, countdown | "my exam is in 30 days, remind me every day", "show my long tasks", "how many days until the exam", "today I wrote chapter 2" |
| **Code work** | code words, "where was I" | "where was I", "watch the project at ~/code/app", "list my coding projects" |

- **To-do items with a time** get a heads-up 10 minutes before, and a "not done yet" nudge 1 hour later.
- **To-do items without a time** get at most 2 gentle nudges a day.
- **Long tasks** send countdowns and check-in questions, only between 05:00 and 22:00. Each long task has its own folder with a log, plus weekly and monthly reports.
- **Every alert** goes to the laptop AND Telegram.
  - Pause one kind: "mute RAM alerts for 20 minutes" or `/mute ram 20`.
  - The day summary arrives at 10 PM.
- **The top bar** shows the to-do count and the next reminder; click them for the details window (separate To-do / Reminders / Read later tiles).
- **The Work card** (full dashboard, ⊞) shows to-dos with ✓ / ✕ buttons.

---

## 4. How it does many things at once

- **One sentence, several jobs:** "write a 1000-word essay about Nepal and open YouTube".
  - Quick actions (open YouTube) happen at once.
  - Long jobs (the essay) run **in the background** and never block you.
- **Background jobs:** writing, code generation, scans, images, charts, MP3s, videos, downloads.
  - When a job finishes, KURAMA says so ("Your audio is ready. It's in the workspace.") and the result appears in the **Workspace**.
  - `/jobs` shows what's running. "cancel the job" stops one.
- **Rate limiter:** big jobs are cut into pieces and paced across models, so a long essay never stops KURAMA from answering you.
- **One camera or vision feature at a time**, to keep RAM low. KURAMA aims for under 600 MB while idle.
- **Talking while it talks:** say "stop", or start a new request; KURAMA stops speaking and listens.

---

## 5. Every tool, with what to say (short version)

The AI chooses between **17 general tools**, which use **129 specialised tools** underneath. This part is the quick overview by area; **part 8** lists every tool one by one, with its actions and example sentences.

### Everyday

| Tool | What it does | Say |
|---|---|---|
| Time / date | Time in any city, today's date in **Bikram Sambat** (AD if you ask), week number | "what time is it in Tokyo", "what's the date today", "date in AD", "which week is this" |
| Weather | Now and up to 3 days | "weather", "weather in Pokhara tomorrow" |
| Morning brief | The first time you use the laptop each day: weather, to-dos, long tasks, habits, money, bills (spoken, on the laptop and on Telegram) | happens by itself; "morning brief", `/brief` |
| Reminders, alarms, timers, stopwatch | | "remind me to drink water in 30 minutes", "alarm at 6 am", "timer 10 minutes", "start the stopwatch" |
| Calculator / converter | Maths, %, units | "15% of 2400", "convert 100 usd to npr" |
| Contacts | Your contacts sheet | "what's Ram's number", "add Sita 98..." |
| Notes, quiz, timetable, lecture recorder | Study helpers | "note for DSA: stacks are LIFO", "start a quiz on DSA", "show my timetable", "record this lecture" |
| Memory | Remembers facts about you | "remember that my exam is on Nov 25", "what do you know about me", "forget that" |

### Money tracker (`expenses.xlsx`)

| Say | Result |
|---|---|
| "spent 200 on meat, 50 on tomato and 500 on vegetables" | 3 entries, each with its own category |
| "got 20000 salary" | income |
| "spent 300 on bus on October 20" | saved on that date |
| "how much did I spend this month / on food / in study" | report (study = education, cloth = clothes) |
| "spending breakdown", "show me the whole budget and expense" | every category, budgets, total, savings |
| "how much from Oct 1 to Oct 15", "on the 20th", "in the last 10 days" | date range |
| "set my food budget to 8000", "my monthly budget is 30000" | budgets, with warnings at 80% and when you go over |
| "remind me to pay internet 1500 every month on the 5th", then "paid internet" | monthly bills |
| "delete the last expense", "the last one was 450" | fix mistakes |
| "chart my expenses" | bar, pie and per-day charts |

**Click the Money & habits card** to open the Money window. It has a calendar filter (From/To date), a category filter, totals and a delete button on each row.

### Habits (`habits.xlsx`)

- **Add one:** "add a habit: drink water 8 glasses a day, remind me at 10 am".
- **Check in:** "I drank 2 glasses of water", "did exercise", "exercise done", `/done exercise`.
- **See streaks:** "my habits", `/habits`, plus the ✓ buttons on the card.
- **Undo or delete:** "I didn't do exercise", "delete the water habit".

### Laptop

| Tool | Say |
|---|---|
| Status / battery / RAM | "status", "battery", "why is my laptop slow", "free up some ram" |
| Volume / brightness / theme | "volume 40" (up to 150% with Ubuntu's Over-Amplification), "brightness up", "dark mode", "do not disturb on", "night light" |
| Apps and windows | "open VS Code", "close Brave", "kill the frozen app", "install VLC", "snap this window left", "press ctrl+t" |
| Screen | "take a screenshot", "read the text on the screen", "scan the QR code" |
| Files | "find my resume pdf", "open the downloads folder", "make a folder called notes here", "move it to Documents", "delete this file" (to the Trash, asks first), "lock this folder with a password" |
| Cleaning | "clean my downloads", "organize my downloads" (shows a plan first, then "yes"), "disk cleaner" |
| Convert files | "convert this pdf to markdown", "convert report.docx to pdf", "convert video.mp4 to mp3" |
| Internet | "check my internet", "fix my internet" |
| Ports | "what is running on port 8080", "show my open ports", "free port 3000" (asks first) |
| Power | "lock the screen", "shut down the laptop" (asks yes/no), "restart", "suspend the laptop" |
| Dictation | "start dictation": KURAMA types what you say into any app. Say "new line", "stop" |
| Clipboard history | "what did I copy 10 minutes ago", "copy back the second one" |

### Phone, Telegram and safety

| Tool | Say (laptop) / send (Telegram) |
|---|---|
| Send things to the phone | "send this file to Telegram", "send the last result to my phone" |
| Phone location | "where is my phone": the last location your phone shared with the bot on Telegram (share live location there for live updates). "find my phone" opens Google Find My Device |
| Laptop location / anti-theft | "where is my laptop" or `/where`; `/guard on` (photo + location if someone uses it); `/track on` (lost mode) |
| Camera | `/camera` (photo), `/video 8` (8-second clip) |
| Remote desktop | `/control` on **Telegram** gives a RustDesk password for 15 minutes (needs your PIN) |
| Wi-Fi | "share wifi" (QR code), "share this file over wifi" |
| Alerts | `/notifications`, `/mute ram 20`, `/unmute`; on Telegram, reply "stop" to an alert to pause that kind |

On Telegram, `/list` shows the phone commands and `/all` shows every KURAMA command. Telegram's `/` menu also shows them.

### Coding (highlight in VS Code first)

| Tool | Say |
|---|---|
| **Find a function** | "find this function", "go to definition", `/def`: VS Code opens the real code, even inside libraries |
| **Library help** | "help me with this library", "what arguments does this take", "is this correct syntax", `/args`: real arguments, typo check ("Did you mean `sep`?") |
| **Run code** | "run this code", `/run`: the output shows in the chat. If it fails, say "fix it" |
| Explain / improve / complete | "explain this code", "fix this code" (shows the result first, replaces only after "yes"), "complete this function" |
| Tests and usage | "give me code to test this function" (KURAMA runs the tests first), "how can I use this function" |
| Write at the cursor | "write a function that reads a csv here" |
| Errors | copy an error and say "what does this error mean" |
| Tidy | "format this file", "check this file" (ruff) |
| Git and projects | "where was I", "git status", "commit my changes", "watch the project at ~/code/app" |
| Code quality | "review my code changes", "check dependencies", "check my packages" (missing, unpinned, outdated, known vulnerabilities) |
| Requirements | "generate requirements.txt", "requirements banao", "make requirements for ~/Projects/tara": reads the imports, writes `requirements.generated.txt`. No path = the project open in VS Code |
| Notebook → Python | "convert this notebook to python" (the one open in VS Code, else the newest), "convert train.ipynb to py" |
| Dev helpers | "run the tests", "create a venv", "install pandas", "decode this" (JSON, base64, JWT...) |
| Anything else | "run the command du -sh ~/Downloads", "use python to count lines in all .py files": shows the command and asks yes/no first |
| Training | "train this on Kaggle" (free GPU), "how's training" |

### Web and text

| Tool | Say |
|---|---|
| Live answers | "latest news about Nepal", "gold price today", "dollar rate", "football scores", "top 10 Ballon d'Or 2026" |
| Search / Wikipedia / pages | "search the web for python asyncio", "wikipedia Mount Everest", "what is this page about", "watch this website for changes" |
| Links | "save this link as facebook", "open my facebook link", "show my saved links" |
| Read later | "save this to read later at 9 pm", "show my list" |
| Text help (highlight first) | "explain this", "meaning of this word" (offline dictionary, 0 tokens), "translate this to Nepali", "summary of this paragraph", "improve this text", "what should I reply to my friend" |

### Make things (all free)

| Tool | Say |
|---|---|
| **Images** | "generate an image of a red panda in a bamboo forest", "make 4 versions of …", "make a phone wallpaper of Everest at night", "same picture but at night", "an HD image of …", "set it as my wallpaper" |
| **Charts** | "chart my expenses", "pie chart of my spending this week", "make a chart from sales.csv", "draw a graph of population by district from <link>" (also tables on government web pages) |
| **Diagrams** | "make a diagram of this project" (from its README only), "flowchart: wake up, brush, study", "diagram of this code" (who calls whom) |
| **Audio (MP3)** | "make an audio of this" (highlighted), "turn the last result into audio", "make an mp3 of <link>", "make an audio of notes.pdf" |
| **Short videos** | "make a short video about the Himalayas", "make a reel about momo", "create a video with this script: …", "make a slideshow from ~/Pictures/trip" |
| Long writing | "write a 1000-word essay about Nepal": a background job, saved to the Workspace |

### Music and video

| Say | Result |
|---|---|
| "play lofi music", "play nepali songs", "play kya mujhe pyar hai by KK" | sound only, no browser (about 30 MB). A named song plays first, then similar songs |
| "next", "previous", "pause", "play", "what song is this", "stop the music" | controls (0 tokens) |
| "increase the volume", "music volume 80" | the music's own volume while it plays |
| "play https://youtube.com/playlist?list=…", "play this playlist" (the tab open in Brave) | a YouTube playlist |
| "save this playlist as study", "play my study playlist", "shuffle my study playlist", "show my playlists" | your saved playlists |
| "play my music" | the files in `~/Music`, offline |
| "play despacito on youtube", "pause the video", "next video" | YouTube in Brave |
| "download this video in 720p", "download it as mp3" | video / audio downloads |
| "gesture control on" | control media with your hand (camera) |

While you speak to KURAMA, the music goes quieter so it can hear you, then comes back up. For keyboard media keys, run once: `sudo apt install mpv-mpris`.

### KURAMA itself

"what can you do", "do you have a tool for …", "change your name to Jarvis", "low RAM mode", "token usage", "summarize my day", "clear the chat", "make a tool that …" (KURAMA writes a small new tool and asks before running it).

---

## 6. Every `/command` (0 tokens)

Type `/` in the chat box: a list appears, so you can pick with the arrow keys and Enter.
- **Typos are fine:** `/wether` works.
- **Same list on Telegram:** send `/all`.

### Day
`/time [city]` · `/date [ad]` · `/weather [place]` · `/today` · `/todo [task]` · `/remind <what> <when>` · `/timer <min>` · `/alarm <time>` · `/goals` · `/links [name]` · `/notes [subject]` · `/contacts` · `/timetable` · `/quiz [subject]` · `/focus [min]` · `/digest` · `/spent <amount> <what>` · `/money [week|month|year]` · `/spending` · `/budget <amount>` · `/habits` · `/done <habit>` · `/brief`

### Laptop
`/status` · `/battery` · `/doctor` · `/ram` · `/freeram` · `/ports [port]` · `/screenshot` · `/lockscreen` · `/vol <up|down|N>` · `/bright <up|down|N>` · `/dark` · `/light` · `/dnd [on|off]` · `/internet` · `/clip` · `/jobs`

### Phone and safety
`/camera` · `/video [seconds]` · `/where` · `/here [name]` · `/history [laptop|phone] [hours]` · `/guard [on|off]` · `/track [on|off]` · `/mute [what] [min]` · `/unmute` · `/notifications` · `/clipnow` · `/control`, `/changepass`, `/lock`, `/unlock <pin>` (these four work on Telegram only)

### Code
`/def [name]` · `/args [name]` · `/run` · `/explain` · `/format` · `/check` · `/code` · `/projects` · `/git` · `/diagram` · `/flow <step, step>` · `/callgraph`

### Media
`/play` · `/pause` · `/next` · `/prev` · `/music [what]` · `/stopmusic` · `/playlists` · `/mymusic` · `/yt <what>` · `/image <prompt>` · `/chart [file|link]` · `/audio [link|file|text]` · `/makevideo <topic>` · `/reel <topic>` · `/download <link>`

### Web and text
`/search <words>` · `/news [topic]` · `/wiki <topic>` · `/page` · `/translate [language]` · `/meaning [word]` · `/summary` · `/calc <sum>`

### KURAMA
`/list` · `/tokens` · `/clearchat` · `/clear yes` · `/reset` · `/stop` · `/alerts`

---

## 7. How to use KURAMA every day

**The modes (buttons on the screen):** *text* (type, it answers in the chat), *voice* (mic button), and **talk** (the default).
In talk mode KURAMA sleeps until you say **"hey KURAMA"** / **"wake up KURAMA"**, then listens; say **"sleep now"** to make it wait for the wake word again. When the voice switch is on, it speaks in every mode.

**A normal day:**

| When | Try |
|---|---|
| Morning | Unlock the laptop and listen to the brief. "what do I have to do today", "weather", "what are my reminders" |
| Planning | "add finish the assignment to my to-do, it's urgent, due friday", "remind me to submit it friday at 4 pm" |
| During work | "open VS Code and youtube", "volume 30", "turn off bluetooth", "dark mode", "do not disturb on" |
| Finishing things | "done 1", "I finished the assignment", "exercise done" |
| Studying | "start focus mode 50", "play focus music", highlight a hard paragraph → "explain this", "note for DSA: …", evening: "start a quiz on DSA" |
| Coding | highlight → "find this function" / "is this correct syntax" / "run this code"; "generate requirements.txt"; "convert this notebook to python"; "check dependencies"; "what is running on port 8000"; end of day: "where was I", "commit my changes" |
| Files | "find naruto.jpg and send it to my telegram", "what's in my downloads", "organize my downloads" |
| Spending | right after paying: "spent 150 on momo and 40 on tea"; weekly: "spending breakdown this week"; month end: "chart my expenses" |
| Habits | "add a habit: …" once, then just "did exercise" |
| Away from the laptop | on Telegram: `/status`, `/where`, `/camera`, `/control`, or "send me the report" |
| Making things | "make a reel about …", "make 4 versions of …", "make an audio of this" for revision on the go |
| Night | "summarize my day", "token usage", "sleep now" (KURAMA), or "shut down the laptop" (asks yes/no) |

**When KURAMA gets something wrong:** paste the chat log to Claude Code. Each line shows the route, tokens and time, so the exact cause can be found and fixed.

---

<!-- TOOLS:START -->

## 8. Every tool in detail

Generated from the tools themselves by `scripts/gen_tool_guide.py` (rerun it after changing tools).
- **Runs at once** means it just does it. **Asks first** means it waits for your yes.
- The **Say** lines are examples. Your own words work too (English, Nepali, Hindi).

### 8a. The 17 tools the AI chooses from

Each one takes an **action** and a few words, and hands the work to the specialised tools in 8b.

#### `apps`

Open an app, website or folder by name; close or force-kill an app; arrange a window (minimize/maximize/left/right/focus); press keys, type or click in the app in front; install an app.

- **Safety:** runs at once (anything risky underneath still asks)
- **Actions:** `open`, `close` → close_app, `kill` → kill_app, `window` → window, `press` → app_control, `type` → app_control, `click` → app_control, `install` → install_app
- **Say:** “open VS Code” · “open youtube and facebook” · “open the tara folder” · “close Brave” · “kill the frozen app” · “snap this window left” · “press ctrl+t” · “install VLC”

#### `laptop`

Laptop settings and health: volume, brightness, wifi, bluetooth, airplane, power mode, night light, theme, do-not-disturb, wallpaper, screenshot, screen off, battery, health (RAM/CPU/top apps), free RAM, internet check, clean disk, focus session, lock, sleep, shutdown, restart, log out.

- **Safety:** runs at once (anything risky underneath still asks)
- **Actions:** `volume`, `brightness`, `wifi` → laptop_toggle, `bluetooth` → laptop_toggle, `airplane` → laptop_toggle, `power_mode` → laptop_toggle, `night_light` → night_light, `theme` → set_theme, `dnd` → do_not_disturb, `wallpaper` → set_wallpaper, `screenshot` → screenshot, `screen_off` → laptop_toggle, `battery` → battery_status, `health` → laptop_doctor, `free_ram` → laptop_doctor, `internet` → internet_doctor, `clean_disk` → disk_cleaner, `focus` → focus_mode, `lock` → lock_screen, `sleep` → suspend_computer, `shutdown` → power_off, `restart` → power_off, `logout` → power_off
- **Say:** “volume 40” · “brightness up” · “turn off bluetooth” · “dark mode” · “night light on” · “do not disturb on” · “battery” · “why is my laptop slow” · “free up some ram” · “check my internet” · “take a screenshot” · “next wallpaper” · “lock the screen” · “shut down the laptop”

#### `files`

Files and folders anywhere on the laptop: list a folder, find files by name, read, write, make a folder, move, copy, delete (to trash, asks first), organize a messy folder, convert a file, lock a folder.

- **Safety:** runs at once (anything risky underneath still asks)
- **Actions:** `list` → list_folder, `find` → find_files, `read` → read_text, `write` → write_file, `mkdir` → make_folder, `move` → move_path, `copy` → copy_path, `delete` → delete_to_trash, `organize` → organize_files, `convert` → convert_file, `lock` → folder_lock
- **Say:** “find my resume pdf” · “what's in my downloads” · “read notes.txt” · “make a folder called notes on the desktop” · “move report.pdf to Documents” · “delete this file” · “organize my downloads” · “convert report.docx to pdf” · “lock the private folder”

#### `telegram`

Send to the user's Telegram: a text message, a file (give a path or just its name: it is found on the laptop), or the latest thing made (picture, document, list).

- **Safety:** runs at once (anything risky underneath still asks)
- **Actions:** `message` → send_message_telegram, `file` → send_file_telegram, `latest` → send_last_result
- **Say:** “send naruto.jpg to my telegram” · “find tools.py and send it to me” · “send this photo” · “message me on telegram: leaving now” · “send the last result to my phone”

#### `schedule`

Alerts in time: remind (a reminder at a time), alarm (rings), timer (countdown), stopwatch; list, cancel, move or rename one; run_later = KURAMA does a command later. Not for to-dos (use todo).

- **Safety:** runs at once (anything risky underneath still asks)
- **Actions:** `remind` → add_reminder, `alarm` → set_alarm, `timer` → set_timer, `stopwatch` → stopwatch, `list` → schedules, `cancel` → schedules, `move` → schedules, `rename` → schedules, `run_later` → schedule_command
- **Say:** “remind me to call mom at 5 pm” · “alarm at 6 am” · “timer 10 minutes” · “start the stopwatch” · “what are my reminders” · “move the call reminder to 7 pm” · “cancel the 6 am alarm”

#### `todo`

The user's to-do list (tasks to do, with optional due date, priority, tag): add, list, today, done, delete, edit, clear. A to-do does not ring; use 'remind' only if the user also wants an alert.

- **Safety:** runs at once (anything risky underneath still asks)
- **Say:** “add buy milk to my to-do #shopping tomorrow” · “add finish the report, it's urgent” · “show my to-do list” · “what do I have to do today” · “done 2” · “delete the bank task” · “clear finished to-dos”

#### `media`

Music and video: play a song, artist or playlist (sound only), pause, resume, next, previous, stop, what's playing, play on YouTube, hand-gesture media control on/off, download a video.

- **Safety:** runs at once (anything risky underneath still asks)
- **Actions:** `play` → music, `pause` → media_control, `resume` → media_control, `next` → media_control, `previous` → media_control, `stop` → music, `playing` → music, `youtube` → youtube, `gesture` → gesture_control, `download` → video_download
- **Say:** “play lofi music” · “play kya mujhe pyar hai by KK” · “next” · “pause” · “what song is this” · “stop the music” · “play despacito on youtube” · “download this video in 720p” · “gesture control on”

#### `web`

Internet answers: live (match results, news, scores, prices, anything recent), search, read a web page, this_page (the page open in the browser), wiki, watch a page for a word.

- **Safety:** runs at once (anything risky underneath still asks)
- **Actions:** `live` → live_search, `search` → web_search, `read` → read_webpage, `this_page` → page_summary, `wiki` → wikipedia, `watch` → web_watch
- **Say:** “latest news about Nepal” · “gold price today” · “arsenal score” · “search the web for python asyncio” · “what is this page about” · “wikipedia Mount Everest” · “watch this page for the word 'result'”

#### `info`

Quick facts: time (any place), date (also Nepali BS calendar), weather (any place, days ahead), calculate (math, %, units), contact (find a phone number), save_contact, phone_location, find_phone, laptop_location.

- **Safety:** runs at once (anything risky underneath still asks)
- **Actions:** `time` → get_time, `date` → get_date, `weather` → weather, `calculate` → calculate, `contact` → contacts, `save_contact` → contacts, `phone_location` → location_history, `find_phone` → find_my_phone, `laptop_location` → laptop_guard
- **Say:** “what time is it in Tokyo” · “what's the date today” · “weather in Pokhara tomorrow” · “15% of 2400” · “convert 100 usd to npr” · “what's Ram's number” · “where is my phone” · “where is my laptop”

#### `memory`

Memory: remember a fact, recall what you know about the user, forget, past_chat (what we talked about), save_link / get_link, read_later (save this link) / reading_list, ask_docs (the user's own notes and code), workspace (read a result).

- **Safety:** runs at once (anything risky underneath still asks)
- **Actions:** `remember` → remember, `recall` → recall, `forget` → forget, `past_chat` → recall_session, `save_link` → saved_links, `get_link` → saved_links, `read_later` → read_later, `reading_list` → read_later, `ask_docs` → ask_knowledge, `workspace` → read_workspace
- **Say:** “remember that my exam is on Nov 25” · “what do you know about me” · “forget that” · “what did we talk about yesterday” · “save this link as facebook” · “open my facebook link” · “save this to read later” · “what do my notes say about stacks”

#### `create`

Make something: image (picture; can also set it as wallpaper or send it to Telegram), document (essay, article, report: runs in the background), audio (speech from text or the selection), chart (e.g. of my spending), diagram, video.

- **Safety:** runs at once (anything risky underneath still asks)
- **Actions:** `image` → generate_image, `document` → write_document, `audio` → make_audio, `chart` → make_chart, `diagram` → make_diagram, `video` → make_video
- **Say:** “generate an image of a red panda” · “make a phone wallpaper of Everest at night” · “write a 1000-word essay about Nepal” · “make an audio of this” · “chart my expenses” · “make a diagram of this project” · “make a short video about the Himalayas”

#### `text`

The selected text / screen: explain, meaning, translate, improve (fix wording), summary, reply, code (write code for it); read_screen (OCR); clipboard (what was copied, history); copy; dictate (start/stop typing by voice); qr (scan a QR code).

- **Safety:** runs at once (anything risky underneath still asks)
- **Actions:** `explain` → text_assist, `meaning` → text_assist, `translate` → text_assist, `improve` → text_assist, `summary` → text_assist, `reply` → text_assist, `code` → text_assist, `read_screen` → read_text, `clipboard` → clipboard, `copy` → clipboard, `dictate` → dictate, `qr` → scan_qr
- **Say:** “explain this” · “meaning of this word” · “translate this to Nepali” · “improve this text” · “summary of this” · “what should I reply to my friend” · “read the text on the screen” · “what did I copy 10 minutes ago” · “start dictation” · “scan the QR code”

#### `code`

Coding help: fix_error (explain an error/traceback), run_tests, where_was_i, changes (what changed lately), git (status/log/diff), commit, new_project, env (check / install a package), requirements (make requirements.txt from imports), notebook_to_py (.ipynb -> .py), check_deps (missing/unpinned/outdated packages), review, training (ML training / Colab status).

- **Safety:** runs at once (anything risky underneath still asks)
- **Actions:** `fix_error` → fix_error, `run_tests` → run_tests, `where_was_i` → where_was_i, `changes` → time_machine, `git` → git_info, `commit` → git_change, `new_project` → scaffold_project, `env` → python_env, `requirements` → generate_requirements, `notebook_to_py` → notebook_to_script, `check_deps` → dependency_doctor, `review` → review_code, `training` → training
- **Say:** “what does this error mean” · “run the tests” · “where was I” · “what changed in the last hour” · “git status” · “commit my changes” · “generate requirements.txt” · “convert this notebook to python” · “check dependencies” · “review my code” · “how's training”

#### `life`

Personal trackers: spent (log spending), money (report), budget, habit (new), habit_done, habits, goals (long tasks), add_goal, timetable (classes), notes (study notes), quiz, lecture (record), day_summary (what we did today), tokens (AI usage).

- **Safety:** runs at once (anything risky underneath still asks)
- **Actions:** `spent` → expenses, `money` → expenses, `budget` → expenses, `habit` → habits, `habit_done` → habits, `habits` → habits, `goals` → goals, `add_goal` → goals, `timetable` → timetable, `notes` → study_notes, `quiz` → quiz, `lecture` → lecture, `day_summary` → daily_digest, `tokens` → token_usage
- **Say:** “spent 200 on momo and 50 on tea” · “how much did I spend this month” · “set my food budget to 8000” · “add a habit: drink water” · “exercise done” · “my habits” · “show my long tasks” · “show my timetable” · “note for DSA: stacks are LIFO” · “start a quiz on DSA” · “record this lecture” · “summarize my day” · “token usage”

#### `kurama`

About KURAMA: about (what you are, where things are stored), can_you (is there a way to do X), rename, mode (power mode), jobs (background jobs), clear_chat, mute_alerts, remote (remote desktop on/off), make_tool (build a small new tool when nothing else fits).

- **Safety:** runs at once (anything risky underneath still asks)
- **Actions:** `about` → about_me, `can_you` → find_capability, `rename` → set_my_name, `mode` → power_mode, `jobs` → jobs, `clear_chat` → reset_kurama, `mute_alerts` → mute_alerts, `remote` → remote_desktop, `make_tool` → make_tool
- **Say:** “what can you do” · “do you have a tool for renaming photos” · “change your name to Jarvis” · “low RAM mode” · “show my jobs” · “clear the chat” · “mute RAM alerts for 20 minutes” · “make a tool that counts words in a file”

#### `run_command`

Run one terminal command on the laptop (bash) and return its output; asks the user first, every time. Use for things no other tool does (file sizes, git, pip, system info...). Never sudo.

- **Safety:** asks first, every time
- **Say:** “run the command du -sh ~/Downloads” · “how big is my home folder” · “list the files in /tmp with sizes”

#### `run_python`

Run a short Python program on the laptop and return what it prints; asks the user first, every time. Use when no other tool fits (math on data, file work, quick scripts).

- **Safety:** asks first, every time
- **Say:** “use python to count the lines in all .py files here” · “write and run code that sums column B of sales.csv”

### 8b. The 129 specialised tools underneath

The AI never sees these directly; the 17 tools above and the instant shortcuts use them. Under **What it understands** are the settings filled in from your words.

#### Everyday (14)

Time, weather, reminders, maths, files to convert.

##### `add_reminder`: Remind the user of a task / work / to-do at a time ('schedule reading the book at 11:45 pm'), once or repeating; alerts on desktop, Telegram and by voice.
- **Safety:** runs at once
- **What it understands:** `text`: What to remind about (e.g. "call mom").
  - `when`: Time phrase, e.g. "at 5 pm", "in 20 minutes", "tomorrow at 9", "every weekday at 9:30".
- **Say:** “remind me to call mom at 5” · “remind me to drink water in 30 minutes” · “remind me every day at 9 pm to study” · `/remind call ram at 6 pm`
- **Tip:** A heads-up 10 minutes before; also on Telegram.

##### `calculate`: Do math (+ - * / ^ %, sqrt, percent of), convert units (km, kg, °C, GB, hours...) or money with today's rate (100 USD to NPR).
- **Safety:** runs at once
- **What it understands:** `expression`: e.g. "18% of 2500", "(45*3)+12", "sqrt(144)", "10 km to miles", "100 f to c", "50 dollars to NPR".
- **Say:** “15% of 2400” · “calculate 1250 * 12” · “sqrt 144” · `/calc 99*99`
- **Tip:** Done locally: 0 tokens.

##### `convert_file`: Convert files locally: pdf<->md/txt/images/docx, md/txt/html->pdf, jpg<->png/webp/ico, images->pdf, docx/pptx/xlsx->pdf, mp4->mp3/gif, mov/mkv->mp4, csv<->xlsx<->json, image->text (OCR). A folder converts all its files of src_ext.
- **Safety:** runs at once
- **What it understands:** `path`: The file or folder (a path, a name to find, or 'this' for the file just mentioned/newest download).
  - `to`: Target format: pdf, md, txt, html, png, jpg, webp, ico, docx, mp3, mp4, gif, csv, xlsx, json ...
  - `src_ext`: For a folder (or 'this pdf'): which files to convert, e.g. jpg.
- **Say:** “convert this pdf to markdown” · “convert report.docx to pdf” · “convert video.mp4 to mp3” · “convert photo.png to jpg”
- **Tip:** Big conversions run in the background. 'this' = the file you have open/selected.

##### `disk_cleaner`: Disk space: what is using it (biggest folders, Hugging Face/pip/torch caches, old checkpoints, venvs of old projects, duplicates, trash, old downloads) and clean a category after asking.
- **Safety:** runs at once
- **What it understands:** `action`: scan = report (deletes nothing); clean = free `category` (asks first).
  - `category`: hf_cache, torch_cache, pip_cache, trash, old_downloads, checkpoints, dead_venvs, pycache, duplicates.
  - `path`: For scan: also list the biggest folders inside this folder.
- **Say:** “clean my disk” · “what is taking my disk space” · “clean the cache”
- **Tip:** Shows what it will delete and asks first.

##### `get_date`: Today's date and weekday. Nepali Bikram Sambat by default; calendar='ad' only if the user asks for English/AD; week=True only if they ask which week.
- **Safety:** runs at once
- **What it understands:** `calendar`: 'bs' = Nepali Bikram Sambat (default), 'ad' = English/Gregorian.
  - `week`: also say the week of the year (only when asked).
- **Say:** “what is the date today” · “date in AD” · “which week is this” · “aajako miti” · `/date`
- **Tip:** Nepali Bikram Sambat by default; say 'in AD' for the English date.

##### `get_time`: Get the current date and time, locally or in any city or country.
- **Safety:** runs at once
- **What it understands:** `place`: City or country for world time; empty = local time.
- **Say:** “what time is it” · “what time is it in Tokyo” · `/time london`

##### `goals`: Long goals (weeks-months, Excel): exam countdown reminders, project daily check-in question + progress log, today's/week's summary, progress, edit, pause, done, formatted report.
- **Safety:** runs at once
- **What it understands:** `action`: add (new goal), list, status (progress, days left), today / week (what was done), log (save a progress note), edit, pause, resume, done, delete, report (formatted report in its folder), link (git repo).
  - `goal`: which existing goal (its name).
  - `name`: the new goal's name (add) or a new name (edit), e.g. 'Physics exam', 'KURAMA app'.
  - `end`: end date, e.g. 'in 30 days', 'in 6 months', 'November 28'.
  - `remind`: reminder times, e.g. '7 am and 8 pm', 'twice a day', 'off'.
  - `ask`: the daily check-in question ('yes' = the default one, 'off' = stop asking).
  - `ask_at`: time of the check-in question, e.g. '9 pm'.
  - `text`: the progress note (log).
  - `status`: edit only: active, paused, done.
  - `repo`: git folder (link); empty = the current coding project.
- **Say:** “my exam is in 30 days, remind me every day” · “show my long tasks” · “how many days until the exam” · “today I wrote chapter 2 of the thesis” · “move the exam to December 2” · “make the thesis report”
- **Tip:** Long tasks only (weeks/months). Short tasks are the to-do list (read_later).

##### `organize_files`: Smart organize a messy folder (Downloads by default): plan in the background (real names for files like IMG_2031, topic folders for documents), shown in the workspace; then apply it (yes), change it (edit + what to change), cancel it (no), or undo the last run.
- **Safety:** runs at once
- **What it understands:** `action`: organize (make a plan), apply (the waiting plan: the user said yes), edit (change the waiting plan as `change` says), cancel (the user said no), undo (the last organize).
  - `folder`: The folder to organize (loose names work; default Downloads).
  - `change`: For edit: what to change, e.g. "keep the pictures where they are".
  - `rename`: Also give meaningless names real ones (False = only sort into folders).
- **Say:** “organize my downloads” · “organize the Documents folder” · “undo the organizing”
- **Tip:** Shows a plan in the Workspace; answer 'yes', 'no' or a change ('keep the pictures where they are').

##### `schedule_command`: Make KURAMA RUN an action later or repeatedly (e.g. 'weather in Kathmandu' every day at 8, shut down at 11). NOT for tasks/work the user will do (reading, studying, calls): use add_reminder.
- **Safety:** asks first
- **What it understands:** `command`: The request to run, as the user would say it (e.g. "daily digest").
  - `when`: Time phrase, e.g. "at 7 am", "in 1 hour", "every day at 8am", "every 30 minutes".
- **Say:** “every day at 10 pm back up my documents” · “at 11 pm shut down the laptop”
- **Tip:** Runs a KURAMA action at a time (not a reminder for you). Asks first.

##### `schedules`: List pending reminders, alarms and scheduled commands; cancel, move (new time) or rename one.
- **Safety:** runs at once
- **What it understands:** `action`: list = what is pending, cancel / move / rename `item`.
  - `item`: The id or words from the reminder.
  - `when`: The new time (move), e.g. "6 pm", "tomorrow at 9".
  - `text`: The new wording (rename).
- **Say:** “what reminders do I have” · “cancel the 5 pm reminder” · “show my schedule”

##### `set_alarm`: Set an alarm at a time (rings with sound; can repeat daily/weekdays).
- **Safety:** runs at once
- **What it understands:** `when`: The time, e.g. "6 am", "tomorrow at 7:30", "every day at 6", "every weekday at 6:30".
  - `label`: What it's for, optional ("go for a walk").
- **Say:** “set an alarm for 6 am” · “wake me up at 5:30” · `/alarm 6 am`

##### `set_timer`: Start a countdown timer that rings when it ends.
- **Safety:** runs at once
- **What it understands:** `minutes`: Minutes.
  - `seconds`: Seconds.
  - `hours`: Hours.
  - `label`: What it's for ("tea", "pasta"), optional.
  - `phone`: Also message the user's phone (Telegram) when it rings, if they ask for that.
- **Say:** “timer 10 minutes” · “set a timer for 25 minutes” · `/timer 5`

##### `stopwatch`: Stopwatch: start, stop, lap, reset or check the time.
- **Safety:** runs at once
- **What it understands:** `action`: start, stop (pause), lap, reset or status.
- **Say:** “start the stopwatch” · “stop the stopwatch” · “lap”
- **Tip:** Also shows on the Now & today card.

##### `weather`: Current weather and up to 3-day forecast for any city or country.
- **Safety:** runs at once
- **What it understands:** `place`: City, town or country (any spelling); empty = the user's home place.
  - `days`: 1 = today, 2 = include tomorrow, up to 3.
- **Say:** “weather” · “weather in Pokhara tomorrow” · “will it rain today” · `/weather kathmandu`
- **Tip:** Up to 3 days ahead.

#### Money & habits (2)

Your spending and daily habits, kept in Excel sheets you can also edit.

##### `expenses`: Money tracker: add an expense/income ('spent 500 on food'), report for today/week/month/year (optionally one category), breakdown by every category, list, delete, edit the last one, set a monthly budget, add a monthly bill reminder or mark a bill paid.
- **Safety:** runs at once
- **What it understands:** `action`: add (text = what was spent/earned), report, breakdown (every category + budgets + totals), list, delete (text = 'last' or row number), edit (text = the change to the last one), budget (category + amount; category 'total' = whole month), bill (text = name, amount, day of month), pay (text = the bill name).
  - `text`: The user's words for add / delete / edit / bill / pay.
  - `period`: For report and list.
  - `category`: For report (one category) or budget.
  - `amount`: For budget or bill.
  - `day`: Day of the month for a bill.
- **Say:** “spent 200 on meat, 50 on tomato and 500 on vegetables” · “got 20000 salary” · “spent 300 on bus on October 20” · “how much did I spend this month” · “how much did I spend on food from Oct 1 to Oct 15” · “spending breakdown” · “set my food budget to 8000” · “remind me to pay internet 1500 every month on the 5th” · “paid internet” · “delete the last expense” · `/money week`
- **Tip:** Click the Money & habits card for the Money window (dates, categories, delete rows).

##### `habits`: Daily habits with streaks: add a habit (name, target per day, reminder time), check in ('I drank water'), status (streaks, what's left today), undo today's check-in, delete.
- **Safety:** runs at once
- **What it understands:** `action`: status, add (text = 'drink water 8 glasses a day remind me at 10 am'), done (text = what the user did), undo (text = the habit), delete (text = the habit).
  - `text`: The user's words.
- **Say:** “add a habit: drink water 8 glasses a day, remind me at 10 am” · “I drank 2 glasses of water” · “did exercise” · “my habits” · “I didn't do exercise” · “delete the water habit” · `/done exercise`
- **Tip:** Streaks and the last 7 days show on the Money & habits card (✓ button = done today).

#### Study & memory (12)

Notes, quizzes, classes, things KURAMA remembers, search in your own files.

##### `ask_knowledge`: Answer a question about the user's own code, docs or notes (also 'what is this project about'), citing file paths.
- **Safety:** runs at once
- **What it understands:** `question`: The question, e.g. "how does the fast path work?".
- **Say:** “according to my notes, what is a heap” · “what does my project README say about setup”

##### `contacts`: Contacts sheet (Excel): save a person's phone number, find someone's number (fuzzy name or part of the number), list all, change a number, or delete a contact.
- **Safety:** runs at once
- **What it understands:** `action`: add, find, list, update (new number), delete.
  - `name`: The person's name (or part of a number for find).
  - `phone`: The phone number (add/update).
  - `note`: Optional note, e.g. 'college friend'.
- **Say:** “what's Ram's number” · “add Sita 9812345678” · “show my contacts”
- **Tip:** Excel: ~/Documents/KURAMA/contacts.xlsx.

##### `forget`: Delete remembered notes (last, all, or by id) or a learned fact about the user.
- **Safety:** asks first
- **What it understands:** `which`: "last", "all", or a note id number (ignored when fact is given).
  - `fact`: A learned fact to forget, e.g. "I live in Pokhara" or "favourite editor".
- **Say:** “forget that” · “forget my exam date”

##### `index_folder`: Index a folder of code or notes (incremental, runs in the background) so it can be searched.
- **Safety:** runs at once
- **What it understands:** `path`: Folder (or file) to index; empty = the configured roots (this project and ~/notes).
- **Say:** “index my Notes folder” · “learn my project folder”
- **Tip:** So you can ask questions about your own files.

##### `lecture`: Lecture recorder: start recording a class (mic, or 'laptop' sound for an online class), stop it (transcript written in the background into Notes/Lectures), status, or summarize the last lecture.
- **Safety:** runs at once
- **What it understands:** `action`: start, stop, status, or summarize (the latest transcript; ~1-2k tokens).
  - `title`: Name of the lecture, e.g. "DSA trees".
  - `source`: mic = a class in the room; laptop = the laptop's own sound (Zoom/Meet/YouTube class).
- **Say:** “record this lecture” · “record the online class” · “stop recording and give me notes”
- **Tip:** Records the mic or the laptop's sound, then makes notes.

##### `quiz`: Study quiz from the user's notes with spaced repetition: make questions for a subject, ask the next due one, show its answer, grade it (right/wrong), or stats.
- **Safety:** runs at once
- **What it understands:** `action`: ask = next due question; make = new questions from `subject` notes; answer = show the answer; right / wrong = how it went; stats = progress.
  - `subject`: e.g. "DSA" (empty = any).
- **Say:** “start a quiz on DSA” · “next question” · “the answer is B” · “my quiz stats”
- **Tip:** Spaced repetition from your own notes.

##### `recall`: Recall remembered notes (all, last, search) or what you know about the user (profile).
- **Safety:** runs at once
- **What it understands:** `which`: "all" (newest 10), "last" (most recent note), "search" (notes containing query) or "profile" (facts about the user).
  - `query`: Text to look for when which is "search".
  - `limit`: Max notes to return.
- **Say:** “what do you know about me” · “what did I tell you about the exam”

##### `recall_session`: Recall past conversations: the last session, a day (yesterday, a weekday, YYYY-MM-DD) or a topic.
- **Safety:** runs at once
- **What it understands:** `query`: "last", "today", "yesterday", a weekday, a date like 2026-10-22, or words to search for.
- **Say:** “what did we talk about yesterday” · “what was that link from this morning”

##### `remember`: Save a short note or fact the user asks you to remember.
- **Safety:** runs at once
- **What it understands:** `text`: Exactly what to remember, e.g. "1234" or "the wifi password is on the fridge".
- **Say:** “remember that my exam is on Nov 25” · “remember I like lofi music”

##### `search_knowledge`: Search the user's own code, docs and notes; returns file:lines with short snippets.
- **Safety:** runs at once
- **What it understands:** `query`: What to look for, in plain words.
  - `k`: Number of hits (1-8).
- **Say:** “search my notes for recursion” · “find where I wrote about the API key”

##### `study_notes`: Study notes: save a note under a subject (auto-picked if not said) in ~/Notes, show the notes of a subject for the last N days, or list subjects.
- **Safety:** runs at once
- **What it understands:** `action`: add = save `text`; show = notes of `subject` (or all) for the last `days`; subjects = list them.
  - `text`: The note.
  - `subject`: e.g. "DSA", "Machine Learning" (empty = picked from your subjects).
  - `days`: How far back to show.
- **Say:** “note for DSA: a stack is LIFO” · “show my DSA notes” · “show my notes from this week”
- **Tip:** Saved in ~/Notes by subject.

##### `timetable`: Class timetable: save it (pasted text, one class per line), show today/tomorrow/the week, or the next class; reminds before each class.
- **Safety:** runs at once
- **What it understands:** `action`: today, tomorrow, week, next, or set (save `text` as the timetable).
  - `text`: The timetable, e.g. "Mon 9:00-10:00 DSA Room 201" per line (other layouts work too).
- **Say:** “show my timetable” · “what classes do I have today”
- **Tip:** Paste your timetable once; it reminds you before classes.

#### Laptop control (33)

Volume, screen, apps, windows, power, health of the laptop.

##### `app_control`: Control the app on screen: tab/page shortcuts, press keys, type text, click a named button/tab/menu, or do any free-form task in an app (e.g. 'turn on dark mode in settings').
- **Safety:** runs at once
- **What it understands:** `action`: task (free-form, multi-step), click (a named element), type (text), press (keys like 'ctrl t'), shortcut (new_tab, close_tab, back, reload, zoom_in, tab:3 ...), enable (one-time setup for browsers).
  - `text`: The task, element name, text, keys or shortcut name.
  - `app`: Optional app to bring to the front first (brave, files, terminal, code, settings).
- **Say:** “press ctrl+t” · “new tab” · “go to tab 3” · “click the Save button” · “scroll down”
- **Tip:** Keys and clicks in the app in front.

##### `audio`: Sound: get/set/step the speaker volume, or mute/unmute the speakers or the microphone.
- **Safety:** runs at once
- **What it understands:** `action`: get/set/up/down = speaker volume; mute/unmute/toggle/status = muting.
  - `target`: speakers (default) or mic (microphone: mute/unmute/toggle/status only).
  - `level`: Volume 0-100 for action=set.
  - `step`: How much to go up/down (0 = default step).
- **Say:** “volume 40” · “volume up” · “mute” · “unmute” · “mute the mic” · “set volume to 130” · `/vol up`
- **Tip:** Up to 150% when Ubuntu's Over-Amplification is on. While KURAMA's music plays, 'volume up' changes the music.

##### `battery_status`: Battery level, charging state, time remaining and battery health.
- **Safety:** runs at once
- **Say:** “battery” · “how long will the battery last” · `/battery`

##### `brightness`: Get, set (percent) or step the screen brightness up/down.
- **Safety:** runs at once
- **What it understands:** `action`: get, set (needs level), up or down (by step).
  - `level`: Target brightness percent for action=set.
  - `step`: Percent to change for up/down (default 10).
- **Say:** “brightness 60” · “brightness up” · `/bright down`

##### `close_app`: Close all open windows of an app by name (like clicking X).
- **Safety:** runs at once
- **What it understands:** `name`: The app's name or part of a window title, e.g. "vs code", "files", "firefox".
- **Say:** “close Brave” · “close Spotify”

##### `daily_digest`: Give the daily digest (conversations, jobs, alerts, notes, tokens, git commits, weather).
- **Safety:** runs at once
- **What it understands:** `date`: "today", "yesterday", a weekday or YYYY-MM-DD.
- **Say:** “summarize my day” · “daily digest” · `/digest`
- **Tip:** Also sent by itself at 10 PM.

##### `dictate`: Speech-to-text (STT) / voice typing / dictation mode: type what the user says into whatever app has the cursor (English, Nepali, Hindi) until they say 'stop dictation'; or turn it off.
- **Safety:** runs at once
- **What it understands:** `action`: start or stop.
  - `lang`: The language spoken (auto = detect each phrase).
- **Say:** “start dictation” · “start dictation in Nepali” · “stop dictation”
- **Tip:** Types what you say into any app; say 'new line', 'change paragraph', 'undo', 'stop'.

##### `do_not_disturb`: Turn Do Not Disturb (hide notification pop-ups) on or off.
- **Safety:** runs at once
- **What it understands:** `action`: on, off, toggle, or status.
- **Say:** “do not disturb on” · “turn off do not disturb” · `/dnd on`

##### `find_my_phone`: Find my phone: open Google Find My Device (Android) or Find My iPhone in the browser, to see the phone's location on a map and ring, lock or erase it. Free, no app needed (sign in with the phone's own account).
- **Safety:** runs at once
- **What it understands:** `phone`: android (Google Find My Device) or iphone (Find My iPhone).
  - `want`: location = the last location the phone shared on Telegram (opens the page only if there is none); open = open the find-my-phone page (to see it live, ring, lock or erase it).
- **Say:** “where is my phone” · “give me the location I shared on Telegram” · “find my phone” · “ring my phone”
- **Tip:** 'where' = the last location your phone shared with the bot; 'find / ring' opens Google Find My Device.

##### `focus_mode`: Start or stop a timed focus (pomodoro) session: Do Not Disturb on, alert when done.
- **Safety:** runs at once
- **What it understands:** `minutes`: Session length in minutes (1-240).
  - `action`: start, stop, or status.
- **Say:** “start focus mode” · “focus for 50 minutes” · “stop focus mode” · `/focus 25`
- **Tip:** DND on, then an alert when time is up.

##### `install_app`: Install or uninstall any app (finds it in apt, snap or flatpak), search for one, or update all apps. Ubuntu shows its own password popup on the laptop.
- **Safety:** asks first
- **What it understands:** `action`: install, remove (uninstall), search (show matches), update (everything).
  - `name`: The app, e.g. 'obs', 'postman', 'vs code', 'vlc'.
- **Say:** “install VLC” · “install obs studio”
- **Tip:** apt / snap / flatpak through a password popup.

##### `internet_doctor`: Internet doctor: find why the internet is slow or not working (Wi-Fi, router, provider, DNS), speed test, or tell the user when it is back. Use reconnect / fix_dns ONLY when the check found that problem or the user asks for it.
- **Safety:** runs at once
- **What it understands:** `action`: check = find the broken link; speed = download speed test (~10 MB); reconnect = restart the Wi-Fi connection; fix_dns = use 1.1.1.1 / 8.8.8.8; notify_when_back = message the user when it works again.
- **Say:** “check my internet” · “fix my internet” · “how fast is my connection” · `/internet`

##### `kill_app`: Force-quit an app that is frozen or won't close (kills its processes).
- **Safety:** asks first
- **What it understands:** `name`: App or process name, or "frozen"/"this" for the focused window's app.
  - `force`: Kill immediately (SIGKILL) instead of asking it to quit first.
- **Say:** “kill the frozen app” · “force quit VS Code”
- **Tip:** Asks first. Never touches KURAMA or system processes.

##### `laptop_doctor`: Laptop doctor: why it's slow (RAM/swap per app, CPU hogs, heat, full disks, updates), free RAM by stopping idle Jupyter kernels, what's using a port, stop a process (asks first), KURAMA's own health.
- **Safety:** runs at once
- **What it understands:** `action`: check = diagnose; free_ram = stop idle Jupyter kernels; port = what is listening (on `target` port, or all); stop = stop the process `target` (PID or name) or what is on port `target`; kurama = KURAMA's own memory and workers.
  - `target`: A port number, PID or process name, depending on the action.
- **Say:** “why is my laptop slow” · “free up some ram” · “what is running on port 8080” · “show my open ports” · “free port 3000” · `/doctor` · `/ports`
- **Tip:** Stopping anything asks first; KURAMA itself is never stopped.

##### `laptop_guard`: Laptop guard (anti-theft): on/off; while on, a webcam photo + location goes to Telegram when someone unlocks it, types a wrong password or wakes it. 'where' = where the laptop is now.
- **Safety:** runs at once
- **What it understands:** `action`: on / off / status, where = Wi-Fi + IP + rough location, photo = webcam photo to Telegram now, track_off = stop lost mode's location messages (the guard stays as it is).
- **Say:** “turn on the guard” · “is the guard on” · `/guard on`
- **Tip:** While armed: a photo + location to Telegram when someone unlocks the laptop.

##### `laptop_toggle`: Laptop switches: Wi-Fi, Bluetooth, airplane mode on/off, power mode (saver/balanced/performance), screen off.
- **Safety:** runs at once
- **What it understands:** `setting`: wifi, bluetooth, airplane, power_mode or screen.
  - `state`: on / off / status; for power_mode: saver, balanced or performance; for screen: off.
- **Say:** “turn off wifi” · “turn on bluetooth” · “airplane mode on”
- **Tip:** Same as the switches on the Laptop card.

##### `location_history`: Show the laptop's (or phone's) location history: where it's been over the last N hours, as a summary plus a map opened in the browser. The phone's trail comes from live location you share with KURAMA on Telegram.
- **Safety:** runs at once
- **What it understands:** `device`: laptop or phone.
  - `hours`: how far back to look (default 24).
  - `open_map`: also open a map of the trail in the browser.
- **Say:** “where is my laptop” · “where has my laptop been today” · `/where` · `/history phone 12`

##### `lock_screen`: Lock the screen.
- **Safety:** runs at once
- **Say:** “lock the screen” · `/lockscreen`

##### `night_light`: Turn Night Light (warm screen) on or off, or set its warmth in kelvin.
- **Safety:** runs at once
- **What it understands:** `action`: on, off, toggle, or status.
  - `temperature`: Optional warmth in kelvin, 1700 (very warm) to 4700 (mild).
- **Say:** “night light on” · “turn off the night light”

##### `open_app`: Open/launch an installed desktop app by name (vs code, files, terminal, settings, firefox).
- **Safety:** runs at once
- **What it understands:** `name`: The app's name as spoken, e.g. "vs code", "files", "terminal", "calculator".
- **Say:** “open VS Code” · “open Brave” · “open the calculator”

##### `power_mode`: Switch KURAMA's power mode to save RAM (full, smart, normal, basic, lowram, laptop, noai) or tell the current one.
- **Safety:** runs at once
- **What it understands:** `mode`: "status" = say the current mode; full = everything on; smart = best AI for everything; normal = the usual KURAMA; basic = important helpers only; lowram = laptop busy (small screen, small AI); laptop = no background helpers; noai = 0 tokens, built-in commands only.
- **Say:** “low RAM mode” · “normal mode” · “full mode” · “which mode am I in”
- **Tip:** How many helpers run in the background.

##### `power_off`: Shut down, restart or log out of the computer.
- **Safety:** asks first
- **What it understands:** `action`: shutdown, restart or logout.
- **Say:** “shut down the laptop” · “restart the laptop” · “log out”
- **Tip:** Always asks yes / no first.

##### `read_text`: Read the text in a picture (OCR, handwriting too): what is on the screen in the window the user looks at, a part they drag a box around, a copied image or an image file. The text is copied to the clipboard.
- **Safety:** runs at once
- **What it understands:** `source`: window (the photo/page on the screen the user is looking at), area (the user drags a box around the part to read), screen (all of it), clipboard (a copied image) or file (an image file).
  - `path`: the image file for source=file ('latest' = the newest picture in Downloads/Pictures).
- **Say:** “read the text on the screen” · “what is written here” · “read the text in this picture”
- **Tip:** OCR, handwriting too.

##### `remote_desktop`: Remote desktop (RustDesk): the password is only given on Telegram after the PIN (this says how). stop=true turns it off (the password stops working at once).
- **Safety:** runs at once
- **Say:** `/control (on Telegram)` · “turn off remote desktop” · `/changepass (on Telegram)`
- **Tip:** Gives a RustDesk password for 15 minutes, only on Telegram after your PIN.

##### `scan_qr`: Scan a QR code or barcode on the screen (or a dragged area, a copied image, a picture): show + copy its link/text; Wi-Fi codes copy the password; can open the link or join the Wi-Fi.
- **Safety:** runs at once
- **What it understands:** `source`: screen (whole screen), area (the user drags a box), clipboard (a copied image) or file.
  - `path`: the picture for source=file ('this' = the newest picture).
  - `open_link`: open the link in the browser.
  - `connect`: join the Wi-Fi network of a Wi-Fi QR code.
- **Say:** “scan the qr code” · “scan the qr code on the screen”

##### `screenshot`: Take a screenshot (full screen, active window, or a selected area); returns the file path.
- **Safety:** runs at once
- **What it understands:** `mode`: full (whole screen), window (active window) or area (user drags a rectangle).
- **Say:** “take a screenshot” · “screenshot this window” · `/screenshot`
- **Tip:** Saved to the Workspace.

##### `set_theme`: Light/dark mode: switch, toggle or check it.
- **Safety:** runs at once
- **What it understands:** `mode`: light, dark, toggle, or status (report the current mode).
- **Say:** “dark mode” · “light mode” · `/dark`

##### `set_wallpaper`: Change the desktop wallpaper (an image path or name, next, random) or tell the current one.
- **Safety:** runs at once
- **What it understands:** `image`: Image path (~ allowed) or part of a file name in the wallpaper folders.
  - `mode`: set (use image), next, random, or current (just report it).
- **Say:** “set this picture as my wallpaper” · “change my wallpaper to mountains”

##### `share_wifi`: Share the current Wi-Fi: show a QR code on the laptop screen that a phone can scan to join (the password stays on the laptop).
- **Safety:** runs at once
- **Say:** “share wifi” · “show the wifi qr code”
- **Tip:** A QR code your phone can scan to join the Wi-Fi.

##### `status_now`: Current status of everything: training runs (epoch x/N, accuracy, loss, ETA), background jobs, downloads, lecture recording, page watches, guard, next reminder/class, laptop, recent alerts.
- **Safety:** runs at once
- **Say:** “status” · “what's going on right now” · `/status`

##### `suspend_computer`: Put the computer to sleep (suspend).
- **Safety:** asks first
- **Say:** “suspend the laptop” · “put the laptop to sleep”
- **Tip:** 'sleep now' alone puts KURAMA to sleep, never the laptop.

##### `token_usage`: Report LLM token usage, budget, fast-path savings, speech seconds and API cost.
- **Safety:** runs at once
- **What it understands:** `period`: "today", "week" (last 7 days) or "month".
- **Say:** “token usage” · “how many tokens did I use today” · `/tokens`

##### `window`: Windows: list the open ones, switch to an app's window, or snap left/right, maximize, minimize, restore.
- **Safety:** runs at once
- **What it understands:** `action`: list, focus (switch to `name`), or a position for the active window / `name`'s window.
  - `name`: The app or window title (empty = the active window for positions).
- **Say:** “snap this window left” · “maximize this window” · “switch to Brave” · “list my windows”

#### Files & folders (14)

Find, open, make, move, lock, clean up, back up.

##### `add_watchdog_target`: Add a dev server for the crash watchdog to keep running and restart if it crashes.
- **Safety:** asks first
- **What it understands:** `name`: Short id, e.g. "n8n".
  - `command`: Command to run, e.g. "n8n start" (allowlisted binaries only; no sudo, pipes or &&).
  - `cwd`: Working directory (default: home).
  - `match`: Optional text to recognise an already-running instance in the process list.
- **Say:** “keep my dev server alive” · “restart my flask server if it crashes”

##### `backup`: Backups: set which folders go to which drive/folder, run a backup now (verified), or status. Runs weekly and when the backup drive is plugged in.
- **Safety:** runs at once
- **What it understands:** `action`: status, setup (`folders` -> `target`), run now, or drives (plugged-in drives you could use).
  - `folders`: Folders to back up, comma separated (loose names work, e.g. "kurama, tara").
  - `target`: Where to (e.g. /media/leo/MyPassport/backup).
- **Say:** “back up my documents” · “backup now” · “when was the last backup”

##### `copy_path`: Copy a file or folder.
- **Safety:** asks first
- **What it understands:** `source`: Existing file or folder.
  - `destination`: New path, or an existing folder to copy it into.
- **Say:** “copy this file to the USB” · “copy notes.txt to Desktop”

##### `delete_to_trash`: Move a file or folder to the trash (can be restored).
- **Safety:** asks first
- **What it understands:** `path`: File or folder to delete.
- **Say:** “delete this file” · “delete old.zip”
- **Tip:** Goes to the Trash (you can restore it). Asks first.

##### `download_file`: Download manager: download a file (dataset, model, ISO) now or tonight, resumes after a broken connection, retries, and says when it's done; or list downloads.
- **Safety:** runs at once
- **What it understands:** `action`: add = queue `url`; list = downloads and their progress.
  - `url`: The http(s) link.
  - `folder`: Where to save it (default ~/Downloads; loose names work).
  - `when`: now, or tonight (after 1 AM, when the network is free).
- **Say:** “download this file” · “download https://example.com/file.zip”

##### `find_files`: Find files or folders by name, or text inside files, anywhere on this laptop (home + all disks).
- **Safety:** runs at once
- **What it understands:** `query`: File/folder name, part of it or a glob (*.py) for name/folder; text to look for when kind=content.
  - `path`: Folder to search; loose names work ("project1 then tara"). Empty = whole laptop.
  - `kind`: any (files AND folders, the default), name (files), folder, or content (text inside files).
  - `limit`: Max results (max 50).
- **Say:** “find my resume pdf” · “find report in Documents” · “where is train.py”
- **Tip:** Searches the whole laptop, typos OK.

##### `folder_lock`: Lock a folder or file with a password (encrypted into one file, original removed) or unlock it. The password is typed into a box on the laptop, never in chat.
- **Safety:** asks first
- **What it understands:** `action`: lock or unlock.
  - `path`: The folder/file (a path, a name, or 'this' for the current one); for unlock, the locked one's name.
- **Say:** “lock this folder with a password” · “unlock the secret folder”
- **Tip:** The password is typed in a popup, never in chat.

##### `list_folder`: List the files and folders inside one or more folders (numbered, so the user can pick one to open or send).
- **Safety:** runs at once
- **What it understands:** `path`: The folder(s); loose names work ("downloads", "project1 and tara", "Disk_D My Future", "music, videos").
  - `pattern`: Optional part of the name or extension to keep (".pdf", "report").
  - `hidden`: Include hidden files (names starting with a dot).
- **Say:** “what's in my Downloads” · “show this folder”

##### `make_folder`: Create a folder (and missing parent folders).
- **Safety:** runs at once
- **What it understands:** `path`: Folder path (absolute, ~/..., or relative to home).
- **Say:** “make a folder called notes here” · “create a folder Projects in Documents”

##### `move_path`: Move or rename a file or folder.
- **Safety:** asks first
- **What it understands:** `source`: Existing file or folder.
  - `destination`: New path, or an existing folder to move it into.
- **Say:** “move it to Documents” · “move report.pdf to Desktop”

##### `open_folder`: Open a folder in the file manager by name (fuzzy match anywhere on the laptop): 'open project1 in files', 'open my college project folder'.
- **Safety:** runs at once
- **What it understands:** `name`: The folder's name or part of it ("project1", "college project", "Tara/TARA"). Loose names work.
- **Say:** “open the Downloads folder” · “open this folder”
- **Tip:** 'this / here' = the folder you used last.

##### `tidy_downloads`: Tidy the Downloads folder: preview or sort files into Documents/Images/Videos/Audio/Archives/Code/Data/Installers (screenshots apart, exact duplicates to Trash); auto_on sorts daily.
- **Safety:** runs at once
- **What it understands:** `action`: preview = what would move; run = do it (asks); auto_on / auto_off = sort by itself once a day.
- **Say:** “clean my downloads” · “tidy the downloads folder”

##### `watchdog_status`: Show crash-watchdog targets, their state and restarts.
- **Safety:** runs at once
- **Say:** “what is the watchdog watching” · “watchdog status”

##### `write_file`: Create or write a text file with the given content (makes missing folders).
- **Safety:** runs at once
- **What it understands:** `path`: File path (absolute, ~/..., or relative to home).
  - `content`: Text to write.
  - `overwrite`: Replace the file if it already exists.
- **Say:** “write hello world to notes.txt” · “save this text as todo.md”

#### Phone & Telegram (5)

Things that go to (or come from) your phone.

##### `mute_alerts`: Mute KURAMA alerts for a while (laptop + Telegram): what = resource (RAM), location, jobs, all... or last (the alert just sent). off = unmute, status = what is muted.
- **Safety:** runs at once
- **What it understands:** `action`: on = mute, off = unmute, status = list current mutes.
  - `what`: resource, location, jobs, downloads, watchdog, web, commands, digest, backup, internet, guard, reminders, all, or last (whatever alert was sent most recently).
  - `minutes`: how long (default 30, at most 24 h: never forever).
- **Say:** “mute RAM alerts for 20 minutes” · “unmute alerts” · “which alerts are muted” · `/mute ram 20` · `/notifications`
- **Tip:** On Telegram you can also reply 'stop' to an alert.

##### `send_file_telegram`: Send a file from this laptop to the user's Telegram: a full path, or a file NAME to find anywhere (all disks; several matches give a numbered list), or pick N / all from the last list.
- **Safety:** runs at once
- **What it understands:** `path`: File path, or just a file name / words from it to find it first.
  - `caption`: Optional short caption.
  - `pick`: Send item N of the last numbered list (-1 = all of them).
- **Say:** “send this file to Telegram” · “send report.pdf to my phone”

##### `send_last_result`: Send the latest thing you made (picture, document or full list) to the user's Telegram.
- **Safety:** runs at once
- **What it understands:** `kind`: image (a generated picture), document (poem/essay/code), list (the full result of the last search), any (whatever was made last).
- **Say:** “send the last result to my phone” · “send that image to Telegram”

##### `send_message_telegram`: Send a text message to the user's Telegram.
- **Safety:** runs at once
- **What it understands:** `text`: The full text to send.
- **Say:** “send me a message on Telegram: buy milk” · “text my phone the wifi password”

##### `wifi_share`: Send a file or folder to the phone over Wi-Fi (not Telegram): makes a private link + QR code on the same network, any size, full speed; or stop sharing.
- **Safety:** runs at once
- **What it understands:** `action`: share (start) or stop.
  - `path`: The file/folder: a path, a name to find, or 'this' for the one just mentioned.
- **Say:** “share this file over wifi” · “share the Downloads folder to my phone”
- **Tip:** A link + QR for your phone on the same Wi-Fi.

#### Web, links & reading (9)

Live answers, search, web pages, saved links, read-later.

##### `live_search`: REAL-TIME info: live/latest match scores, results with scorers and next fixtures for any team; latest news on a topic; or an up-to-date answer to a current-events question (who won, what happened today). Prefer this over web_search for anything recent.
- **Safety:** runs at once
- **What it understands:** `query`: The question or topic, e.g. "Inter Miami result today", "news about Nepal".
  - `kind`: auto (decide), sports (a team's live/last/next game), news (headlines), answer (fresh short answer).
- **Say:** “latest news about Nepal” · “gold price today” · “dollar rate” · “football scores” · “top 10 Ballon d'Or 2026” · `/news cricket`
- **Tip:** Fresh facts from the web; long lists go to the Workspace.

##### `open_url`: Open a website in the browser: a URL, a domain or ANY site name (unknown names are found automatically).
- **Safety:** runs at once
- **What it understands:** `target`: A URL, a domain (example.com) or just the site's name as the user said it (e.g. sofascore).
- **Say:** “open youtube” · “open my facebook link” · “open github.com”
- **Tip:** Your saved links win over normal websites.

##### `page_summary`: What the web page open in the browser RIGHT NOW is about (short overview, then offers a detailed one in the workspace). Never pass an older link: it reads the current tab.
- **Safety:** runs at once
- **What it understands:** `action`: summary (2-3 sentences + offer), detail (the detailed overview to the workspace), cancel.
- **Say:** “what is this page about” · “summarize this page” · `/page`
- **Tip:** Reads the tab open in your browser; 'yes' = a detailed overview.

##### `read_later`: My list (to-dos + read later, Excel): add the highlighted link/open page or a to-do, optional tag and time (reminds 10 min before + at the time), list, done N (removes it), open N.
- **Safety:** runs at once
- **What it understands:** `action`: add (the highlighted link / the page open in the browser), todo (add the task in text), list, last (the newest saved link), open (link n), done (item n finished: removed), remove (item n, or the item named in text), clear (every to-do + reminder; text 'read' = the reading list), today (to-do + classes + long tasks), reschedule (item named in text -> new time in when), rename (text 'old » new').
  - `url`: ONLY a link the user literally gave in their message; never invent one (empty = the open page).
  - `n`: the item number from the list.
  - `text`: the to-do task (action todo); for list: 'todo' or 'read' shows only that part.
  - `tag`: optional tag, e.g. work, study, shopping.
  - `when`: optional time, e.g. 'in 2 hours', 'at 2 pm', 'tomorrow 2 pm', 'November 28 5 pm'.
- **Say:** “add buy milk to my to-do list” · “save this to read later at 9 pm” · “show my list” · “what's on today” · “done 2” · “remove the second task” · `/todo`
- **Tip:** To-do + reminders + read-later in one list (read_later.xlsx).

##### `read_webpage`: Read a web page (URL) and return its main text, e.g. to summarize an article.
- **Safety:** runs at once
- **What it understands:** `url`: Full page address, e.g. "https://example.com/article".
  - `max_chars`: Maximum characters of text to return (200-3000).
- **Say:** “read https://example.com/article” · “summarize this link”

##### `saved_links`: Saved links by name (Excel): save the highlighted link / open page under a name, give or open a saved link by name, list, rename, delete.
- **Safety:** runs at once
- **What it understands:** `action`: save (the highlighted link or the page open in the browser), name (the name for the link just found), cancel, get (the link, copied), open, list, rename, delete.
  - `name`: the link's name, e.g. 'Facebook', 'Claude Code'.
  - `url`: ONLY a link the user literally gave; never invent one (empty = highlighted link / open page).
  - `new_name`: rename only.
- **Say:** “save this link as facebook” · “give me my claude code link” · “show my saved links” · “delete the x link”
- **Tip:** links.xlsx.

##### `web_search`: Search the web for general info, people or facts: top results with title, URL and snippet. NOT for scores, prices, rates or today's news (use live_search).
- **Safety:** runs at once
- **What it understands:** `query`: What to search for, e.g. "CarryMinati latest video".
  - `k`: Number of results (1-8).
- **Say:** “search the web for python asyncio” · `/search best laptop under 1 lakh`

##### `web_watch`: Website watcher: message the user when a page changes (results, notices, releases, prices). add a URL (optionally only lines with a word like 'result'), list, stop, or check now.
- **Safety:** runs at once
- **What it understands:** `action`: add = start watching `url`; list = all watches; stop = stop the watch `url` (number, name or 'all'); check = look at all of them now.
  - `url`: The page (https://...) or, for stop, the watch's number/name.
  - `word`: Only lines containing this word count (e.g. "result", "BSc 2nd year", "v2.").
  - `every_minutes`: How often to look (default 60, at least 10).
- **Say:** “tell me when this website changes” · “watch the exam results page”

##### `wikipedia`: Wikipedia summary of a person, place or topic (fuzzy names ok); lang en, ne or hi.
- **Safety:** runs at once
- **What it understands:** `topic`: Person, place or thing, e.g. "CarryMinati" or "Kathmandu".
  - `lang`: Wikipedia language code: en, ne (Nepali) or hi (Hindi).
- **Say:** “wikipedia Mount Everest” · `/wiki Buddha`

#### Text & clipboard (2)

Help with any text you highlight or copy.

##### `clipboard`: Clipboard: read what is on it, copy text to it, or the copy history of the last 24 h (search by words or 'N minutes ago', copy item N back, clear).
- **Safety:** runs at once
- **What it understands:** `action`: read = what is on the clipboard now, write = copy `text` to it, history = recent copies.
  - `text`: The text to copy (action=write).
  - `max_chars`: Read at most this many characters (0 = default).
  - `limit`: How many history items to list.
  - `restore`: Copy history item N back to the clipboard (action=history).
  - `query`: History: only copies containing these words.
  - `minutes_ago`: History: what was copied about this many minutes ago.
- **Say:** “what did I copy 10 minutes ago” · “show my clipboard history” · “copy back the second one” · `/clip`

##### `text_assist`: Work on the text/code the user highlighted in any app: explain it, a word's meaning, translate (any language), improve/fix/optimize it in place, explain code, reply to a selected/copied chat; or write new code at the cursor in VS Code; or explain a whole file.
- **Safety:** runs at once
- **What it understands:** `action`: explain (what it means), meaning (word -> meaning), translate, improve (rewrite/fix in place: grammar, formal, shorter, optimize/fix/format code), code (explain highlighted code), write (new code at the cursor; request says what), explain_file (path), apply_code / cancel_code (the user said yes / no to an improved code waiting in the workspace), reply (the user's next message in the selected/copied chat; request = what they want to say), summary (the main points of the highlighted text), ask (anything else about the highlighted code/text, e.g. pytest tests for it; request = the user's words), use (a small run block to use/run the highlighted code, added to the file), complete (finish unfinished code; asks first when unclear, then waits for yes).
  - `request`: The user's words / instruction (e.g. "make it formal", "optimize this", "a calculator class").
  - `lang`: Answer/translation language code (ne, hi, en, ja, fr...); empty = from the request.
  - `replace`: translate only: put the translation in place of the selection.
  - `path`: explain_file only: the file (name, path, or 'this' = the file open in VS Code).
  - `text`: Explain/meaning/translate this typed text instead of the highlighted one.
- **Say:** “explain this” · “meaning of this word” · “translate this to Nepali” · “summary of this paragraph” · “improve this text” · “explain this code” · “fix this code” · “give me code to test this function” · “how can I use this function” · “what should I reply to my friend” · “write a csv reader here”
- **Tip:** Highlight first. Changes to your files are shown first and done only after 'yes'.

#### Coding (19)

Help inside VS Code and around your projects.

##### `code_nav`: Highlighted code: find = open where a function/class is defined (project or library) in VS Code; help = its real arguments/docs and whether the call is right; run = run it and show the output.
- **Safety:** runs at once
- **What it understands:** `action`: find (go to where it is defined), help (arguments, docs, is my call correct, suggestions) or run (run the highlighted code in a temp folder and show what it prints).
  - `name`: the function/class name or call; empty = the text highlighted in VS Code.
  - `request`: the user's question (for help: 'is this correct', 'suggest a better way'...).
- **Say:** “find this function” · “go to definition” · “help me with this library” · “is this correct syntax” · “what arguments does this take” · “run this code” · `/def` · `/args` · `/run`
- **Tip:** Highlight in VS Code. find = opens the real code; help = real arguments + typo check; run = output (then 'fix it').

##### `code_tidy`: Format a code file (ruff format / pretty JSON), check it for problems (ruff check) or fix the safe ones. 0 tokens. Default file: the one open in VS Code.
- **Safety:** runs at once
- **What it understands:** `action`: format (rewrite the layout), check (list problems with line numbers) or fix (apply ruff's safe fixes).
  - `path`: the file; empty = the file open in VS Code.
- **Say:** “format this file” · “check this file” · “fix the problems” · `/format` · `/check`
- **Tip:** ruff; backups kept.

##### `command_alerts`: Long-command alerts: when a terminal command runs longer than N minutes, say when it finishes (done/failed, time taken; on the phone when the screen is locked). on, off or status.
- **Safety:** runs at once
- **What it understands:** `action`: on = install the small bash hook, off = remove it, status = is it on + the last commands.
  - `minutes`: Only commands longer than this (default 2).
- **Say:** “turn on command alerts” · “tell me when long terminal commands finish”

##### `decode_text`: Decode or prettify the highlighted text, 0 tokens: JSON, JWT, base64, URL encoding, Unix timestamp, HTML entities, unicode escapes, XML, hex; or encode to base64 / URL.
- **Safety:** runs at once
- **What it understands:** `mode`: auto (detect), a specific format, or encode_base64 / encode_url.
  - `text`: the text; empty = the highlighted text.
- **Say:** “decode this” · “pretty print this json” · “decode this base64” · “what time is this timestamp”

##### `dependency_doctor`: Check a Python project's dependencies: unpinned, duplicate, missing, unused, outdated, vulnerable, torch/GPU baggage.
- **Safety:** runs at once
- **What it understands:** `repo`: Project folder (default: current folder).
  - `check_outdated`: Ask pip which packages are outdated (needs network, ~25 s max).
- **Say:** “check my dependencies” · “are my requirements pinned” · “any outdated packages”

##### `fix_error`: Explain an error or traceback (pasted text, or the clipboard if none) with cause + fix, remembering it; 'fixed' saves how the user fixed the last error; 'list' shows errors seen before.
- **Safety:** runs at once
- **What it understands:** `action`: explain = what the error means and how to fix it; fixed = remember `text` as the user's fix for the last error; list = recent errors and their fixes.
  - `text`: The error/traceback (explain; empty = read the clipboard) or how the user fixed it (fixed).
- **Say:** “what does this error mean” · “fix this error”
- **Tip:** Copy or highlight the error first.

##### `generate_requirements`: Generate requirements.generated.txt from a project's imports, pinned to installed versions.
- **Safety:** runs at once
- **What it understands:** `path`: Project folder (default: current folder).
  - `output`: File name to write inside the project (default requirements.generated.txt).
- **Say:** “make requirements.txt from imports”

##### `git_change`: Git changes: commit staged work (auto message if none), or create / switch a branch. Never pushes.
- **Safety:** asks first
- **What it understands:** `action`: commit, new_branch (create + switch) or switch_branch.
  - `repo`: The repo folder.
  - `message`: Commit message (empty = written automatically).
  - `add_all`: Stage every change before committing.
  - `branch`: Branch name for new_branch / switch_branch.
- **Say:** “commit my changes” · “make a new branch called login” · “switch to main”
- **Tip:** Asks first.

##### `git_info`: Git (read-only): status (branch, changed files), log (last N commits) or diff (what changed).
- **Safety:** runs at once
- **What it understands:** `action`: status, log or diff.
  - `repo`: The repo folder (loose names work, e.g. "kurama").
  - `n`: How many commits for action=log.
- **Say:** “git status” · “show the git log” · “what changed in my code” · `/git`

##### `kaggle_train`: Train on Kaggle's free GPU: send a .py/.ipynb or project folder, watch it, download the results when done (desktop + Telegram alert); or show the runs' status; or set up the Kaggle tool.
- **Safety:** runs at once
- **What it understands:** `action`: run (send path), status (recent runs), setup (install the Kaggle tool once).
  - `path`: The script, notebook or project folder (loose names / 'this' work).
  - `gpu`: Use a GPU (True) or CPU only.
- **Say:** “train this on Kaggle” · “run the notebook on a free GPU”
- **Tip:** Needs ~/.kaggle/kaggle.json once.

##### `notebook_to_script`: Convert a Jupyter notebook (.ipynb) to a .py script next to it; optional main() wrapper.
- **Safety:** runs at once
- **What it understands:** `path`: The .ipynb file.
  - `wrap_main`: Put the code inside a main() function with a __main__ guard.
  - `output`: Output .py path (default: same name next to the notebook).
- **Say:** “turn this notebook into a script” · “convert train.ipynb to python”

##### `python_env`: Python environment: check it (python/venv/pip, disk, RAM, tools), or install a missing module / package into the right project venv (from a ModuleNotFoundError or a name; asks first).
- **Safety:** runs at once
- **What it understands:** `action`: check = environment report; install = pip install `package` into `folder`'s venv.
  - `package`: A package name, an import name (cv2, sklearn) or the error text ("No module named 'timm'").
  - `folder`: The project folder (loose names work); its venv/.venv/env is used.
- **Say:** “create a venv” · “install pandas in this project” · “which python is this project using”

##### `review_code`: AI code review of the staged diff, a file or the last commit; returns up to 8 findings with file:line.
- **Safety:** runs at once
- **What it understands:** `target`: "staged" (default; falls back to unstaged), "last_commit", "commit:<sha>" or "file".
  - `repo`: Repository folder (default: current folder).
  - `path`: File to review when target is "file" (or any file path given as target).
- **Say:** “review my code changes” · “review the last commit”

##### `run_tests`: Run pytest on a project/file; returns pass/fail counts and the first failure.
- **Safety:** runs at once
- **What it understands:** `path`: Project folder or test file (default: current folder).
  - `pattern`: Only tests matching this -k expression.
  - `timeout`: Seconds; above 30 the suite runs as a background job.
- **Say:** “run the tests” · “run the tests in this project”

##### `run_training`: Start a training command in the background (e.g. 'python train.py --epochs 10') and guard it: progress, crash (+ cause), NaN, out of memory, stuck, finished; optional auto-restart.
- **Safety:** asks first
- **What it understands:** `command`: The command, e.g. "python train.py --epochs 10" (python/torchrun/accelerate/papermill...).
  - `folder`: The project folder to run it in (loose names work, e.g. "my_project").
  - `label`: Optional short name for the alerts.
  - `retries`: Restart it this many times if it crashes (0-5).
- **Say:** “train this model in the background” · “run train.py and tell me when done”

##### `scaffold_project`: Scaffold a new Python project (python-cli, fastapi, langgraph-agent or data-science).
- **Safety:** asks first
- **What it understands:** `name`: Project folder name.
  - `kind`: python-cli, fastapi, langgraph-agent or data-science.
  - `path`: Parent folder (default ~/projects).
  - `create_venv`: Also create a venv inside it.
- **Say:** “create a new flask project called shop” · “start a python project”

##### `time_machine`: Code time machine (automatic snapshots, even uncommitted): what changed since a time ('2 hours ago', 'yesterday'), history of a file, restore a file as it was then, undo a restore, protect a project, snapshot now.
- **Safety:** runs at once
- **What it understands:** `action`: changes = diff since `when`; history = snapshots (of `file`); restore = put `file` back as it was at `when` (asks first); undo = undo the last restore; protect = start snapshotting `project`; snapshot = save one now; list = watched projects; pin = always show `project` on the Coding card; unpin = automatic again; forget = stop watching `project` (code untouched); watch = watch it again.
  - `project`: Project folder (loose names work); empty = the one you changed most recently.
  - `when`: A time like "2 hours ago", "yesterday 18:00", "this morning", or a snapshot id.
  - `file`: A file inside the project, e.g. "train.py" or "src/model.py".
- **Say:** “watch the project at ~/code/app” · “watch this project” · “list my coding projects” · “stop watching” · `/projects`
- **Tip:** Snapshots of only the projects you choose.

##### `training`: Training Guard: how training is going (status: epochs, accuracy, ETA), watch a run/process/log, link a Google Colab notebook (colab), stop a training run (stop = after this epoch, stop_now = at once; local or Colab, asks first), or stop watching.
- **Safety:** runs at once
- **What it understands:** `action`: status = progress of every run; watch = start watching `target`; colab = get the notebook cell that makes a Colab run report here; stop = stop a training run after the current epoch (Colab) / now (local); stop_now = interrupt it at once; stop_watching = forget a watch.
  - `target`: For watch: a log file, a folder (its newest log), a PID or a process name (e.g. "train.py"). For stop_watching / kill: the run's number or name ("all" for every watch).
  - `label`: Optional short name for the alerts.
  - `patterns`: Optional regex to alert on in a log (default: errors, NaN, out of memory, finished).
- **Say:** “how's training” · “show the training progress”

##### `where_was_i`: Where was I? Resume a project after a break: what you were doing, unfinished changes, TODOs, the last error and training run, and the next step; can open it in VS Code.
- **Safety:** runs at once
- **What it understands:** `project`: The project (loose names work); empty = the one you changed most recently.
  - `open_editor`: Also open the project in VS Code.
- **Say:** “where was I” · “what was I working on” · `/code`

#### Create (images, charts, diagrams, audio, video, writing) (7)

Free generation; results land in the Workspace.

##### `generate_image`: Generate pictures from a text description (free; 1-4 versions, any size, or a change of the last picture); runs in the background, shows in the workspace.
- **Safety:** runs at once
- **What it understands:** `prompt`: What the picture should show, in English; include a style only if the user asked for one. With change_last: only the change ('at night', 'more colorful').
  - `set_as_wallpaper`: True when the user also wants it as the desktop wallpaper (done when the image is ready).
  - `send_to_telegram`: True when the user also wants the picture on Telegram/phone (sent when it's ready).
  - `width`: Pixels, 256 to 1920 (0 = from the words: phone wallpaper, square logo, thumbnail... or 1024x768).
  - `height`: Pixels, 256 to 1920.
  - `count`: How many different versions (1-4).
  - `change_last`: True for 'the same picture but ...' / 'another version' (uses the last picture's prompt).
  - `detailed`: True when the user wants more detail / a better picture (the service improves the prompt).
- **Say:** “generate an image of a red panda” · “make 4 versions of a fox” · “make a phone wallpaper of Everest” · “same picture but at night” · “an HD image of a castle” · `/image a dragon over Pokhara`
- **Tip:** Free (your Cloudflare workers, then Pollinations).

##### `jobs`: Background jobs: list them, show one's result, cancel one, or resume an interrupted writing job.
- **Safety:** runs at once
- **What it understands:** `action`: list = all jobs and progress, result = a job's output, cancel = stop one, resume = continue one.
  - `job`: The job's id or words from its title (cancel with no job = the latest running one).
- **Say:** “what jobs are running” · “cancel the job” · “show the result of job 12” · `/jobs`

##### `make_audio`: Turn text into an MP3 (spoken, English/Nepali/Hindi): the highlighted text, a txt/md/pdf file, a web page link, the newest workspace document ('last'), or given words. Background job.
- **Safety:** runs at once
- **What it understands:** `source`: 'selection', 'last' (newest workspace document), a URL, a file path, or 'text' (use `text`).
  - `text`: The words to speak when source is 'text'.
- **Say:** “make an audio of this” · “turn the last result into audio” · “make an mp3 of <link>” · “make an audio of notes.pdf” · `/audio`
- **Tip:** English / Nepali / Hindi voice.

##### `make_chart`: Draw charts (bar, line, pie; several views) from the user's spending, a CSV/Excel/JSON file or a link to data (e.g. a government data page). Shows in the workspace.
- **Safety:** runs at once
- **What it understands:** `source`: 'money' (my spending), a file path, or a URL; empty = money.
  - `request`: The user's words (which columns: 'population by district').
  - `kind`: auto (good views for the data), bar, line, pie, or all.
  - `period`: For money charts.
- **Say:** “chart my expenses” · “pie chart of my spending this week” · “make a chart from sales.csv” · “draw a graph of population by district from <link>” · `/chart`
- **Tip:** Several views (bar, line, pie).

##### `make_diagram`: Draw a diagram: project = from the project's README only (no README, no diagram), flow = a flowchart of the steps given, code = which function calls which in a Python file. 0 tokens.
- **Safety:** runs at once
- **What it understands:** `kind`: project, flow or code.
  - `target`: project: folder path or name (empty = the folder open in VS Code); flow: the steps in words; code: a .py file (empty = the file open in VS Code).
- **Say:** “make a diagram of this project” · “flowchart: wake up, brush, study” · “diagram of this code” · `/diagram` · `/flow a, b, c`
- **Tip:** Projects are drawn from their README only.

##### `make_video`: Make a short video (MP4): about a topic (AI writes 4-6 narrated scenes), from the user's own script, or a slideshow of the pictures in a folder. Background job, free.
- **Safety:** runs at once
- **What it understands:** `topic`: What the video is about (the AI writes the scenes; one small call).
  - `script`: The user's own narration (each sentence becomes a scene; no AI).
  - `folder`: A folder of pictures for a slideshow (no AI).
  - `vertical`: 720x1280 for reels/shorts; default 1280x720.
- **Say:** “make a short video about the Himalayas” · “make a reel about momo” · “create a video with this script: ...” · “make a slideshow from ~/Pictures/trip” · `/reel tea`
- **Tip:** Pictures + voice + captions, joined with ffmpeg.

##### `write_document`: Write a long essay/article/story/report or code file in the background; returns a job id at once.
- **Safety:** runs at once
- **What it understands:** `request`: The full writing request, including topic and length (e.g. "a 1000-word essay about Nepal").
- **Say:** “write a 1000-word essay about Nepal” · “write a report on climate change” · “write a python snake game”
- **Tip:** A background job; saved in the Workspace.

#### Music & video (5)

Music without the browser, YouTube, downloads, hand gestures.

##### `gesture_control`: Turn hand-gesture control of media/YouTube (camera) on or off, or check it.
- **Safety:** runs at once
- **What it understands:** `action`: on = start the camera gesture control, off = stop it, status = is it running.
- **Say:** “gesture control on” · “turn off gesture control”
- **Tip:** Control media with your hand in front of the camera.

##### `media_control`: Control music/video playback (play, pause, next, previous, stop, what's playing) or play one of the user's named playlists.
- **Safety:** runs at once
- **What it understands:** `action`: play_pause (toggle), play, pause, next, previous, stop, status, or playlist (play `name`).
  - `player`: Optional player name (spotify, firefox, vlc); empty = the active one.
  - `name`: The playlist's name (action=playlist; empty = list them).
- **Say:** “pause” · “play” · “next song” · “what song is this” · “pause the video” · “continue the video” · `/play` · `/pause` · `/next`
- **Tip:** Works for KURAMA's music and for videos in the browser.

##### `music`: Music without the browser (sound only): play a song/artist/mood, a YouTube link or playlist, a saved playlist, or the songs in ~/Music; save/list/delete playlists; pause, resume, next, previous, volume, what's playing, stop.
- **Safety:** runs at once
- **What it understands:** `action`: play (query = song/artist/mood), url (query = YouTube link; empty = the tab open in the browser), playlist (query = saved playlist name), local (query = folder, empty = ~/Music), save (query = name for the open/linked playlist), playlists (list them), delete (query = name), pause, resume, next, previous, volume_up / volume_down (query = step, default 15), volume_set (query = 0-130), status, stop.
  - `query`: See action.
  - `shuffle`: Play in random order.
- **Say:** “play lofi music” · “play kya mujhe pyar hai by KK” · “next” · “pause” · “music volume 80” · “play my study playlist” · “save this playlist as study” · “play my music” · “stop the music” · `/music`
- **Tip:** Sound only (no browser). The next song is loaded while one plays.

##### `video_download`: Download a YouTube/online video (link or search words) in a quality like 1080p/720p/4K with sound, a whole playlist, or just the audio as MP3; runs in the background and says when done.
- **Safety:** runs at once
- **What it understands:** `source`: The video/playlist link, or words to search YouTube for (empty = a link on the clipboard).
  - `quality`: 1080p, 720p, 4k, hd ... (empty = best available).
  - `audio`: True = MP3 audio only.
  - `playlist`: True = the whole playlist.
- **Say:** “download this video” · “download it in 720p” · “download this as mp3” · “download this playlist”

##### `youtube`: Play a YouTube video for a query, search YouTube, or pause/next/fullscreen the YouTube tab.
- **Safety:** runs at once
- **What it understands:** `query`: What to play or search (for play/search).
  - `action`: play (first video), search (results page), pause (toggle), next, or fullscreen.
- **Say:** “play despacito on youtube” · “search youtube for python tutorials” · `/yt lofi`
- **Tip:** Opens YouTube in Brave.

#### KURAMA itself (7)

About KURAMA, new tools, skills, reset.

##### `about_me`: Facts about yourself: overview, outputs (where files go), howto, limits; storage/architecture/security are password-protected.
- **Safety:** runs at once
- **What it understands:** `topic`: overview | outputs | howto | limits | storage | architecture | security.
- **Say:** “what can you do” · “how do you work” · “what are your limits”

##### `find_capability`: Find which of your tools can do a task or help with a problem; use it to guide a stuck user.
- **Safety:** runs at once
- **What it understands:** `need`: What the user wants to do, in a few words (e.g. "create a python project").
- **Say:** “do you have a tool to compress pdf” · “can you track my sleep”

##### `make_tool`: When no other tool can do a real task (calculation, conversion, data, a desktop setting), offer to build a small tool for it. It asks the user before making anything.
- **Safety:** runs at once
- **What it understands:** `task`: What the user wants done, in their words.
- **Say:** “make a tool that renames photos by date” · “create a tool to count words in a file”
- **Tip:** KURAMA writes a small tool and asks before running it.

##### `read_workspace`: Read what is in your Workspace (latest result first) to summarize it or answer from it.
- **Safety:** runs at once
- **What it understands:** `item`: 1 = the latest, 2 = the one before, ...

##### `reset_kurama`: Clear/reset KURAMA: 'chat' = forget this conversation; 'recent' = chat + reminders/alarms/timers + caches; 'all' = also wipe learned personal facts and start brand new. Password and settings are kept.
- **Safety:** runs at once
- **What it understands:** `level`: chat (this conversation), recent (chat + reminders + caches), all (full fresh start).
- **Say:** “reset KURAMA” · `/reset`
- **Tip:** Wipes what KURAMA knows (asks first; settings and password kept).

##### `set_my_name`: Change your own name when the user asks; you answer to it from now on.
- **Safety:** runs at once
- **What it understands:** `name`: The new name, one or two words.
- **Say:** “call me Leo” · “my name is Dhiru”

##### `skills`: Saved tools KURAMA built earlier: list them, run one by name, or delete one.
- **Safety:** runs at once
- **What it understands:** `action`: list = all saved tools, use = run `name` with `arg`, delete = remove `name` (asks first).
  - `name`: The saved tool's name.
  - `arg`: The input for the saved tool (action=use).
- **Say:** “show my skills” · “use the rename skill” · “delete the rename skill”
- **Tip:** Tools KURAMA made for you.

<!-- TOOLS:END -->
