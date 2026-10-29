# KURAMA: what it can do and how to use it

This is the one page to read when you forget something. It covers:

1. How to start KURAMA and how to talk to it
2. How it works inside, and how it saves tokens
3. How it keeps your tasks apart (to-do, long tasks, code work)
4. How it does many things at once
5. Every tool, with example sentences
6. Every `/command`
7. Ideas for using it every day
8. **All 131 tools in detail:** what each one does, whether it asks first, what it understands, and example sentences

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
   ├─ 1. /command?               -> run that tool directly            0 tokens
   ├─ 2. Fast path (rules)?      -> hundreds of known ways of saying   0 tokens
   │                                things: run the tool, answer
   │                                from a ready template
   ├─ 3. Router: which tools could help?
   │       a. keyword rules                                            0 tokens
   │       b. local "understanding model" (small, on the laptop)       0 tokens
   │       c. a tiny AI question "which group?" (only if still unclear) ~100 tokens
   │
   └─ 4. The AI agent, given ONLY 1–3 groups of tools (never all ~130) -> picks the tool, answers
```

Over half of all requests stop at step 1 or 2 and cost **0 tokens**. The dashboard's System card shows it as "FREE ANSWERS 55%".

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
| Your editable sheets | `~/Documents/KURAMA/` → `read_later.xlsx` (to-do + reminders + read later), `goals.xlsx` (long tasks), `expenses.xlsx`, `habits.xlsx`, `links.xlsx`, `contacts.xlsx` |
| Secrets (API keys) | `.env` only |

---

## 3. How it keeps your tasks apart

KURAMA has **three kinds of work** and never mixes them:

| Kind | Words that mean it | Examples |
|---|---|---|
| **To-do** (short tasks and reminders): the default | task, work, to-do, reminder | "add buy milk to my to-do", "remind me to call mom at 5", "schedule reading the book at 9 pm", "what's on today", "done 2", "remove the second task" |
| **Long tasks** (weeks or months: exams, projects) | long task, goal, monthly, countdown | "my exam is in 30 days, remind me every day", "show my long tasks", "how many days until the exam", "today I wrote chapter 2" |
| **Code work** | code words, "where was I" | "where was I", "watch the project at ~/code/app", "list my coding projects" |

- **To-do items with a time** get a heads-up 10 minutes before, and a "not done yet" nudge 1 hour later.
- **To-do items without a time** get at most 2 gentle nudges a day.
- **Long tasks** send countdowns and check-in questions, only between 05:00 and 22:00. Each long task has its own folder with a log, plus weekly and monthly reports.
- **Every alert** goes to the laptop AND Telegram.
  - Pause one kind: "mute RAM alerts for 20 minutes" or `/mute ram 20`.
  - The day summary arrives at 10 PM.
- **The Work card** on the dashboard shows long tasks and to-dos with ✓ / ✕ buttons.

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

KURAMA has **131 tools** in 34 groups. The AI only ever sees the 1–3 groups a request needs. This part is the quick overview; **part 8** at the end lists every tool one by one, in detail.

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
| Code quality | "review my code changes", "check my dependencies", "scan the repo for leaked keys" |
| Dev helpers | "run the tests", "create a venv", "make requirements.txt from imports", "turn this notebook into a script", "decode this" (JSON, base64, JWT...) |
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

## 7. Ideas for every day

| When | Try |
|---|---|
| Morning | Unlock the laptop and listen to the brief. "what's on today" |
| Studying | "start focus mode 50", "play focus music", highlight a hard paragraph → "explain this", "note for DSA: …", evening: "start a quiz on DSA" |
| Coding | highlight → "find this function" / "is this correct syntax" / "run this code"; "what is running on port 8000"; end of day: "where was I" |
| Spending | right after paying: "spent 150 on momo and 40 on tea"; weekly: "spending breakdown this week"; month end: "chart my expenses" |
| Habits | "add a habit: …" once, then just "did exercise" |
| Away from the laptop | on Telegram: `/status`, `/where`, `/camera`, `/control`, or "send me the report" |
| Making things | "make a reel about …", "make 4 versions of …", "make an audio of this" for revision on the go |

**When KURAMA gets something wrong:** paste the chat log to Claude Code. Each line shows the route, tokens and time, so the exact cause can be found and fixed.

---

<!-- TOOLS:START -->

## 8. Every tool in detail (17 tools)

Generated from the tools themselves by `scripts/gen_tool_guide.py`.
- **Runs at once** means it just does it. **Asks first** means it waits for your yes.
- Under **What it understands** are the settings the AI fills in from your words. You never type them.
- The **Say** lines are examples. Your own words work too.

### Everyday (2)

Time, weather, reminders, maths, files to convert.

#### `info`: Quick facts: time (any place), date (also Nepali BS calendar), weather (any place, days ahead), calculate (math, %, units), contact (find a phone number), save_contact, phone_location, find_phone, laptop_location.
- **Safety:** runs at once
- **What it understands:** `action`: What to look up.
  - `query`: The place (time/weather), 'bs' for the Nepali date, the expression (calculate) or the person's name.
  - `value`: save_contact: the phone number.
  - `days`: weather: how many days ahead (1 = today).

#### `schedule`: Alerts in time: remind (a reminder at a time), alarm (rings), timer (countdown), stopwatch; list, cancel, move or rename one; run_later = KURAMA does a command later. Not for to-dos (use todo).
- **Safety:** runs at once
- **What it understands:** `action`: remind, alarm, timer, stopwatch, list, cancel, move, rename, run_later.
  - `text`: What to remind about / the alarm label / the new name / the command to run later.
  - `when`: The time ('at 5 pm', 'tomorrow 6 am', 'every day at 8') or, for timer, the length ('5 minutes').
  - `item`: Which reminder (id or words) for cancel/move/rename; stopwatch: start, stop, lap, reset, status.

### Money & habits (1)

Your spending and daily habits, kept in Excel sheets you can also edit.

#### `create`: Make something: image (picture; can also set it as wallpaper or send it to Telegram), document (essay, article, report: runs in the background), audio (speech from text or the selection), chart (e.g. of my spending), diagram, video.
- **Safety:** runs at once
- **What it understands:** `action`: image, document, audio, chart, diagram, video.
  - `what`: Description: the picture / the document request / the text to speak / the chart wanted.
  - `telegram`: image: also send it to Telegram when ready.
  - `wallpaper`: image: also set it as the wallpaper.

### Laptop control (5)

Volume, screen, apps, windows, power, health of the laptop.

#### `apps`: Open an app, website or folder by name; close or force-kill an app; arrange a window (minimize/maximize/left/right/focus); press keys, type or click in the app in front; install an app.
- **Safety:** runs at once
- **What it understands:** `action`: open, close, kill (force), window, press (keys like 'ctrl+v', 'enter'), type, click, install.
  - `target`: App / website / folder name ('brave', 'youtube', 'tara'), or several sites 'youtube, facebook'.
  - `how`: window: focus, minimize, maximize, left, right, restore, list; install: install, remove, search, update.
  - `text`: What to type, the keys to press, or what to click.

#### `kurama`: About KURAMA: about (what you are, where things are stored), can_you (is there a way to do X), rename, mode (power mode), jobs (background jobs), clear_chat, mute_alerts, remote (remote desktop on/off), make_tool (build a small new tool when nothing else fits).
- **Safety:** runs at once
- **What it understands:** `action`: What to do.
  - `text`: The topic / the need / the new name / the mode / list|result|cancel / minutes / stop / the task.

#### `laptop`: Laptop settings and health: volume, brightness, wifi, bluetooth, airplane, power mode, night light, theme, do-not-disturb, wallpaper, screenshot, screen off, battery, health (RAM/CPU/top apps), free RAM, internet check, clean disk, focus session, lock, sleep, shutdown, restart, log out.
- **Safety:** runs at once
- **What it understands:** `action`: What to change or check.
  - `value`: volume/brightness: up, down, +10, 40, mute, get; wifi/bluetooth/airplane/night_light/dnd: on, off, status; power_mode: saver, balanced, performance; theme: light, dark; wallpaper: next, random or an image path; screenshot: full, window, area; internet: check, speed, fix_dns; clean_disk: scan, clean; focus: minutes.

#### `life`: Personal trackers: spent (log spending), money (report), budget, habit (new), habit_done, habits, goals (long tasks), add_goal, timetable (classes), notes (study notes), quiz, lecture (record), day_summary (what we did today), tokens (AI usage).
- **Safety:** runs at once
- **What it understands:** `action`: What to do.
  - `text`: What was spent ('500 on food'), the habit, the goal, the note, the quiz subject, or 'stop' (lecture).
  - `period`: money/tokens: today, week, month; timetable: today, tomorrow, week, next; add_goal: when it ends.

#### `text`: The selected text / screen: explain, meaning, translate, improve (fix wording), summary, reply, code (write code for it); read_screen (OCR); clipboard (what was copied, history); copy; dictate (start/stop typing by voice); qr (scan a QR code).
- **Safety:** runs at once
- **What it understands:** `action`: What to do.
  - `request`: Extra wish ('make it formal', 'in 3 lines'), the clipboard search, the text to copy, or 'stop' (dictate).
  - `lang`: translate: target language (ne, hi, en...).

### Files & folders (1)

Find, open, make, move, lock, clean up, back up.

#### `files`: Files and folders anywhere on the laptop: list a folder, find files by name, read, write, make a folder, move, copy, delete (to trash, asks first), organize a messy folder, convert a file, lock a folder.
- **Safety:** runs at once
- **What it understands:** `action`: list, find, read, write, mkdir, move, copy, delete, organize, convert, lock.
  - `path`: The file or folder; loose names work ('downloads', 'project1 then tara').
  - `query`: For find: the file name or part of it ('main.py', 'naruto'), searched on all disks.
  - `to`: Destination folder (move/copy) or format (convert: pdf, md, mp3...).
  - `text`: write: the content; find: name/folder/content; organize: organize/apply/undo; lock: lock/unlock.

### Phone & Telegram (1)

Things that go to (or come from) your phone.

#### `telegram`: Send to the user's Telegram: a text message, a file (give a path or just its name: it is found on the laptop), or the latest thing made (picture, document, list).
- **Safety:** runs at once
- **What it understands:** `action`: message, file, latest.
  - `text`: The message (or a caption for a file).
  - `file`: A path or a file name ('naruto.jpg', 'tools.py'); a folder is sent as a zip.
  - `kind`: latest: image, document, list or any.

### Web, links & reading (1)

Live answers, search, web pages, saved links, read-later.

#### `web`: Internet answers: live (match results, news, scores, prices, anything recent), search, read a web page, this_page (the page open in the browser), wiki, watch a page for a word.
- **Safety:** runs at once
- **What it understands:** `action`: live, search, read, this_page, wiki, watch.
  - `query`: What to look up (or the word to watch for).
  - `url`: The page to read or watch.
  - `kind`: live: sports, news, answer or auto.

### Coding (1)

Help inside VS Code and around your projects.

#### `code`: Coding help: fix_error (explain an error/traceback), run_tests, where_was_i, changes (what changed lately), git (status/log/diff), commit, new_project, env (check / install a package), review, training (ML training / Colab status).
- **Safety:** runs at once
- **What it understands:** `action`: What to do.
  - `text`: The error text / commit message / project name / package to install / 'last hour' / git: status, log, diff.
  - `path`: The project folder or file (empty = the current project).

### Music & video (1)

Music without the browser, YouTube, downloads, hand gestures.

#### `media`: Music and video: play a song, artist or playlist (sound only), pause, resume, next, previous, stop, what's playing, play on YouTube, hand-gesture media control on/off, download a video.
- **Safety:** runs at once
- **What it understands:** `action`: play, pause, resume, next, previous, stop, playing, youtube, gesture, download.
  - `query`: Song / artist / playlist / video to play, a video link to download, or on/off for gesture.

### KURAMA itself (3)

About KURAMA, new tools, skills, reset.

#### `memory`: Memory: remember a fact, recall what you know about the user, forget, past_chat (what we talked about), save_link / get_link, read_later (save this link) / reading_list, ask_docs (the user's own notes and code), workspace (read a result).
- **Safety:** runs at once
- **What it understands:** `action`: What to do.
  - `text`: The fact / the search words / the link name / the question.
  - `url`: A link the user literally gave (never invent one).

#### `run_command`: Run one terminal command on the laptop (bash) and return its output; asks the user first, every time. Use for things no other tool does (file sizes, git, pip, system info...). Never sudo.
- **Safety:** asks first
- **What it understands:** `command`: The exact bash command, e.g. 'du -sh ~/Downloads' or 'ls -la'.
  - `folder`: Folder to run it in (default: home).

#### `run_python`: Run a short Python program on the laptop and return what it prints; asks the user first, every time. Use when no other tool fits (math on data, file work, quick scripts).
- **Safety:** asks first
- **What it understands:** `code`: The complete Python program; print() the result.
  - `folder`: Folder to run it in (default: home).

### Other

- `todo`: The user's to-do list (tasks to do, with optional due date, priority, tag): add, list, today, done, delete, edit, clear. A to-do does not ring; use 'remind' only if the user also wants an alert.

<!-- TOOLS:END -->
