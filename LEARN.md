# LEARN.md: how KURAMA works, and how to change it yourself

This guide is for you, the owner, who has used KURAMA every day but has not read its code. After reading it (with
the files open beside it) you should be able to:

- explain what happens between "you say something" and "KURAMA answers";
- find the file that does any one thing, and know what else it touches;
- debug a problem from evidence (traces and logs) instead of guessing;
- add or change a tool, a shortcut, a setting, or a piece of the UI;
- reuse the ideas in any big project of your own.

Read it in order the first time. Sections 2 and 3 are the most important: they are the "skeleton" every other file
hangs on. Later sections are reference: come back to them when you need them.

> Line counts and names below are from 2026-11-01. Files grow; if a name moved, `grep -n "def name" -r jarvis` finds
> it. Never trust a doc over the code: the code is the truth, this guide is the map.

---

## Contents

1. [What KURAMA is, in one page](#1-what-kurama-is-in-one-page)
2. [The life of one request (the most important section)](#2-the-life-of-one-request)
3. [The architecture: layers and why](#3-the-architecture-layers-and-why)
4. [The folder map](#4-the-folder-map)
5. [Every core file: what it does, what it needs, when to change it](#5-every-core-file)
6. [Tools: the two layers, the contract, how to add one](#6-tools)
7. [How KURAMA understands a request (routing in depth)](#7-how-kurama-understands-a-request)
8. [Memory, data and where everything is stored](#8-memory-data-and-storage)
9. [Voice, wake word, hold-to-talk, the desktop window](#9-voice-and-the-desktop)
10. [Background work: workers, jobs, the job list](#10-background-work)
11. [Technologies, and why each one was chosen](#11-technologies-and-why)
12. [Who depends on whom (the dependency map)](#12-the-dependency-map)
13. ["I want to change X": which file, which setting](#13-i-want-to-change-x)
14. [Debugging: your toolkit, step by step](#14-debugging)
15. [How to learn it: top-down, bottom-up, and exercises](#15-how-to-learn-it)
16. [Lessons for any big project](#16-lessons-for-any-big-project)
17. [Honest weak spots (technical debt)](#17-honest-weak-spots)
18. [Glossary](#18-glossary)

---

## 1. What KURAMA is, in one page

KURAMA is a personal assistant that runs all day on one laptop (Ubuntu, X11, 8 GB RAM, no GPU). You talk to it by
typing, by voice (wake word, talk mode, hold Alt), or from your phone through Telegram. It can do 130+ things:
open apps, control the laptop, manage files, reminders, to-dos, money, links, music, downloads, code help, web
answers, and more.

Three hard limits shaped every design decision. Remember them, because almost every "why is it done this way?"
comes back to one of these:

| Limit | What it forces |
|---|---|
| **Groq free tier**: about 8,000 tokens a minute per model, and a daily cap | Do as much as possible with **0 tokens** (shortcuts, templates, local code). Send the AI only the 3 tools it needs, never all 130. Keep the system prompt under 250 tokens. |
| **8 GB RAM**, shared with VS Code and Chrome, running all day | Load heavy things only when needed and free them when idle. One process instead of many. No PyTorch, no GPU libraries. |
| **It acts on your real laptop** | Every tool call passes a safety gate. Risky actions (delete, shutdown, commands) ask you first. Everything is logged. |

The code is Python 3.12 in the `jarvis/` package (the old name; the user-facing name is KURAMA and can be
changed). The UI is plain HTML/JS in `frontend/`. A small GTK program shows that UI as your desktop wallpaper and a
mini chat panel.

---

## 2. The life of one request

Follow one message, "save this website names whatsapp", from your keyboard to the answer. Every step names the file
and the function, so you can open it and read along.

### 2.1 The picture

```
 you type / speak / Telegram
            │
            ▼
 ┌──────────────────────┐   frontend/app.js  sendChat()  ──HTTP POST /api/v1/chat (Server-Sent Events)──┐
 │  UI (browser page)   │                                                                                 │
 └──────────────────────┘                                                                                 ▼
                                                          ┌───────────────────────────────────────────────────┐
                                                          │ API  jarvis/api/routes/chat.py  chat()             │
                                                          │      jarvis/api/turns.py  Engine.run_turn()        │
                                                          │      (talk-mode room-talk gate, dictation gate)    │
                                                          └───────────────────────┬───────────────────────────┘
                                                                                  ▼
                                                          ┌───────────────────────────────────────────────────┐
                                                          │ BRAIN  jarvis/core/agent.py  Agent.stream()        │
                                                          │  ① shortcut?  fastpath.try_answer()  → 0 tokens    │
                                                          │  ② bare yes/no?  _bare_answer()      → 0 tokens    │
                                                          │  ③ AI graph (LangGraph):                           │
                                                          │     plan → route → llm ⇄ tools → answer            │
                                                          └───────┬───────────────────────────┬───────────────┘
                                                                  │                           │
                                         ┌────────────────────────▼──────┐     ┌──────────────▼───────────────┐
                                         │ TOOLS  registry + safety      │     │ AI  jarvis/core/llm.py        │
                                         │  tools/core/* (17 general)    │     │  Groq through LangChain       │
                                         │  tools/general/* (130+ real)  │     │  retry, fallback, rate limit  │
                                         └────────────────┬──────────────┘     └──────────────────────────────┘
                                                          ▼
                                         your laptop: files, apps, xdotool, pactl, Excel sheets, SQLite...
            ▲
            │  events stream back: delta (text) · tool · confirm (yes/no card) · done
            └──────────────────────────────────────────────────────────────────────────────────────────────────
```

### 2.2 Step by step

**Step 1: the UI sends it.** `frontend/app.js`, function `sendChat()`, calls `api.chat()` in `frontend/api.js`. That is
a `POST /api/v1/chat` whose answer is a **stream** (Server-Sent Events): the reply arrives word by word, so you see and
hear it before the AI has finished.

**Step 2: the API receives it.** `jarvis/api/routes/chat.py` `chat()` validates the body (`ChatIn`: text, mode,
lang, ambient) and hands it to `jarvis/api/turns.py` `Engine.run_turn()`. That function:
- runs the blocking agent in its own thread and turns what it yields into events (`delta`, `tool`, `confirm`, `done`);
- drops talk-mode speech that isn't for KURAMA (`addressed()`: it names KURAMA, it is a shortcut, or by meaning it is
  a greeting or a clear request);
- parks the thread when a tool asks yes/no, until you click the card (`POST /api/v1/confirm`) or it times out.

**Step 3: the brain, path ① (shortcut).** `jarvis/core/agent.py` `Agent.stream()` first calls `_fast()`, which
calls `jarvis/core/fastpath.py` `try_answer()` → `match()`. `match()` tries, in order:
- slash commands (`/clear ram`, `/weather pokhara`; `jarvis/core/slash.py`);
- hundreds of regex patterns, one function per area (`links_intent`, `video_dl_intent`, `live_intent`...);
- "selection first" (something is highlighted → explain / translate / improve it, chosen by meaning);
- `meaning_intent()`: a small table of actions chosen **by meaning** (`config.MEANING_SHORTCUTS`): save or list links,
  copy this folder's path, open it in VS Code, start or list jobs, clean RAM / KURAMA / storage.

A pattern only runs if `meaning_ok()` agrees: its area must be close to the best area for the whole sentence. If
something matches, the tool runs at once and a template writes the answer. **0 tokens, ~100 ms.** About 2 of every 3
requests end here. "save this website names whatsapp" ends here: `meaning_intent()` masks unknown words as X
("save this website names X"), finds the action `save_link`, takes the left-over word "whatsapp" as the name, and
calls the `saved_links` tool, which reads the page open in your browser.

**Step 4: the brain, path ② (bare yes/no).** "yes" or "no" with nothing waiting for it gets a fixed answer
(`_bare_answer()`), instead of the AI guessing.

**Step 5: the brain, path ③ (the AI).** Anything else goes into the LangGraph graph built in `Agent._build()`:

```
START → plan ─┬─ one quick task ──→ route → llm ⇄ tools → END
              ├─ several tasks ───→ quick / long / chain  (run at the same time) → join → END
```

- **plan** (`_plan_node`, `jarvis/core/planner.py`): one task or several? "write an essay about Nepal and open
  YouTube" is two tasks; long ones become background jobs.
- **route** (`_route_node`, `jarvis/core/router.py` `route()`): picks at most 3 **areas** (tool groups) by meaning
  (`jarvis/core/semantic.py`), then turns them into at most 3 **general tools** (`registry.schemas_for()`). It also
  picks the model tier and builds the messages: a short system prompt, the last 6 turns, a rolling summary, and one
  line of context (what is open in VS Code, Files or the browser; `jarvis/core/context.py`).
- **llm** (`_llm_node`): calls Groq through `jarvis/core/llm.py` `chat()`, with only those tools bound. The model
  either answers in text or asks for a tool call. Safety nets live here:
  - a refusal, or "I did it" with no tool behind it, is retried once with the tools (`meta.needs_tool`);
  - a tool-less answer about your saved things (links, to-dos, reminders, jobs, money) is retried with the tools;
  - a junk stream ("… … …", invisible spaces) is held back and replaced by the tool's own result.
- **tools** (`_tools_node`): every call goes through `jarvis/core/safety.py` `execute()`: is it allowed, does it
  need your yes, log it. A general tool (`jarvis/tools/core/memory.py`, say) maps its `action` to the real tool
  (`saved_links`) through `jarvis/tools/core/_hub.py`. The result goes back to **llm**, which loops (at most 4 rounds)
  until it answers in text.

**Step 6: the answer streams back.** Text deltas flow: agent → `turns.py` → SSE → `app.js`, which draws the bubble
and, in voice mode, speaks sentence by sentence (`frontend/voice.js` → `POST /api/v1/tts` → edge-tts).

**Step 7: after the answer (nothing waits for this).**
- `jarvis/core/trace.py` writes one row to `data/traces.db`: text, path, route, tools, tokens, answer, time. This
  is your evidence when something goes wrong (section 14).
- `jarvis/core/learn.py` judges the **previous** turn: if your next message was a correction ("no, I meant..."), the
  earlier wording is learned as belonging to the right area.
- `jarvis/core/store.py` saves the turn under a session; the summary is updated now and then.

### 2.3 The same request from other doors

| Door | Path |
|---|---|
| **Voice in the page** | `frontend/voice.js` records → `POST /api/v1/stt` (`jarvis/api/routes/voice.py` → `jarvis/core/stt.py`, Groq Whisper) → text → the same `/chat` with `mode: "voice"` → the reply spoken. |
| **Wake word** | `jarvis/api/routes/wake.py` runs `jarvis/core/wake.py` `WakeListener` (mic → voice activity → short Whisper check for "KURAMA") → the page starts listening. |
| **Hold Alt** | `jarvis/core/ptt.py` (pynput key hook in the server) → the desktop window (`scripts/kurama_wallpaper.py`) shows the panel → the page records → same as voice. |
| **Telegram** | `jarvis/workers/telegram_bot.py` polls Telegram → the same `Agent` with `channel="telegram"` → replies via the Bot API. |
| **Terminal** | `python -m jarvis` → `jarvis/cli.py` → `Agent.run()`. Handy for debugging without the UI. |

---

## 3. The architecture: layers and why

### 3.1 The layers

```
 ┌──────────────────────────────────────────────────────────────────────┐
 │ 6. SHELLS     frontend/ (HTML/JS) · scripts/kurama_wallpaper.py (GTK) │  what you see
 │               browser_ext/ · vscode_ext/ · Telegram                   │
 ├──────────────────────────────────────────────────────────────────────┤
 │ 5. API        jarvis/api/  FastAPI: /chat (SSE), /stt, /tts, panels   │  one door for every shell
 ├──────────────────────────────────────────────────────────────────────┤
 │ 4. BRAIN      core/agent.py (LangGraph) · fastpath · planner · router │  decides what to do
 │               semantic · learn · meta · templates · slash             │
 ├──────────────────────────────────────────────────────────────────────┤
 │ 3. TOOLS      tools/core (17 general) → tools/general|interactive (130+)│  does it
 │               registry.py (register) · safety.py (gate + log)         │
 ├──────────────────────────────────────────────────────────────────────┤
 │ 2. SERVICES   core/*.py feature logic: links, todos, reminders, music,│  the real work, plain code
 │               ytdl, cleanup, doctor, files, live, stt, tts, wake...   │
 ├──────────────────────────────────────────────────────────────────────┤
 │ 1. FOUNDATION config.py · store.py (SQLite) · llm.py (Groq) · trace.py│  used by everyone
 │               memory.py (embeddings) · notify.py · jobs.py            │
 └──────────────────────────────────────────────────────────────────────┘
   plus WORKERS (jarvis/workers/): small loops for reminders, Telegram, RAM guard... (section 10)
```

**The rule: a layer may use the layers below it, never above.** A tool never imports the agent; `config.py` imports
nothing of ours. That is what lets you test a tool alone, swap the UI, or run the brain from a terminal.

### 3.2 The ideas behind it (and why each one is better than the obvious way)

1. **Cheapest path first.** Shortcut (0 tokens) → template (0 tokens) → small AI → big AI. The obvious way is "send
   everything to the AI". That is simpler, but it would burn the free tier in an hour and be slower (2–5 s vs 0.1 s).
2. **Decide by meaning, not by keywords.** A small local embedding model (`bge-small`, through `fastembed`) turns a
   sentence into numbers. Sentences that mean the same land close together, so "free RAM bro", "my ram is full,
   clean it" and "release some memory" all find the same action. Keyword rules break on every new wording.
   The project rule: **no new word rules for routing**; keywords only help while the model is loading.
3. **Few tools per AI call.** 130 tool schemas would cost ~30k tokens per call. KURAMA groups them into 17 general
   tools (`tools/core/`) and sends at most 3. The AI picks an `action` inside the tool, and plain code maps it to the
   real function.
4. **One gate for every action** (`safety.execute`). Shortcuts, the AI, Telegram and slash commands all pass the
   same gate, so "delete asks first" can never be forgotten in one path.
5. **Everything observable.** Every request is a trace; every tool call, AI call and routing decision is logged.
   Fixes are made from evidence, not guesses.
6. **Lazy and frugal.** Heavy libraries are imported inside the function that needs them, never at startup. The
   embedding model lives in a child process that is killed when idle (the only way to really give its memory back).
   Workers run as threads inside the server (one Python process instead of two saves ~55 MB).
7. **One place for settings** (`config.py`). Model names, thresholds, paths and limits live there and nowhere else,
   so tuning never means hunting through 100 files.
8. **One file = one tool**, each with a description, a schema, a safety level and a test. Adding a capability never
   means editing a giant file (with two exceptions; see section 17).
9. **Tests at three levels**: unit tests (`tests/`, ~1200, no network), the scorecard (`tests/eval/`, 260 real
   requests from your traces, 0 tokens), and a live check against the running server.

---

## 4. The folder map

```
KURAMA/
├── CLAUDE.md            rules for Claude Code (hard limits, stack, working rules) — read it once
├── LEARN.md             this guide
├── MONITORING.md        how to find problems from traces; fix history
├── PROGRESS.md          a diary of every change, newest at the bottom
├── COMMAND.md           your user guide (what to say); your own edits live here
├── README.md            short intro
├── requirements.txt     every Python dependency, pinned
├── .env                 secrets (Groq key, Telegram token...). Never committed.
│
├── jarvis/              THE PYTHON PACKAGE (all the logic)
│   ├── core/            ~110 modules: brain + services + foundation (section 5)
│   ├── tools/
│   │   ├── core/        the 17 GENERAL tools the AI sees (thin dispatchers)
│   │   ├── general/     ~150 real tools (one file each)
│   │   ├── interactive/ a few more real tools (code, files)
│   │   └── external/    (empty, reserved for API tools)
│   ├── api/             FastAPI server: app.py, turns.py, routes/
│   ├── workers/         background loops (reminders, Telegram, guards)
│   ├── agents/          optional focused helpers (coding agent)
│   ├── cli.py           terminal chat;  voice.py  the old terminal voice loop
│   └── server.py        `python -m jarvis.server` (starts the API)
│
├── frontend/            the UI: index.html, app.js (chat, panels), voice.js, orb.js, styles.css
├── scripts/             launchers + desktop programs (wallpaper window, Files reader, trace report)
├── browser_ext/         tiny Brave/Chrome extension: tells KURAMA the open tab + your highlight
├── vscode_ext/          tiny VS Code extension: the open file, the selection, edits into the editor
├── packaging/           .desktop + systemd files
├── tests/               ~130 test files; tests/eval/ = the scorecard
├── docs/                HANDOFF.md (state for a new session), NIGHT_SHIFT.md (plans), kurama_self.md
└── data/                everything KURAMA stores (not in git): databases, logs, outputs, models
```

---

## 5. Every core file

The table groups `jarvis/core/` by job. "Change it when" tells you when you would ever touch it. **Bold** = read
these first; they are the skeleton.

### 5.1 Brain (decides what to do)

| File | Lines | What it does | Change it when |
|---|---|---|---|
| **agent.py** | 1040 | The LangGraph graph: plan → route → llm ⇄ tools; streaming; history and sessions; the safety nets (retry tool-less claims, data areas, junk streams); the system prompt (`SYSTEM_PROMPT`). | The AI's behaviour, the prompt, the retry rules, how replies stream. |
| **fastpath.py** | 4100 | 0-token shortcuts: `match()` (patterns + meaning actions), `try_answer()` (run the tool, write the answer from a template), `render()` (answer templates), `meaning_ok()` (the meaning gate), `meaning_intent()`. | A shortcut does the wrong thing, or a frequent AI request should become 0 tokens. |
| **router.py** | 290 | `route()`: picks ≤3 areas. Meaning first (semantic), word rules only while the model loads; adds the area of a meaning action. | A request gets the wrong tools. |
| **semantic.py** | 270 | The meaning model: `scores()` (area by area), `match()`, `best_of()` (closest label in a small table), `ensure_ready()`, idle unload. | Routing thresholds, model loading behaviour. |
| planner.py | 450 | One task or several? Cheap checks first; a tiny AI call only when it looks like several. | Multi-task splitting is wrong. |
| learn.py | 200 | Learns areas from your corrections (stored in `data/learned.json` with the tool's name, so it follows the tool if areas change). | Learning picks up wrong lessons. |
| meta.py | 130 | `request_tools` (the AI asks for more areas); `needs_tool()` / `claims()` (did it claim an action no tool did?). | False "done" claims slip through, or real answers get retried. |
| templates.py | 140 | Fixed answers: small talk by meaning, setup guides. | Wording of greetings / small-talk answers. |
| slash.py | 240 | `/commands`: the list, typo matching, `/clear ram|storage|kurama`. | Add or change a slash command. |
| phrases.py | 70 | Random greetings / thanks so KURAMA doesn't repeat itself. | Greeting wording. |
| context.py | 120 | One line about what is open (VS Code file + selection, the Files folder, the browser tab) for the prompt. | "this" means the wrong thing. |
| focus.py | 140 | KURAMA's "current folder" (like a shell's `cd`); `refer("this")` resolves "this folder". | "this folder / here" resolves wrongly. |
| filemanager.py | 70 | Reads the Files app (via `scripts/kurama_fm.py`): open folder, selection. | Files-app context is wrong (see `data/logs/fm.log`). |
| browsertab.py | 60 | The open tab + highlight, reported by `browser_ext/`. | "this page / this link" is wrong. |
| editor.py | 130 | VS Code link (`vscode_ext/`): file, selection, edits. | Code-in-editor features. |
| rewrite.py | 270 | Read / replace the highlighted text in any app; which window is in front. | Selection features. |
| identity.py | 50 | The assistant's name (KURAMA, changeable). | Renaming. |

### 5.2 Foundation (used by everyone)

| File | Lines | What it does | Change it when |
|---|---|---|---|
| **config.py** | 1210 | Every setting: models, tiers, thresholds, paths, voices, examples for meaning. Read the comments; most explain *why* a value is what it is. | Tuning anything. Look here before touching code. |
| **llm.py** | 470 | Groq through LangChain (`ChatGroq`): `chat()`, streaming, retries on 429/5xx (reads retry headers), fallback big → small model, logging every call. | Model behaviour, timeouts, a new provider. |
| ratelimit.py | 170 | Token buckets per model (tokens/minute + requests/minute), so background jobs never starve your chat. | Rate-limit errors. |
| budget.py | 35 | Daily token budget from the call log. | Budget limits. |
| **store.py** | 860 | The main SQLite database (`data/jarvis.db`): messages, sessions, LLM/tool/routing logs, schedules, todos, watches, kv. | A new table, or a query for a feature. |
| **trace.py** | 190 | One row per request in `data/traces.db` (see MONITORING.md). | You want more evidence recorded. |
| **registry.py** | 380 | `@tool` decorator → LangChain tool; `discover()` imports every tool file; `schemas_for(groups)` → the tools to send; ordering by meaning. | Tool registration, which tools are sent. |
| **safety.py** | 250 | `execute()`: safe / confirm / blocked; asks you (`ask()`); logs every call; per-call context (`user_text`, `confirm`). | Safety rules, the yes/no flow. |
| memory.py | 910 | Search over your notes and code (SQLite FTS5 + vectors); the embedding model in a child process (`Embedder`), shared with the router. | Document search ("ask my notes"). |
| notify.py | 310 | One alert → desktop + Telegram + the alerts list. | Alert channels. |
| jobs.py | 560 | Background jobs (thread pool, progress, cancel, announce when done). | Long tasks. |
| longjobs.py | 380 | Durable jobs with checkpoints (Night Shift foundation). | Very long tasks. |
| sheets.py | 70 | Small Excel files in ~/Documents/KURAMA, written safely under a lock. | Any Excel-backed list. |
| privacy.py | 20 | Every file KURAMA creates is private to you (umask 077). | Never. |
| modes.py | 190 | Power modes (how much of KURAMA runs). | RAM/CPU modes. |

### 5.3 Voice

| File | What it does |
|---|---|
| stt.py | Groq Whisper; a parallel Nepali-forced pass; drops noise and foreign-language garbage (`not_ours()`); `data/logs/stt.log`. |
| tts.py · edge_pool.py | edge-tts voices, sentence-by-sentence streaming, warm connections to cut latency. |
| audio.py | Mic capture with voice-activity detection (webrtcvad), the player, barge-in (talk over KURAMA to stop it). |
| wake.py | Wake word without a model: a cheap loudness + VAD loop, then a short Whisper check for the name; `match_wake()` handles mishearings ("Karma", "Corama"). `data/logs/wake.log`. |
| ptt.py | Hold-to-talk key hook; `data/logs/ptt.log`. |
| dictation.py · devaudio.py · voicecfg.py | Voice typing; removing the laptop's own sound from the mic; mic volume and wake sensitivity. |

### 5.4 Services (the features; plain code, mostly 0 tokens)

You change these when *that feature* misbehaves. Each file's top docstring explains it well; read it first.

- **Lists and data**: `links.py` (link store), `readlater.py`, `todos.py`, `reminders.py` + `when.py` (time parsing
  without AI), `contacts.py`, `expenses.py`, `habits.py`, `goals.py`, `study.py`, `notes.py`, `jobqueue.py` (your job
  list), `profile.py` (facts about you), `episodes.py` (past chats).
- **Laptop**: `cleanup.py` (free RAM / clean caches), `doctor.py` (why is it slow), `netdoctor.py`, `diskclean.py`,
  `ports.py`, `installer.py`, `guard.py` (photo on unlock), `geolocate.py`, `locationlog.py`, `remotedesk.py`,
  `wifishare.py`, `vault.py` (lock a folder).
- **Media and web**: `music.py`, `ytdl.py` (downloads), `live.py` (scores, news, prices), `pageread.py` (what is this
  page), `webwatch.py`, `ocr.py`, `qr.py`.
- **Making things**: `writer.py` (long documents), `charts.py`, `diagram.py`, `videomaker.py`, `audiomaker.py`,
  `convert.py`, `organizer.py`.
- **Code help**: `assist.py` (help with the highlight), `codenav.py`, `coderun.py`, `codetidy.py`, `libhelp.py`,
  `errmem.py`, `timemachine.py`, `training.py`, `kaggle_gpu.py`.
- **KURAMA itself**: `toolsmith.py` (builds a new tool when none fits, after asking), `selfknow.py`, `reset.py`,
  `usage.py`, `digest.py`, `brief.py`, `greeting.py`, `suggest.py`, `overview.py`, `phone.py` / `phonecmds.py`
  (Telegram features), `telesec.py`.

### 5.5 API (`jarvis/api/`)

| File | What it does |
|---|---|
| app.py | Builds the FastAPI app, mounts routes, serves `frontend/`, warms the agent in the background. |
| **turns.py** | The bridge: agent thread → event queue → SSE. Confirmations. The talk-mode gate (`addressed()`). |
| security.py | Every request must come from this laptop (Host / Origin checks): the API can run tools. |
| settings.py | API settings from environment variables. |
| routes/chat.py | `POST /chat`, `POST /confirm`. |
| routes/voice.py | `POST /stt`, `POST /tts`. |
| routes/wake.py | The wake-word listener for the page. |
| routes/info.py · routes/dash.py | Panels: health, status, jobs, alerts, cards. |

---

## 6. Tools

### 6.1 Two layers

```
AI sees (≤3 per call)            plain code maps action → real tool          real tools (one file each)
tools/core/memory.py   ──────►   TABLE = {"save_link": Act("saved_links",…), ──► tools/general/saved_links.py
  action="save_link"                       "delete_link": …}                      → core/links.py (the logic)
```

- **General tools** (`jarvis/tools/core/`, 17): `apps, laptop, files, telegram, schedule, todo, media, web, info,
  memory, create, text, code, life, kurama, run_command, run_python`. Each has an `action` argument and a few plain
  ones. Its `TABLE` maps each action to a real tool and its arguments. `_hub.run()` does the mapping and calls
  `safety.execute()`, so the real tool's safety level still applies.
- **Real tools** (`jarvis/tools/general/`, `interactive/`): the actual work, usually a thin wrapper that calls a
  service in `jarvis/core/`.
- **Areas (groups)**: every real tool has a `group` ("links", "files", "audio"...). The router picks areas;
  `config.CORE_COVERS` says which general tool serves which areas; `registry.schemas_for()` turns areas into tools.

Why two layers: the AI is better at choosing among 3 broad tools with clear actions than among 130 narrow ones, and
the schemas are 10× smaller. The real tools stay small, testable and usable directly by shortcuts.

### 6.2 The tool contract (from CLAUDE.md)

One file = one tool, registered with `@tool(group=..., safety=..., description=...)`; a one-line description; type
hints + docstring become the JSON schema; a safety level (`safe` / `confirm` / `blocked`); a mocked test. `confirm`
is for delete, shell, install, send email, kill a process: the user must say yes. Example:
`jarvis/tools/general/brightness.py`.

### 6.3 How to add a tool (practise this)

1. Write the logic in a service (`jarvis/core/myfeature.py`) as plain functions. No AI, no UI: easy to test.
2. Add `jarvis/tools/general/my_tool.py` with `@tool(group="...", safety="safe", description="...")` that calls it.
   `registry.discover()` finds it automatically.
3. Let the AI reach it: add an action to the right general tool's `TABLE` in `jarvis/tools/core/<tool>.py`, and
   mention the action in its description.
4. Help routing find it by meaning: add 4–6 example phrasings to `config.TOOL_EXAMPLES["my_tool"]`.
5. Optional, for a very common request: a 0-token shortcut, either a `MEANING_SHORTCUTS` label + a few lines in
   `fastpath.meaning_intent()`, or a slash command in `slash.py`.
6. Test: `tests/test_my_tool.py` with the work mocked, at least 3 phrasings the way you really type.
7. Check: `venv/bin/python -m pytest -q tests/test_my_tool.py`, then the scorecard, then a live `curl` (section 14).

---

## 7. How KURAMA understands a request

This is where most real problems happen ("it used the wrong tool"). Understand these five mechanisms.

1. **Area scores by meaning** (`semantic.scores`). Each area has "documents": its description
   (`config.TOOL_GROUP_DESCRIPTIONS`), its examples (`config.ROUTER_EXAMPLES`, `config.TOOL_EXAMPLES`), each tool's
   description, and wordings learned from your corrections (`learn.py`). Your sentence is compared with all of them
   (cosine similarity, 0..1); each area gets its best score. There is also a "plain chat" pseudo-area: if chat wins,
   no tools are sent.
2. **Thresholds** (all in `config.py`): `SEMANTIC_MIN` (0.66, the best area must reach this), `SEMANTIC_MARGIN`
   (runners-up this close are sent too), `MEANING_GATE_MARGIN` (a shortcut runs only if its area is within 0.15 of
   the best), `MEANING_SHORTCUT_MIN` (0.82 for meaning actions), `AMBIENT_ACTION_MIN` (0.80 for talk-mode speech).
3. **Word rules** (`config.ROUTER_RULES`): only while the model is loading, or for Devanagari text the model can't
   read. Since 11-01 the model is loaded before routing (~0.6 s once), so they rarely decide anything.
4. **Masking names** (`fastpath.meaning_label`): words no action knows become X, so a name ("whatsapp", "night
   melody song") never drags the meaning toward another area. The left-over words are the argument (the name).
5. **Learning** (`learn.py`): after a correction, the earlier wording is stored with the tool that finally did the
   job. Learned rows count like examples. Bad lessons are possible: the file is `data/learned.json`, and you may
   delete a wrong row (and its vector in `learned.npy`, same position).

**Why meaning beats keywords, concretely:** "remove sofascore from link store" contains "remove" (files?) and
"link" (browser?). Keyword rules chose files + browser and the AI deleted nothing (trace 632e5841033b). By meaning,
it is closest to the link-store examples, so the right tool is sent.

---

## 8. Memory, data and storage

| What | Where | Format | Written by |
|---|---|---|---|
| Chats, sessions, summaries, logs of AI/tool/routing calls, schedules, to-dos, watches, kv settings | `data/jarvis.db` | SQLite (WAL) | `store.py` |
| One row per request (your evidence) | `data/traces.db` | SQLite | `trace.py` |
| Search index over notes and code | `data/memory.db` | SQLite FTS5 + float16 vectors | `memory.py` |
| Learned wordings | `data/learned.json` + `.npy` | JSON + numpy | `learn.py` |
| Meaning-model cache | `data/semantic_router.npz`, `data/models/` | numpy / ONNX | `semantic.py` |
| Side logs (speech, wake, hold-to-talk, Files) | `data/logs/*.log` | text, self-trimming | `stt.py`, `wake.py`, `ptt.py`, `filemanager.py` |
| Server and worker logs | `data/logs/server.log`, `worker_*.log` | text | logging |
| Things KURAMA made (essays, images, results) | `data/outputs/` | files | jobs, workspace |
| Your editable lists | `~/Documents/KURAMA/*.xlsx` (links, read later, contacts, money...) | Excel | `sheets.py` + services |
| Secrets | `.env` | text | you |

Why SQLite: one file, no server, transactions, full-text search built in, and it survives crashes (WAL mode). Why
Excel for your lists: you can open and fix them by hand in LibreOffice, so KURAMA's data is never locked away
from you.

---

## 9. Voice and the desktop

- **The desktop window** (`scripts/kurama_wallpaper.py`, ~1400 lines) uses the *system* python3 (GTK3 + WebKit2,
  which the venv can't install easily). It shows the same `frontend/` page as your wallpaper (`?wallpaper=1`) and a
  mini chat panel (`?mini=1`); it pauses the page when a window covers it, and handles hold-to-talk display.
  `scripts/kurama_fm.py` reads the Files app through accessibility (AT-SPI).
- **Power**: `scripts/kurama-power.sh on|off|status` starts/stops everything; `off` survives a reboot.
- **Voice pipeline**: record in the page (`voice.js`) → `/stt` → text → `/chat` (mode voice) → sentences →
  `/tts` → play. Barge-in: speaking while it talks stops it.
- **Talk mode**: speech long after KURAMA last spoke is sent with `ambient: true`; `turns.addressed()` keeps it only
  if it names KURAMA, is a shortcut, or by meaning is a greeting or a clear request.

---

## 10. Background work

- **Workers** (`jarvis/workers/`): tiny loops, each a `Worker` with `tick()` every N seconds (≥5 s, `base.py`).
  They run as threads inside the server (`inproc.py`). Main ones: `scheduler` (reminders), `telegram_bot`,
  `resource_guard` (RAM/CPU alerts), `process_watch` (training runs), `crash_watchdog`, `clipboard_watch`,
  `daily_digest`, `brief`, `timemachine`, `location_tracker`, `guard`.
- **Jobs** (`core/jobs.py`): anything long (an essay, a video, a scan) runs in a thread pool, saves to
  `data/outputs/`, and announces itself when done. Your voice loop is never blocked.
- **Job list** (`core/jobqueue.py`): things you ask KURAMA to do later; "start the jobs" runs them.
- **Rate limits** (`core/ratelimit.py`): jobs share token buckets with chat and always yield to your requests.

---

## 11. Technologies and why

| Technology | Used for | Why this one (and what was rejected) |
|---|---|---|
| **Groq** (gpt-oss-20b fast, gpt-oss-120b smart, qwen3.8-27b voice/vision, Whisper) | the AI, speech-to-text | Free tier, very fast. Rejected: local LLMs (no GPU, 8 GB RAM), paid APIs. |
| **Gemini** (2.5-flash, flash-lite; optional `GEMINI_API_KEY`) | fallback when Groq's daily limits are used up | Free tier, ~10 requests/min. Before qwen, which claimed actions it never did. A model that answers 429 is skipped for a while (`llm._cool`). |
| **LangChain** (`ChatGroq`, tool schemas) | one interface for messages and tools | Readable, swappable provider. Raw Groq SDK only for Whisper. |
| **LangGraph** | the agent as a graph (plan/route/llm/tools/join), parallel fan-out with `Send` | Explicit, testable states; easy to add a node. Rejected: a hand-written while-loop (hard to extend), multi-agent frameworks (too many tokens). |
| **fastembed + ONNX Runtime** (`bge-small-en-v1.5`) | meaning: routing, shortcuts, search | ~250 MB, CPU only, no PyTorch. Rejected: sentence-transformers (pulls in torch, >1 GB). |
| **SQLite** (FTS5, WAL) | every database | No server, crash-safe, built-in search. Rejected: Chroma/Postgres servers (RAM, setup). |
| **FastAPI + uvicorn + SSE** | the API | Async streaming of replies; automatic docs at `/docs`. SSE instead of WebSockets: one-way streaming is all we need and it passes through proxies. |
| **Plain HTML/JS** | the UI | No build step, no node_modules, loads instantly. |
| **GTK3 + WebKit2** (system python) | the wallpaper/panel window | A real desktop window that can sit behind other windows. |
| **edge-tts** | voices (en, hi, ne) | Free, natural, streaming. Piper as offline fallback. |
| **webrtcvad** | detecting speech in the mic | Tiny C library, no torch. |
| **pynput, xdotool, wmctrl, pactl, brightnessctl** | controlling the laptop on X11 | Standard Linux tools; each is checked with `which` before use. |
| **psutil** | RAM/CPU/process info | Cross-platform, cheap. |
| **openpyxl** | your Excel lists | Editable by hand. |
| **yt-dlp** | downloads | Kept current; YouTube breaks old versions. |
| **pytest** | tests | The standard. |

---

## 12. The dependency map

The arrows mean "imports / calls". Lower boxes never call upper ones.

```
frontend/app.js ──HTTP──► api/routes/chat.py ──► api/turns.py ──► core/agent.py
                                                                  │  │  │  │
          ┌───────────────────────────────────────────────────────┘  │  │  └─────────────► core/trace.py, core/learn.py
          ▼                                                          │  ▼
  core/fastpath.py ──► core/slash.py                                 │  core/llm.py ──► core/ratelimit.py, core/store.py
          │ ──► core/semantic.py ◄── core/router.py ◄────────────────┘          ▲
          │           │                    │                                    │ (planner, summaries, toolsmith)
          │           ▼                    ▼                                    │
          │     core/memory.py       core/registry.py ──discover──► tools/core/* ──► tools/core/_hub.py
          │     (Embedder, shared)          │                                          │
          ▼                                 ▼                                          ▼
  core/safety.py ◄──────────────────── every tool call ─────────────────────► tools/general/*.py
          │                                                                            │
          ▼                                                                            ▼
  core/store.py (logs)                                         core/<feature>.py (links, todos, ytdl, cleanup...)
                                                                                       │
                                                         core/config.py ◄──── everyone reads settings here
```

Rules of thumb:
- `config.py` → depends on nothing; everything depends on it.
- `store.py`, `llm.py`, `safety.py`, `registry.py` → foundation; changing their behaviour affects everything. Run the
  full test suite after touching them.
- A service in `core/<feature>.py` → used by its tool(s) and maybe by `fastpath.py`. Changing it affects that
  feature only. Grep before changing: `grep -rn "from jarvis.core import links\|links\." jarvis | head`.
- `fastpath.py` and `agent.py` → many features pass through them; small edits, many tests.

---

## 13. "I want to change X"

| I want to... | Change this | Check with |
|---|---|---|
| Change what the AI is told | `agent.py` `SYSTEM_PROMPT` (keep < 250 tokens: a test checks) | `pytest tests/test_p7c.py` |
| Use another model / tier | `config.py` `LLM_DEFAULT`, `LLM_FAST`, `TIERS`, `TIER_CHAIN` | live check |
| Fix "it used the wrong tool" | Add meaning examples: `config.ROUTER_EXAMPLES` / `TOOL_EXAMPLES`; or the tool's description in `tools/core/<tool>.py` | `python -m tests.eval.harness` |
| Make a frequent request 0 tokens | `config.MEANING_SHORTCUTS` + `fastpath.meaning_intent()`, or `slash.py` | scorecard "instant" % |
| Change a 0-token answer's wording | `fastpath.render()` / `templates.py` / `phrases.py` | tests for that intent |
| Change when it asks yes/no | the tool's `safety=` in its `@tool`, or `safety.ask()` inside the tool | its test |
| Change thresholds (meaning, RAM alerts, idle unload) | `config.py` (each value has a comment) | related tests |
| Add a feature | section 6.3 | |
| Change a list's file (links, money...) | `config.py` `LINKS_FILE`, `READ_LATER_FILE`... | |
| Change speech recognition / dropping | `stt.py` `not_ours()`, `config.STT_*` | `data/logs/stt.log` |
| Change the wake word | `wake.py` `match_wake()`, `config.WAKE_*`, `ASSISTANT_NAMES` | `data/logs/wake.log` |
| Change the voice | `config.py` `VOICES`, `tts.py` | |
| Change RAM limits / alerts | `config.JARVIS_CORE_MAX_MB`, `RESOURCE_*`; `workers/resource_guard.py` | `worker_resource_guard.log` |
| Change the UI | `frontend/app.js` (logic), `index.html`, `styles.css`; the panel window in `scripts/kurama_wallpaper.py` | reload the page |
| Add a slash command | `slash.py` `COMMANDS` | `pytest tests/test_slash.py` |
| Add a background loop | a new `workers/<name>.py` subclassing `Worker`; enable it in `config.WORKERS_ENABLED` | its log |

---

## 14. Debugging

### 14.1 The method (use it every time)

1. **Reproduce or find the evidence.** Don't guess. Find the trace of the bad request.
2. **Locate the step.** Was it the shortcut (path `fastpath`), the router (wrong `route_groups` / `tools_sent`), the
   AI (wrong tool chosen, or no tool), the tool itself (`tools[].result` says error), or the UI?
3. **Prove the cause.** Re-run that step alone (examples below) until you can say "this line, with this input,
   produces this wrong output".
4. **Fix the class, not the sentence.** If "remove sofascore" failed because the AI had no delete action, add the
   action for every link, not a special case for "sofascore".
5. **Test with your real way of typing** (typos, "bro", "..", Nepali/Hindi), then the scorecard, then live.

### 14.2 The toolkit

```bash
cd /media/leo/Project1/New_project/KURAMA

# what went wrong lately (traces + speech/wake/hold-to-talk/Files logs + job list)
venv/bin/python scripts/trace_report.py --days 3
venv/bin/python scripts/trace_report.py --show 3fa9c1          # one request in full

# ask the running KURAMA directly (same path as the UI)
curl -sN -X POST http://127.0.0.1:8000/api/v1/chat -H 'Content-Type: application/json' -d '{"text":"show me link stroe"}'

# which shortcut would take a sentence? (0 tokens)
venv/bin/python -c "from jarvis.core import fastpath as f; i=f.match('free RAM bro'); print(i and (i.tool, i.args))"

# which areas/tools would the AI get?
venv/bin/python -c "
from jarvis.core import registry, router, semantic; registry.REGISTRY._ensure(); semantic.ensure_ready()
r=router.route('remove sofascore from link store', log_it=False); print(r.groups, [t.name for t in registry.REGISTRY.schemas_for(r.groups)])"

# area scores by meaning
venv/bin/python -c "
from jarvis.core import registry, semantic; registry.REGISTRY._ensure(); semantic.ensure_ready()
print(semantic.scores('save this website names whatsapp')[:5])"

# the terminal chat (no UI)
venv/bin/python -m jarvis

# tests and the scorecard
venv/bin/python -m pytest -q tests/test_links.py         # one file
venv/bin/python -m pytest -q                              # all (~2.5 min)
venv/bin/python -m tests.eval.harness                     # must stay >= 65% instant / 100% right / 98% router

# restart KURAMA after a code change
scripts/kurama-power.sh off; scripts/kurama-power.sh on
```

### 14.3 Reading a trace

`--show <id>` prints: `text` (what KURAMA heard), `path` (fastpath / ai / multi), `route_method` + `route_groups`
(how it chose areas), `tools_sent` (what the AI could use), `tools` (what actually ran, with arguments and the first
300 characters of the result), `llm` (each AI call: model, purpose, tokens, ms), `retried`, `asked` / `denied`
(yes/no), `answer`, `ms`, `error`. Typical readings:
- `path: ai`, `tools: []`, answer says "Done" → the AI claimed without acting (section 2, safety nets).
- the right tool is missing from `tools_sent` → routing (section 7).
- the right tool ran but `result` starts with "error" → the tool / service.
- `route_method: rules` → the meaning model wasn't loaded.

---

## 15. How to learn it

### 15.1 Top-down (recommended first): from the request to the details

| Day | Read | Goal |
|---|---|---|
| 1 | This guide, sections 1–3. `CLAUDE.md`. | Know the shape. |
| 2 | `jarvis/api/routes/chat.py` (90 lines), `jarvis/api/turns.py` `run_turn()`. | See a request arrive. |
| 3 | `agent.py`: `stream()`, `_fast()`, `_build()`, `_route_node()`, `_llm_node()`, `_tools_node()`. Skip the rest. | See the brain's main loop. |
| 4 | `fastpath.py`: `match()`, `meaning_ok()`, `meaning_intent()`, `try_answer()`, then ONE area function, e.g. `links_intent()`. | See the 0-token path. |
| 5 | `router.py` `route()`, `semantic.py` `scores()` / `match()` / `best_of()`. | See how meaning picks areas. |
| 6 | `registry.py` (`tool`, `schemas_for`), `safety.py` (`execute`, `ask`), `tools/core/_hub.py`, `tools/core/memory.py`. | See how tools are found and run. |
| 7 | One feature end to end: `tools/general/saved_links.py` → `core/links.py` → `tests/test_links.py` + `tests/test_link_store_ai.py`. | See a complete vertical slice. |
| 8 | `llm.py` `chat()`; `trace.py`; `scripts/trace_report.py`. | See the AI call and the evidence. |

While reading, keep a running KURAMA and the `curl` command handy: change nothing, just predict what each sentence
will do, then check.

### 15.2 Bottom-up (second): from small pieces to the whole

Start with files that depend on almost nothing and build upward: `config.py` (skim the comments) → `sheets.py` →
`links.py` → `saved_links.py` → `registry.py` → `safety.py` → `_hub.py` → `semantic.py` → `router.py` →
`fastpath.py` (one area) → `agent.py`. Each step uses only what you already know.

### 15.3 Practice exercises (do them in order; each has a test you can write)

1. **Read a trace.** Run `trace_report.py --days 3`, pick one "Likely mistake", `--show` it, and say in one
   sentence at which step it went wrong.
2. **Predict routing.** Write 10 sentences the way you speak; predict the area; check with the router snippet.
3. **Change a template.** Change the "Copied the path" answer in `fastpath.render()`; run its test; see it live.
4. **Add meaning examples.** Find a request that went to the AI in your traces; add 2 examples to
   `MEANING_SHORTCUTS` or `ROUTER_EXAMPLES`; run the scorecard.
5. **Add a slash command** `/ip` that answers your local IP (a phrase or a tool in `slash.py`).
6. **Add a small tool**: "how many files are in this folder" (service + tool + `files` TABLE action + test).
7. **Add a 0-token meaning action** for your new tool (section 6.3 step 5).
8. **Fix a real bug from a trace** using the method in 14.1, with a test that fails before your fix.
9. **Add a worker** that logs your battery % every 10 minutes (subclass `Worker`), and watch its log.
10. **Read one big feature** you care about (music, downloads, reminders) and draw its flow on paper.

### 15.4 How to read a big file without drowning

- Read the module docstring first (most files explain themselves at the top).
- List the functions: `grep -n "^def \|^class \|    def " jarvis/core/agent.py`.
- Follow one call from the entry point; ignore everything else for now.
- Use the tests as examples: `grep -rn "links\." tests | head` shows how a module is called.

---

## 16. Lessons for any big project

These are the patterns that keep a 50,000-line project workable. They apply far beyond KURAMA.

1. **Layers with one-way dependencies.** UI → API → brain → tools → services → foundation. You can test, replace or
   run any layer alone.
2. **A single source of truth for settings** (`config.py`) with a comment on *why* each value is what it is.
3. **Contracts for extension points.** Every tool follows the same shape (decorator, description, schema, safety,
   test), so adding the 151st tool is as easy as the first.
4. **Cheapest path first.** Do the common cases with plain code; call the expensive thing (AI, network) only when you
   must. Measure how often each path is used (the scorecard's "instant %").
5. **Observability from day one.** Logs, traces and side logs make bugs provable. A bug you can't see is a bug you
   guess at.
6. **Fix classes, not instances.** One special case per complaint turns into thousands of fragile rules.
7. **Safety by default.** One gate, deny when unsure, ask for anything destructive, log everything.
8. **Resource frugality.** Lazy imports, idle unloading, child processes for heavy models, one process where
   possible. Measure memory after each change.
9. **Tests at several levels.** Fast unit tests with mocks; a scorecard on real requests; a live check. Write tests
   with real users' messy input, not textbook sentences.
10. **Graceful degradation.** No internet → offline answers; the model not loaded → word rules; Groq 429 → back off
    and use a smaller model. Never crash the user's flow.
11. **Write it down.** A diary (`PROGRESS.md`), a handoff (`docs/HANDOFF.md`), a fix history (`MONITORING.md`) and a
    map (this file) let anyone continue the work.

---

## 17. Honest weak spots

No real project is perfect. Know these before you change things:

- **`fastpath.py` is 4,100 lines of regex patterns.** It grew before routing by meaning existed. New shortcuts
  should use the meaning table (`MEANING_SHORTCUTS`), not new patterns; old patterns are kept because they work and
  are tested, but they are the most fragile part. A future refactor could split it by area (`fastpath/links.py`...).
- **`config.py` is 1,200 lines.** It is one source of truth, which is good, but it mixes settings with long example
  lists. Examples could move to their own file.
- **`frontend/app.js` is 2,900 lines** in one file (no framework, by design). Splitting it into modules per panel
  would make UI changes easier.
- **The AI sometimes ignores its tools** (gpt-oss "I can't save without a URL"). The safety nets catch most cases;
  the long-term fix is more 0-token actions by meaning.
- **The name `jarvis/`**: the package kept its old name to avoid a risky rename; everything user-facing says KURAMA.

---

## 18. Glossary

| Word | Meaning here |
|---|---|
| **Area / group** | A family of tools ("links", "files", "audio"). The router picks areas. |
| **General tool** | One of the 17 broad tools the AI sees (`tools/core/`), with an `action` argument. |
| **Real / specialised tool** | A tool that does the work (`tools/general/`). |
| **Shortcut / fast path** | A request answered without the AI (0 tokens). |
| **Meaning / semantic / embedding** | Turning a sentence into a vector so similar meanings are close; done locally. |
| **Meaning gate** | A shortcut runs only if the sentence's meaning agrees with its area. |
| **Tier** | Which model: fast (20b), smart (120b), voice (qwen). |
| **Token** | The AI's unit of text (≈ ¾ of a word); the free tier limits tokens per minute and per day. |
| **Trace** | One saved row per request, with everything that happened. |
| **Scorecard** | `tests/eval/harness.py`: how often shortcuts handle requests, how often they're right, how often the router offers the right tools. |
| **SSE** | Server-Sent Events: the server streams the reply to the page piece by piece. |
| **Worker** | A small background loop inside the server. |
| **Job** | A long task running in the background, announced when done. |
| **Confirm** | A tool that needs your yes before it runs. |
| **Cold path** | A request that arrives while the meaning model is not loaded. |
