# LEARN.md: how KURAMA works, and how to run and improve it yourself

This guide is for you, the owner. You have used KURAMA every day; this is the map of its code. After reading it
(with the files open beside it) you should be able to:

- explain what happens between "you say something" and "KURAMA answers";
- explain how KURAMA remembers what just happened (short-term memory) and how it runs several linked tasks;
- find the file that does any one thing, and know what else it touches;
- debug a problem from evidence (traces and logs) instead of guessing;
- add or change a tool, a shortcut, a setting, or a piece of the UI;
- monitor KURAMA and improve it on your own, without help;
- reuse the ideas in any big project of your own.

Read it in order the first time. Sections 2, 3, 4 and 5 are the most important: they are the skeleton every other
file hangs on. Later sections are reference: come back to them when you need them.

> Updated 2026-11-05 (learning from feedback, tool reach, Telegram, hold-to-talk, engineering tooling, and the
> production-readiness phase: fastpath split into `intents/`, typed tool results, type gate, wider lint gate,
> coverage floor, `/metrics`, frontend checks, ADRs; see 2.4 and 23). Names and line counts are from that day. Files grow; if a name
> moved, `grep -n "def name" -r jarvis` finds it. Never trust a doc over the code: the code is the truth, this guide
> is the map.

---

## Contents

1. [What KURAMA is, in one page](#1-what-kurama-is-in-one-page)
2. [The life of one request (the most important section)](#2-the-life-of-one-request)
3. [Short-term memory: how KURAMA remembers this conversation](#3-short-term-memory)
4. [Multitasking: the task graph](#4-multitasking-the-task-graph)
5. [The architecture: layers and why](#5-the-architecture-layers-and-why)
6. [The folder map](#6-the-folder-map)
7. [Every core file: what it does, when to change it](#7-every-core-file)
8. [Tools, memories and agents: the plug-in points, how to add one](#8-tools)
9. [How KURAMA understands a request (routing in depth)](#9-how-kurama-understands-a-request)
10. [The AI models: tiers, fallbacks, limits](#10-the-ai-models)
11. [Tokens: where they go and how they are cut](#11-tokens)
12. [Long-term memory, data and where everything is stored](#12-long-term-memory-data-and-storage)
13. [Privacy and safety](#13-privacy-and-safety)
14. [Voice, wake word, hold-to-talk, the desktop window](#14-voice-and-the-desktop)
15. [Background work: workers, jobs, the job list](#15-background-work)
16. [Technologies: what each one is, where it is used, what to learn](#16-technologies-what-each-one-is-where-kurama-uses-it-what-to-learn)
17. [Who depends on whom (the dependency map)](#17-the-dependency-map)
18. ["I want to change X": which file, which setting](#18-i-want-to-change-x)
19. [Debugging: your toolkit, step by step](#19-debugging)
20. [Monitoring and improving it yourself (the routine)](#20-monitoring-and-improving-it-yourself)
21. [How to learn it: a 12-week, day-by-day plan (1–2 h a day)](#21-how-to-learn-it-a-day-by-day-plan-12-hours-a-day)
22. [Lessons for any big project](#22-lessons-for-any-big-project)
23. [Industry level: where KURAMA stands, and what is left](#23-industry-level-where-kurama-stands-and-what-is-left)
24. [Glossary](#24-glossary)

---

## 1. What KURAMA is, in one page

KURAMA is a personal assistant that runs all day on one laptop (Ubuntu, X11, 8 GB RAM, no GPU). You talk to it by
typing, by voice (wake word, talk mode, hold Alt), or from your phone through Telegram. It can do 130+ things:
open apps, control the laptop, manage files, reminders, to-dos, money, links, music, downloads, code help, web
answers, and more. It can do several linked things from one sentence ("make a folder in downloads and open it in VS
Code") and it remembers what it just did ("send that image to telegram").

Three hard limits shaped every design decision. Almost every "why is it done this way?" comes back to one of them:

| Limit | What it forces |
|---|---|
| **Free AI tiers**: Groq ~8,000 tokens a minute and ~200,000 a day per model; Gemini ~10 requests a minute | Do as much as possible with **0 tokens** (shortcuts, templates, plain code). Send the AI only the 1–3 tools it needs, never all 130. Keep the system prompt under 250 tokens. Never pay twice for the same work. |
| **8 GB RAM**, shared with VS Code and Chrome, running all day | Load heavy things only when needed and free them when idle. One process instead of many. No PyTorch, no GPU libraries. |
| **It acts on your real laptop** | Every tool call passes one safety gate. Risky actions (delete, shutdown, commands) ask you first. Keys and passwords are never read into the AI. Everything is logged. |

The code is Python 3.12 in the `jarvis/` package (the old name; the user-facing name is KURAMA and can be
changed). The UI is plain HTML/JS in `frontend/`. A small GTK program shows that UI as your desktop wallpaper and a
mini chat panel.

---

## 2. The life of one request

Follow one message from your keyboard to the answer. Every step names the file and the function, so you can open it
and read along.

### 2.1 The picture

```
 you type / speak / Telegram
            │
            ▼
 ┌──────────────────────┐  frontend/app.js sendChat() ──HTTP POST /api/v1/chat (Server-Sent Events)──┐
 │  UI (browser page)   │                                                                            │
 └──────────────────────┘                                                                            ▼
                                              ┌─────────────────────────────────────────────────────────────┐
                                              │ API  jarvis/api/routes/chat.py chat() → api/turns.py run_turn │
                                              └──────────────────────────────┬──────────────────────────────┘
                                                                             ▼
 ┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ BRAIN  jarvis/core/agent.py  Agent.stream()                                                               │
 │   0. _begin_turn: did KURAMA just ask you something? (_open_question)  · resume the chat after a restart  │
 │   ① shortcut?        fastpath.try_answer()  (a choice "2", patterns, meaning actions)  → 0 tokens         │
 │   ② bare yes/no?     _bare_answer()  (only when KURAMA asked nothing)                   → 0 tokens         │
 │   ③ the graph (LangGraph):                                                                                │
 │        plan ─┬─ one task ────► route → llm ⇄ tools → answer                                               │
 │              └─ several ─────► schedule → step, step… (at once) → schedule → … → finish                   │
 └───────────────┬───────────────────────────────────────┬───────────────────────────────┬─────────────────┘
                 ▼                                       ▼                               ▼
 ┌──────────────────────────────┐   ┌──────────────────────────────────┐   ┌───────────────────────────────┐
 │ TOOLS  registry + safety gate │   │ AI  jarvis/core/llm.py            │   │ WORKING MEMORY  workmem.py     │
 │  tools/core/* (17 general)    │   │  Groq → Gemini → qwen, retries,   │   │  every tool call's real files, │
 │  tools/general/* (130+ real)  │──►│  rate limits, cooldown, logging   │   │  folders, images; choices      │
 └──────────────┬───────────────┘   └──────────────────────────────────┘   └───────────────────────────────┘
                ▼                          (the safety gate writes into working memory after every call)
 your laptop: files, apps, xdotool, pactl, Excel sheets, SQLite...
            ▲
            │  events stream back: delta (text) · tool · confirm (yes/no card) · done
            └──────────────────────────────────────────────────────────────────────────────────────────────
```

### 2.2 Step by step

**Step 1: the UI sends it.** `frontend/app.js` `sendChat()` calls `api.chat()` in `frontend/api.js`: a
`POST /api/v1/chat` whose answer is a **stream** (Server-Sent Events). The reply arrives piece by piece, so you see
and hear it before the AI has finished.

**Step 2: the API receives it.** `jarvis/api/routes/chat.py` `chat()` checks the body (`ChatIn`: text, mode, lang,
ambient) and hands it to `jarvis/api/turns.py` `Engine.run_turn()`, which:
- runs the agent in its own thread and turns what it yields into events (`delta`, `tool`, `confirm`, `done`);
- drops talk-mode speech that isn't for KURAMA (it must name KURAMA, be a shortcut, or by meaning be a greeting or
  a clear request);
- parks the thread when a tool asks yes/no, until you click the card (`POST /api/v1/confirm`) or it times out.

**Step 3: before anything, `_begin_turn()`** (`agent.py`):
- `_open_question()`: KURAMA's newest message to you (this chat, the other channel, or an alert it sent on its own),
  if it asked or offered something in the last 10 minutes (`config.QUESTION_TTL_S`). Remembered as `self._asked`.
  Section 3.4 explains why.
- After a restart, the chat's last turns come back from the database (`_resume()`), so "what were we talking about"
  still works.
- Facts you state about yourself are captured with plain code (`profile.capture_and_save`).

**Step 4: path ① (shortcut, 0 tokens).** First the text is cleaned: `spelling.fix()` (common slips) and
`mywords.expand()` (your own phrases). Then `_fast()` → `jarvis/core/fastpath.py` `try_answer()` → `match()`, which
tries in order (learned shortcuts and kept answers from `recipes.py` come right after it):
1. **A choice** (`workmem.choose()`): KURAMA just listed numbered files ("I found 3 copies: 1. … 2. …") and you
   answered "2" / "the second one" / "the one in Redmi" → the same tool runs again on that file.
2. Agent switches, slash commands (`/clear ram`, `/weather pokhara`; `slash.py`), cleaning, "selection first"
   (something highlighted → explain / translate / improve it, chosen by meaning).
3. Hundreds of regex patterns, one function per area (`links_intent`, `video_dl_intent`, `sendfile_intent`...).
4. `meaning_intent()`: actions chosen **by meaning** from `config.MEANING_SHORTCUTS` (save/list links, new folder,
   open in VS Code, copy path, Telegram message, clean RAM, tabs, scroll...).

A pattern runs only if `meaning_ok()` agrees: its area must be close to the best area for the whole sentence. A bare
"yes"/"no" never triggers a shortcut by itself (`_bare_yes_no`). If something matches, the tool runs through the
safety gate and a template writes the answer. **0 tokens, ~100 ms.** About 2 of every 3 requests end here.

**Step 5: path ② (bare yes/no).** "yes"/"no" when KURAMA asked nothing gets a fixed answer (`_bare_answer()`).
If KURAMA *did* ask something, the reply goes on to the AI, with the question.

**Step 6: path ③ (the graph).** Built in `Agent._build()`:

```
START → plan ─┬─ one task ─────────────► route → llm ⇄ tools → END
              └─ several tasks ─► schedule ─► step  step  step ─► schedule ─► … ─► finish → END
                                              (all ready steps run at the same time)
```

- **plan** (`_plan_node`, `planner.py`): one task or several? Several linked tasks go to the task graph
  (section 4). One task goes to route.
- **route** (`_route_node`, `router.py`): picks at most 3 **areas** by meaning (`semantic.py`), then the general
  tools for them (`registry.schemas_for()`).
  - If KURAMA just asked something and your reply is short ("yes", "do it"), the tools come from **the meaning of
    KURAMA's question** (route method `answer`): "Want me to play some music?" → "yes" gets the music tools.
  - The text/code tool is added for the open VS Code file only when the request **means** it
    (`_about_context()`; section 11).
  - It also picks the model tier (fast / smart / voice).
- **messages** (`_messages()`): a short system prompt; the last 6 turns (the last 2 replies carry what their tools
  did); a rolling summary; "Things from this chat" (section 3); KURAMA's open question; one line of what is open
  (VS Code, Files, the browser; `context.py`).
- **llm** (`_llm_node`): calls the model through `llm.py` `chat()` with only those tools. Safety nets:
  - a refusal, or "I did it" with no tool behind it, is retried once with the tools (`meta.needs_tool`);
  - a claim that survives the retry is replaced by "I didn't do it: the action didn't run this time";
  - a tool-less answer about your saved things (links, to-dos, reminders, jobs, money) is retried with the tools;
  - a junk stream ("… … …", invisible spaces) is held back and replaced by the tool's own result.
- **tools** (`_tools_node`): every call goes through `safety.py` `execute()` (allowed? needs your yes? log it;
  record what it touched in working memory). A general tool maps its `action` to the real tool through
  `tools/core/_hub.py`. If every call was a simple action that worked, its own sentence is the answer (**direct
  reply**, no second AI call; section 11). Otherwise the result goes back to **llm** (at most 4 rounds).

**Step 7: the answer streams back.** agent → `turns.py` → SSE → `app.js` draws the bubble and, in voice mode, speaks
sentence by sentence (`frontend/voice.js` → `POST /api/v1/tts` → edge-tts).

**Step 8: after the answer (nothing waits for this).**
- `_remember()` adds the turn to the history with one line of what the tools did (`did_line()`), and saves it to
  the database (`store.py`). A choice that wasn't answered is dropped.
- `trace.py` writes one row to `data/traces.db`: text, path, route, tools, plan + step results, models, tokens,
  answer, time. This is your evidence (sections 19–20).
- `learn.py` judges the **previous** turn, but only from what *you* did: a correction ("no, I meant..."), a
  complaint or praise (judged by meaning), or a 👍/👎. Silence teaches nothing. `recipes.py` turns a confirmed
  request into a 0-token shortcut. All of it is explained with examples in `docs/LEARNING.md`.

### 2.3 The same request from other doors

| Door | Path |
|---|---|
| **Voice in the page** | `frontend/voice.js` records → `POST /api/v1/stt` (`api/routes/voice.py` → `core/stt.py`, Groq Whisper) → text → the same `/chat` with `mode: "voice"` → the reply spoken. |
| **Wake word** | `api/routes/wake.py` runs `core/wake.py` `WakeListener` (mic → voice activity → short Whisper check for "KURAMA") → the page starts listening. |
| **Hold Alt** | `core/ptt.py` (key hook in the server) → the desktop window (`scripts/kurama_wallpaper.py`) shows the panel → the page records → same as voice. |
| **Telegram** | `workers/telegram_bot.py` polls Telegram → the same `Agent` with `channel="telegram"` → replies through the Bot API. Same working memory: "send that image" on Telegram finds the image made on the laptop. |
| **Terminal** | `python -m jarvis` → `jarvis/cli.py` → `Agent.run()`. Handy for debugging without the UI. |

### 2.4 What changed since 11-01 (read this if you learned the old version)

| Area | Before | Now (11-05) | Files |
|---|---|---|---|
| Before anything | the raw text went in | `spelling.fix()` (common slips: "opne", "remain me") then `mywords.expand()` ("when I say good night, lock the screen") | `spelling.py`, `mywords.py` |
| Shortcuts | regex + meaning gate | + **learned shortcuts with slots** and **kept answers** (a 👍 answer reused for a near-identical question, 0 tokens) | `recipes.py` |
| Which tools the AI gets | a hand-made area → tool map | `registry.reach()` reads each general tool's TABLE to know what it can run; ≤ 3 tools; an unreachable specialised tool only when it matches by meaning ≥ 0.6 | `registry.py` |
| AI calls | ~2,700 tokens median | ~800–1,100; a tool's own sentence is often the reply (direct reply) | `agent.py`, `config.DIRECT_REPLY_*` |
| Learning | also learned from silence | **only from you**: 👍/👎, spoken praise or complaints, corrections, "when I say…", reply-style rules. A plain 👎 = "bad reply", with optional tool suggestions in plain words | `learn.py`, `recipes.py`, `style.py`, `docs/LEARNING.md` |
| Multitasking | some links missed | `add_dependencies` adds hard and *soft* (order-only) links, `merge_tails` joins "when it finishes…", `cover()` adds back parts the plan missed, follow-up jobs can wait for several jobs | `planner.py`, `agent.py` |
| Picking from a list | re-ran the tool with the pick | a pick from **search results** acts on that result: "open 2 in vs code", "send the third one" | `workmem.choose()`, `act_on()` |
| File search | files + folders + KURAMA's own outputs | "X folder" → folders only; folders inside another match and KURAMA's `data/` are dropped | `find_files.py` `_tops`, `_junk` |
| Apps | one launch try | `open_verified`: raise an existing window, else launch and check a window appears, try gtk → gio → exe, remember the way that worked | `_apps.py` |
| Music | low volume, no seek | volume 100 kept, seek (skip/back/jump), a music card with controls | `music.py`, `frontend/app.js` |
| Sound | two volumes multiplied | one volume while the echo canceller runs; the canceller restores your default device | `devaudio.py` |
| Telegram | uploads blocked the bot; slash commands had no PIN | uploads run beside the chat with an "uploading" status, fresh connection per upload, photos ≤ ~150 KB, a time limit; risky slash commands ask the PIN | `telegram_bot.py`, `notify.py`, `send_file_telegram.py`, `telesec.py` |
| Hold-to-talk | first holds after start recorded silence | no system echo canceller for hold-to-talk; the panel opens only after the page says "ready"; the ring spins at key-down | `voice.js`, `app.js`, `kurama_wallpaper.py` |
| Speed test | 10 MB once (0.3 s) | ~15 s: ping, download, upload | `netdoctor.speed()` |
| Engineering | — | `pyproject.toml`, `Makefile`, lint gate, pre-commit, GitHub CI | section 23 |
| Code layout | `fastpath.py` 4,587 lines | split by area into `jarvis/core/intents/` (base, files, desktop, media, todo, control); `fastpath.py` ~2,900 lines re-imports them, so `fastpath.X` still works | `core/intents/`, ADR 0010 |
| Tool results | sentences parsed back with regexes | a tool can return `Reply(text, paths=[...])`: still a string, plus exact data; picks use the exact paths | `core/results.py`, ADR 0009 |
| Quality gates | lint only | + `make type` (mypy on the core contracts), wider lint rules (tests that never ran, closures over loop values), coverage floor, `make js-check` | `pyproject.toml`, `Makefile` |
| Metrics | SQLite tables only | `GET /api/v1/metrics` in Prometheus format: tokens, tool calls, routing, jobs, RAM (`make metrics`) | `core/metrics.py`, `api/routes/metrics.py` |
| Decisions | comments in code | 11 one-page decision records | `docs/adr/` |
| Extending | a new agent meant editing a list in `agents/__init__.py`, `config.AGENT_TOOL_MODULES` and the switch's alias table; memory kinds had no common shape | **plug-ins**: a tool, a memory source or an agent is one file/folder, found by itself, isolated if broken, checked by contract tests; `make new-tool` / `new-memory` / `new-agent` write the skeleton | `core/plugins.py`, `core/memories.py`, `memories/`, `agents/`, section 8.4, ADR 0011 |
| Knows itself | a hand-written page about itself; "can you" by word match | **self-knowledge**: every tool has a card built from its own code (what, how, settings, how to ask); "how did you do that?" is explained from the real last request; 20 safe **settings** changed by voice ("make the speed test 30 seconds", undo, reset); **help** by area or need; "can you" by meaning | `core/selfindex.py`, `core/usersettings.py`, `tools/general/{explain_self,kurama_settings,help_me,find_capability}.py`, section 8.5, ADR 0012 |
| Small fixes | — | window commands at 0 tokens ("minimize YouTube"); a folder named in words opens in VS Code; your own commands ("when I say X, Y", "show my commands"); a ready Colab / Kaggle notebook linked to KURAMA | sections 8.4–8.5, PROGRESS.md |

---

## 3. Short-term memory

"Short-term memory" means: what KURAMA knows about **this conversation**, beyond your words. Before 2026-11-01 the
chat history kept only words, so everything a tool did vanished: "send that image" had no image, "open it in VS
Code" had no "it", and "yes" got "nothing is waiting for a yes". There are now five layers.

### 3.1 The five layers

| Layer | What it holds | Where | Cost |
|---|---|---|---|
| **Chat history** | your last 6 messages and KURAMA's replies, plus a rolling summary of older ones | `Agent.history`, `Agent.summary`; saved in `data/jarvis.db` | the words themselves |
| **What the tools did** | one line per reply: `[tools this turn: make_folder(path=~/Downloads/x) -> Created folder …]` | appended to the reply in history (`did_line()`); only the last 2 replies keep it (`config.DID_TURNS`) | ~40–60 tokens |
| **Things** (working memory) | every real file / folder / image / video / document a tool touched or made, newest first, with its kind | `jarvis/core/workmem.py`, kv key `workmem_things` | ~50 tokens in the prompt; 0 tokens for shortcuts |
| **Choices** | the numbered list of real paths KURAMA just showed, and the tool call to repeat with the one you pick | `workmem.py`, kv key `workmem_choice`, 10 minutes | 0 tokens |
| **KURAMA's open question** | its newest message to you if it asked or offered something (any channel, alerts too) | `Agent._open_question()` | ~50 tokens, only when there is one |

### 3.2 How things are recorded (no tool needs to know about it)

Every tool call passes `safety.execute()`. After the call, `done()` calls `workmem.record_call(name, args, ok,
result)`, which:
1. takes the paths written in the arguments and in the result (`paths_in()`: "Saved to /home/leo/My Notes/x.md.
   Ask me…" → `/home/leo/My Notes/x.md`, spaces included);
2. keeps **only paths that really exist on disk** (never a guess) and never system folders;
3. ignores listings (more than 3 paths = a search result, not something made);
4. stores each as `{"p": path, "k": kind, "by": tool, "t": time}`; the kind comes from the extension (image,
   video, audio, document, code, archive, folder, file).

Finished background jobs add their output too (`jobs._finish` → `workmem.note_job`). Because the gate does it, all
130 tools, shortcuts, Telegram and jobs are covered without one line of change in any tool.

### 3.3 How "it", "this folder", "that image" are resolved

`focus.refer(text)` (and the send shortcuts in `fastpath._focus_intent`) decide, in order:
1. a path you pasted in this message;
2. **a kind named** ("that image", "the pdf", "the essay"): the newest thing of that kind
   (`workmem.kind_named` + `workmem.latest(kind)`). No thing of that kind → nothing (the AI asks), never some folder;
3. **something made or touched in the last 2 minutes** (`config.WORKMEM_FRESH_S`): "make folder X … open it" means X,
   even if the Files app shows another folder;
4. the Files app's selection / open folder, when Files is the app you used last;
5. KURAMA's remembered current folder (`focus.py`, like a shell's `cd`).

For the AI, `workmem.line()` adds one line to the system prompt: "Things from this chat, newest first: image
~/Pictures/horse.png (2 min ago); folder ~/Downloads/new_project2 (5 min ago)". The model reads it the way you
would.

### 3.4 Answers to KURAMA's questions

The problem: KURAMA asks "Want me to play some music?", you say "yes", and the AI got "yes" with no music tool (the
router can't route "yes"), or the bare-yes rule said "nothing is waiting".

The fix is general: `_open_question()` finds KURAMA's newest message (this chat, the other channel's chat, or an
alert from `notify.recent_sent`). If it asks or offers something (a "?" or "want me to / should I / would you
like…") within 10 minutes:
- `_bare_answer()` lets the reply go to the AI;
- `_route_node()` routes a short reply **by the question's meaning** (route method `answer`): the question "play
  some music?" brings the music tools;
- `_messages()` tells the AI: "Your latest message to the user asked: … If their reply answers it, do what it
  agreed to."

Choices (3.1) are the 0-token version of the same idea, for lists of real files.

### 3.5 After a restart

The laptop chat now resumes like Telegram did: `_begin_turn()` → `_resume()` reloads the last 6 turns and the
summary from `data/jarvis.db` if the last message was within `config.SESSION_IDLE_S` (4 hours). Things and choices
live in the kv store, so they survive restarts too.

### 3.6 What short-term memory does NOT do

- It does not remember the *content* of a long answer (an essay is a file; the file is the thing).
- A thing that was deleted from disk is forgotten automatically (`things()` keeps only existing paths).
- It does not decide what you meant. It offers the AI and the shortcuts the right candidates; meaning still decides.

---

## 4. Multitasking: the task graph

### 4.1 The problem it solves

"create a new folder in download folder name new_project2 and open this folder in vs code" used to:
- split into 3 tasks by words (including "let's work" as a task of its own);
- run them **at the same time**, because nothing said that "this folder" needs the first task;
- give each task a full AI call with the whole chat (5,500 tokens);
- open an old Webcam folder in VS Code, while the AI claimed "Made it" with no tool behind it.

### 4.2 The new way, in one picture

```
 "let's work .. create a new folder in download folder name new_project2 and open this folder in vs code"
   │
   ▼ planner.plan()
   ├─ parts(): split into clauses, drop filler by meaning ("let's work ..")
   ├─ every part is a 0-token shortcut?  → plan by rules (0 tokens)
   ├─ seen this shape before and it worked? → learned plan (0 tokens)
   └─ else one small AI call (decompose) → steps + depends_on
   │
   ▼ add_dependencies(): a step that refers back ("this folder", "it", "that image") needs the step before
   │
   steps = [ {0: "create a new folder in download folder name new_project2"},
             {1: "open this folder in vs code", depends_on: [0]} ]
   │
   ▼ LangGraph loop in agent.py
   schedule ──► step 0 ──► schedule ──► step 1 ──► schedule ──► finish
   (_after_schedule sends every step whose needs are all "ok", all at once, with LangGraph's Send)
```

### 4.3 What one step does (`Agent._step_node`)

1. **Inputs become the freshest things.** Every file/folder the needed steps made is noted again in working memory
   (`workmem.note`), so "it / this folder / that image" in this step resolve to them (section 3.3, rule 3).
2. **Long steps** (an essay, a big report) start a background job and the step is `waiting`.
3. **Shortcut first.** If the needed steps made things, the step tries the 0-token shortcut (the folder was made, so
   "open this folder in vs code" is the `open_vscode` meaning action on that folder).
4. **Else one AI call**, with only this step's tools, the inputs (`taskgraph.inputs_text`: "step 1 (create …) →
   Created folder … Files: /home/leo/Downloads/new_project2"), and **no chat history** (cheaper and no confusion).
5. **Checked, not trusted** (`taskgraph.judge`): the step `failed` if it claims an action with no tool behind it, if
   every tool call failed, or if a tool answered "error: …" (`workmem.collect()` records this step's calls, things
   and jobs). It is `waiting` if it started a background job, else `ok`.
6. **One re-plan** (`taskgraph.replan`, ~150 tokens, fast model): a failed step may get one corrected step ("the
   folder exists already → use another name", "wrong path → the right folder"). If that fails too, it stops.

### 4.4 The end (`Agent._finish_node` + `taskgraph.settle`)

- A step whose needed step failed is **skipped, with the reason**: *I skipped "open it in vs code" because "create a
  folder …" didn't work.* Nothing is faked.
- Steps that need a background job (the essay, the picture) become **one follow-up job** that waits for the job and
  runs on its real output (`start_after_job` → `after_job`).
- Independent steps never wait for unrelated ones.
- One answer: each step's sentence in order; "started job #N" lines last.
- A plan the AI made that fully worked is **learned** by meaning (`taskgraph.learn_plan` →
  `data/learned_plans.json`): the next request of the same shape ("make a folder X in downloads and open it in vs
  code" with any name) reuses the links between steps with 0 tokens (`config.TASK_PLAN_MATCH` 0.93).

### 4.5 Your 6-step example

"generate an image of a dog, write a description of it, save that to dog.md, open it in VS Code, close VS Code, and
send the document to telegram":

| Step | Needs | What happens |
|---|---|---|
| 1 image | – | `generate_image` starts a job → `waiting` |
| 2 description | 1 | runs in the follow-up job, after the image exists (the image is a thing) |
| 3 save dog.md | 2 | follow-up job; `write_file` → dog.md becomes a thing |
| 4 open in VS Code | 3 | "it" = dog.md |
| 5 close VS Code | 4 | **closes only windows this request opened**; if VS Code was open before (your work), it asks (`close_app` + `taskgraph.windows_before`) |
| 6 send to telegram | 3 | "the document" = dog.md (kind document) |

### 4.6 Settings and switches (`config.py`)

`TASK_GRAPH` (False = the old chains, kept as a fallback), `PLANNER_MAX_TASKS` (8), `TASK_REPLAN`,
`TASK_REPLAN_MAX_TOKENS`, `TASK_PLANS_KEEP`, `TASK_PLAN_MATCH`, `FILLER_EXAMPLES` / `NOT_FILLER_EXAMPLES` /
`FILLER_MIN` (what counts as filler, by meaning).

---

## 5. The architecture: layers and why

### 5.1 The layers

```
 ┌──────────────────────────────────────────────────────────────────────┐
 │ 6. SHELLS     frontend/ (HTML/JS) · scripts/kurama_wallpaper.py (GTK) │  what you see
 │               browser_ext/ · vscode_ext/ · Telegram                   │
 ├──────────────────────────────────────────────────────────────────────┤
 │ 5. API        jarvis/api/  FastAPI: /chat (SSE), /stt, /tts, panels   │  one door for every shell
 ├──────────────────────────────────────────────────────────────────────┤
 │ 4. BRAIN      agent.py (LangGraph) · fastpath · planner · taskgraph   │  decides what to do
 │               router · semantic · learn · meta · templates · slash    │
 ├──────────────────────────────────────────────────────────────────────┤
 │ 3. TOOLS      tools/core (17 general) → tools/general|interactive     │  does it
 │               registry.py (register) · safety.py (gate + log + memory)│
 ├──────────────────────────────────────────────────────────────────────┤
 │ 2. SERVICES   core/*.py feature logic: links, todos, reminders, music,│  the real work, plain code
 │               ytdl, cleanup, doctor, files, live, stt, tts, wake...   │
 ├──────────────────────────────────────────────────────────────────────┤
 │ 1. FOUNDATION config · store (SQLite) · llm (Groq/Gemini) · trace ·   │  used by everyone
 │               workmem · focus · memory (embeddings) · notify · jobs   │
 └──────────────────────────────────────────────────────────────────────┘
   plus WORKERS (jarvis/workers/): small loops for reminders, Telegram, RAM guard... (section 15)
```

**The rule: a layer may use the layers below it, never above.** A tool never imports the agent; `config.py` imports
nothing of ours. That is what lets you test a tool alone, swap the UI, or run the brain from a terminal.
(`workmem` is foundation: the safety gate writes into it, and the brain reads it.)

### 5.2 The ideas behind it (and why each one beats the obvious way)

1. **Cheapest path first.** Shortcut (0 tokens) → template (0 tokens) → small AI → big AI. Sending everything to the
   AI would be simpler, but it would burn the free tier in an hour and be slower (2–5 s vs 0.1 s).
2. **Decide by meaning, not by keywords.** A small local embedding model (`bge-small` through `fastembed`) turns a
   sentence into numbers; sentences that mean the same land close together. Keyword rules break on every new
   wording. Project rule: **no new word rules for routing**.
3. **Few tools per AI call.** 130 tool schemas would cost ~30k tokens per call. KURAMA groups them into 17 general
   tools and sends at most 3.
4. **One gate for every action** (`safety.execute`). Shortcuts, the AI, Telegram, slash commands and task steps all
   pass it, so "delete asks first" can't be forgotten in one path, and working memory sees every action.
5. **Remember what was DONE, not only what was SAID.** Real paths from real tool calls (working memory) instead of
   asking the AI to remember file names from prose.
6. **Plan once, run steps cheaply.** One planning call (or none), then small steps that get real inputs, instead of
   one long AI loop that re-sends everything every round (~5× the tokens).
7. **Verify, don't trust.** A claim without a tool is a failure; a failed step skips what needs it, with the reason.
8. **Everything observable.** Every request is a trace; every tool call, AI call and routing decision is logged.
   Fixes are made from evidence, not guesses.
9. **Lazy and frugal.** Heavy libraries are imported only inside the function that needs them. The embedding model
   lives in a child process killed when idle. Workers are threads in the server.
10. **One place for settings** (`config.py`). Model names, thresholds, paths and limits live there and nowhere else.
11. **One file = one tool**, each with a description, a schema, a safety level and a test.
12. **Graceful degradation.** Groq used up → Gemini → qwen; the meaning model not loaded → word rules; no internet →
    offline answers. Never crash your flow.
13. **Tests at three levels**: unit tests (`tests/`, ~1,400, no network), the scorecard (`tests/eval/`, 270 real
    requests from your traces, 0 tokens), and a live check against the running server.

---

## 6. The folder map

```
KURAMA/
├── CLAUDE.md            rules for Claude Code (hard limits, stack, working rules)
├── LEARN.md             this guide
├── MONITORING.md        how to find problems from traces; the routine; fix history
├── PROGRESS.md          a diary of every change, newest at the bottom
├── COMMAND.md           your user guide (what to say); your own edits live here
├── requirements.txt     every Python dependency, pinned
├── requirements-dev.txt developer tools only (mypy, pytest-cov), pinned
├── pyproject.toml       project settings: lint gate, type gate, pytest, coverage floor
├── Makefile             every everyday command: `make help`
├── .env                 secrets (Groq key, Gemini key, Telegram token...). Never committed.
│
├── jarvis/              THE PYTHON PACKAGE (all the logic)
│   ├── core/            ~115 modules: brain + services + foundation (section 7)
│   │   └── intents/     the fast-path intents by area (base, files, desktop, media, todo, control)
│   ├── memories/        memory sources, one file each (notes, profile, links, documents): section 8.4
│   ├── tools/
│   │   ├── core/        the 17 GENERAL tools the AI sees (thin dispatchers)
│   │   ├── general/     ~150 real tools (one file each)
│   │   └── interactive/ a few more real tools (code, files) + _secrets.py (key detection)
│   ├── api/             FastAPI server: app.py, turns.py, routes/
│   ├── workers/         background loops (reminders, Telegram, guards)
│   ├── agents/          optional focused helpers, one folder each (coding): found by themselves, section 8.4
│   ├── cli.py           terminal chat
│   └── server.py        `python -m jarvis.server` (starts the API)
│
├── frontend/            the UI: index.html, app.js, voice.js, orb.js, styles.css
├── scripts/             launchers, the desktop window, trace_report.py, tool_round.py
├── browser_ext/         tiny Brave/Chrome extension: the open tabs + your highlight
├── vscode_ext/          tiny VS Code extension: the open file, the selection, edits
├── tests/               ~140 test files; tests/eval/ = the scorecard
├── docs/                HANDOFF.md (state for a new session), plans
│   └── adr/             Architecture Decision Records: one page per big choice
└── data/                everything KURAMA stores (not in git): databases, logs, outputs, models
```

---

## 7. Every core file

**Bold** = read these first; they are the skeleton. Line counts from 2026-11-01.

### 7.1 Brain (decides what to do)

| File | Lines | What it does | Change it when |
|---|---|---|---|
| **agent.py** | 1270 | The LangGraph graph (plan → route → llm ⇄ tools; schedule → step → finish); streaming; history, sessions, resume; `_open_question`, `did_line`, `_about_context`, direct replies; the safety nets; `SYSTEM_PROMPT`. | The AI's behaviour, the prompt, retries, how steps run or join. |
| **intents/** | 6 files, 100–600 each | The fast-path intents moved out of fastpath.py by area: `base` (Intent, FastResult, `yes_no`, `_nth`), `files` (open/search/find/send), `desktop` (volume, brightness, media keys, DND, alerts), `media` (music, video, image, chart), `todo` (links, to-dos, goals, reading list), `control` (reminders, power, clock). | A shortcut in that area misbehaves. Add new intents to the right area file. |
| **usersettings.py** | 230 | The safe list of settings the owner can change (`SETTINGS`: name, config key, range, unit), `set_value` / `undo` / `reset` / `listing`; saved in `data/user_settings.json`, applied by `config.py` at start. | Add a setting: one `Setting(...)` line (the key must exist in config.py and be read as `config.KEY` at run time). |
| **selfindex.py** | 70 | A card per tool built from its code: description, its file's docstring (how it works), the settings it reads, example phrases. `card`, `cards_for`, `by_meaning`. | Never by hand: write a clear docstring at the top of a tool's file. |
| **plugins.py** | 60 | Finds plug-ins in a package (`names`, `load`, `load_one`), isolates a broken one, lists them (`broken()`). | You add a new kind of extension point. |
| **memories.py** | 80 | The memory-source contract (`MemorySource`, `Hit`) and `search()` across sources with rank fusion. | You add a kind of memory (`make new-memory`). |
| **results.py** | 30 | `Reply(str)`: a tool's text plus exact data (`.data`, e.g. `paths`); `data_of()`. | A tool's result is acted on later (a pick, a chain): return a Reply. |
| **metrics.py** | 80 | Prometheus text from the SQLite logs (last 24 h) + process RAM/CPU, for `GET /api/v1/metrics`. | You want a new number on a dashboard. |
| **fastpath.py** | 2900 | 0-token shortcuts: `match()` (choice, patterns, meaning actions), `try_answer()`, `render()` (answer templates), `meaning_ok()`, `meaning_intent()`, `tg_message_text()`, `_focus_intent()`. | A shortcut does the wrong thing, or a frequent AI request should become 0 tokens. |
| **planner.py** | 480 | One task or several (`is_multi`), `parts()` (clauses without filler), `decompose()` (the AI split), `add_dependencies()` (refers back → needs the step before), `_shortcut_tasks()` (0-token plans). | Splitting or linking of tasks is wrong. |
| **taskgraph.py** | 220 | Step helpers: `judge`, `replan`, `settle` (skipped / after), `filler`, learned plans, `inputs_text`, window guard. | Step checks, re-planning, filler, learned plans. |
| **workmem.py** | 300 | Working memory: things, kinds, `record_call`, `latest`, `line`, choices, `collect` (one step's calls). | "it / that image" resolves wrongly; a tool's paths aren't remembered. |
| **router.py** | 285 | `route()`: ≤3 areas; meaning first, word rules only while the model loads. | A request gets the wrong tools. |
| **semantic.py** | 265 | The meaning model: `scores()`, `match()`, `best_of()`, `ensure_ready()`, idle unload. | Routing thresholds, model loading. |
| learn.py | 200 | Learns areas from your corrections (`data/learned.json`). | Learning picks up wrong lessons. |
| meta.py | 140 | `request_tools`; `claims()` / `needs_tool()` (did it claim an action no tool did?). | False "done" claims slip through, or real answers get retried. |
| templates.py | 140 | Fixed answers: small talk by meaning, setup guides. | Greeting / small-talk wording. |
| slash.py | 240 | `/commands`, `/clear ram|storage|kurama`. | Add or change a slash command. |
| context.py | 130 | One line about what is open (VS Code file + selection, Files, browser tab); private files are skipped. | "this" means the wrong thing. |
| focus.py | 150 | KURAMA's current folder; `refer()` resolves "this / it / that image" (section 3.3). | Reference resolution order. |
| filemanager.py · browsertab.py · editor.py | 60–130 | The Files app, the browser tab, the VS Code link. | That context is wrong. |
| rewrite.py | 330 | Read / replace the highlight in any app; refuses keys and private files. | Selection features. |

### 7.2 Foundation (used by everyone)

| File | Lines | What it does | Change it when |
|---|---|---|---|
| **config.py** | 1280 | Every setting, with comments explaining *why*. | Tuning anything. Look here before touching code. |
| **llm.py** | 510 | `chat()`, streaming, `structured()`; Groq through `ChatGroq`, Gemini through `ChatGoogleGenerativeAI` (`_gemini`); retries, fallback chain, cooldown of used-up models (`_cool`), logging. | Model behaviour, timeouts, a new provider. |
| ratelimit.py | 170 | Token/request buckets per model, so jobs never starve your chat. | Rate-limit errors. |
| budget.py | 35 | Daily token budget per model from the call log. | Budget limits. |
| **store.py** | 855 | `data/jarvis.db`: messages, sessions, AI/tool/routing logs, schedules, todos, kv. | A new table or query. |
| **trace.py** | 195 | One row per request in `data/traces.db`. | You want more evidence recorded. |
| **registry.py** | 380 | `@tool` → LangChain tool; `discover()`; `schemas_for(groups)`. | Tool registration, which tools are sent. |
| **safety.py** | 255 | `execute()`: safe / confirm / blocked; `ask()`; logs every call; feeds working memory. | Safety rules, the yes/no flow. |
| memory.py | 910 | Search over your notes and code (FTS5 + vectors); the shared embedding process. | Document search. |
| notify.py | 310 | One alert → desktop + Telegram + the alerts list; `recent_sent()`. | Alert channels. |
| jobs.py · longjobs.py | 570 · 380 | Background jobs; durable jobs with checkpoints; finished outputs → working memory. | Long tasks. |
| sheets.py | 70 | Small Excel files in ~/Documents/KURAMA, written under a lock. | Excel-backed lists. |
| privacy.py · modes.py | 20 · 190 | Private file permissions; power modes. | Rarely. |

### 7.3 Voice

| File | What it does |
|---|---|
| stt.py | Groq Whisper; a parallel Nepali-forced pass; drops noise and foreign garbage (`not_ours()`); `data/logs/stt.log`. |
| tts.py · edge_pool.py | edge-tts voices, sentence by sentence, warm connections. |
| audio.py | Mic capture with voice activity (webrtcvad), the player, barge-in. |
| wake.py | Wake word: loudness + VAD, then a short Whisper check; `match_wake()` handles mishearings. `data/logs/wake.log`. |
| ptt.py | Hold-to-talk key hook; `data/logs/ptt.log`. |
| dictation.py · devaudio.py · voicecfg.py | Voice typing; removing the laptop's own sound from the mic; mic settings. |

### 7.4 Services (the features; plain code, mostly 0 tokens)

Each file's top docstring explains it; read it first.

- **Lists and data**: `links.py`, `readlater.py`, `todos.py`, `reminders.py` + `when.py`, `contacts.py`,
  `expenses.py`, `habits.py`, `goals.py`, `study.py`, `notes.py`, `jobqueue.py`, `profile.py`, `episodes.py`.
- **Laptop**: `cleanup.py`, `doctor.py`, `netdoctor.py`, `diskclean.py`, `ports.py`, `installer.py`, `guard.py`,
  `geolocate.py`, `locationlog.py`, `remotedesk.py`, `wifishare.py`, `vault.py`, `uiagent.py` (keys/windows).
- **Media and web**: `music.py`, `ytdl.py`, `live.py`, `pageread.py`, `webwatch.py`, `ocr.py`, `qr.py`.
- **Making things**: `writer.py`, `charts.py`, `diagram.py`, `videomaker.py`, `audiomaker.py`, `convert.py`,
  `organizer.py`.
- **Code help**: `assist.py`, `codenav.py`, `coderun.py`, `codetidy.py`, `libhelp.py`, `errmem.py`,
  `timemachine.py`, `training.py`, `kaggle_gpu.py`.
- **KURAMA itself**: `toolsmith.py`, `selfknow.py`, `reset.py`, `usage.py`, `digest.py`, `brief.py`, `greeting.py`,
  `suggest.py`, `overview.py`, `phone.py` / `phonecmds.py`, `telesec.py`.

### 7.5 API (`jarvis/api/`)

| File | What it does |
|---|---|
| app.py | Builds the FastAPI app, mounts routes, serves `frontend/`, warms the agent. |
| **turns.py** | Agent thread → event queue → SSE; confirmations; the talk-mode gate. |
| security.py | Every request must come from this laptop (the API can run tools). |
| routes/chat.py · voice.py · wake.py · info.py · dash.py | `/chat` + `/confirm`; `/stt` + `/tts`; the wake listener; panels. |

---

## 8. Tools

### 8.1 Two layers

```
AI sees (≤3 per call)            plain code maps action → real tool          real tools (one file each)
tools/core/memory.py   ──────►   TABLE = {"save_link": Act("saved_links",…), ──► tools/general/saved_links.py
  action="save_link"                       "delete_link": …}                      → core/links.py (the logic)
```

- **General tools** (`jarvis/tools/core/`, 17): `apps, laptop, files, telegram, schedule, todo, media, web, info,
  memory, create, text, code, life, kurama, run_command, run_python`. Each has an `action` argument; its `TABLE`
  maps each action to a real tool. `_hub.run()` does the mapping and calls `safety.execute()`.
- **Real tools** (`jarvis/tools/general/`, `interactive/`): the actual work, usually a thin wrapper over a service.
- **Areas (groups)**: every real tool has a `group`. The router picks areas; `config.CORE_COVERS` says which
  general tool serves which areas.

### 8.2 The tool contract

One file = one tool, `@tool(group=..., safety=..., description=...)`; type hints + docstring become the JSON schema;
a safety level (`safe` / `confirm` / `blocked`); a mocked test. `confirm` = delete, shell, install, send email, kill
a process. Example: `jarvis/tools/general/brightness.py`.

**Good tool results help memory for free:** return a full sentence with the **full path** of what you made ("Created
folder /home/leo/Downloads/x"), and start failures with `error:`. Working memory records the path; the step checker
sees the failure; a short request can use the sentence as the direct reply.

### 8.3 How to add a tool (practise this)

1. Write the logic in a service (`jarvis/core/myfeature.py`) as plain functions.
2. `make new-tool NAME=my_tool [GROUP=general] [SAFETY=safe]` writes `jarvis/tools/general/my_tool.py` and
   `tests/test_tool_my_tool.py`. Fill in the TODOs; the tool calls your service. `registry.discover()` finds it.
   That is already enough: a tool no general tool's TABLE reaches is offered by itself when the request's meaning
   matches its description (`registry.schemas_for`), so write the one-line description carefully.
3. For a tool used often: also add an action to the right general tool's `TABLE` in `jarvis/tools/core/<tool>.py`
   (it is then reached reliably and costs no extra schema tokens).
4. Help routing: 4–6 example phrasings in `config.TOOL_EXAMPLES["my_tool"]`.
5. If its own sentence is a complete answer for a short request, add it to `config.DIRECT_REPLY_SINGLE`.
6. Optional, for a very common request: a 0-token shortcut (`MEANING_SHORTCUTS` label + a few lines in
   `fastpath.meaning_intent()`, or a slash command).
7. Test with 3+ phrasings the way you really type; run the scorecard; a live `curl` (section 19).

### 8.4 The plug-in architecture: add a tool, a memory or an agent without touching the others

KURAMA has three extension points. Each one is **a file (or a folder) you drop in**: nothing central is edited,
the new piece is found by itself, and **if it is broken it is logged and skipped while everything else keeps
working**. That is the rule that keeps a big project flexible: *new code plugs in; it never edits old code.*

```
                     found by                     contract                               checked by
tools/general/x.py   registry.discover()          @tool(group, safety, description) -> str  test_plugin_contracts (every tool)
memories/x.py        memories.sources()           SOURCE = MemorySource(name, description,  test_plugin_contracts (every source)
                                                           search(query, k) -> [Hit], heavy)
agents/x/__init__.py agents.AGENTS (folders)      SPEC = AgentSpec(name, title, groups,      test_plugin_contracts (every agent)
agents/x/tools.py    agents.tool_modules()          prompt, examples, aliases, welcome, ...)
                     all via core/plugins.py: import each one alone, catch its errors, list them in plugins.broken()
```

| You want | Command | What you fill in | What happens by itself |
|---|---|---|---|
| **A new tool** | `make new-tool NAME=word_count` | the function body, its one-line description | discovered, safety-gated, logged, offered by meaning, schema built from type hints, contract-tested |
| **A new kind of memory** | `make new-memory NAME=bookmarks` | `_search(query, k)`: read your data, return `Hit`s | `memories.search()` asks it, fuses its results with the others (rank fusion), skips it if it fails; `recall` uses it when no note matches |
| **A new agent** | `make new-agent NAME=study` | `SPEC` (title, prompt line, example phrasings), its tools in `tools.py` | listed in the dashboard and `/agent`, switched on by name or alias, its tools offered only while it is on, its tool group kept out of normal routing |

**The memory sources today:** `notes` (things you asked KURAMA to remember), `profile` (facts about you), `links`
(saved links), `documents` (your own files, hybrid search; *heavy*, so it is asked only by name:
`memories.search(q, only=["documents"])`). Short-term memory (`workmem`, section 3) is different: it is "what just
happened in this conversation", not a store you search.

**Why this design (the ideas to learn):**
- **Inversion of control / plug-ins**: the core asks "who is there?" instead of keeping a list. Adding never edits
  the list, so adding never breaks a neighbour. (Same idea as pytest plugins, Flask blueprints, VS Code extensions.)
- **A small contract per extension point**: a dataclass (`MemorySource`, `AgentSpec`) or a decorator (`@tool`)
  says exactly what a plug-in must provide. Anything else stays private to the plug-in.
- **Fault isolation**: `plugins.load_one()` catches the import error of one plug-in; `memories.search()` catches the
  error of one source at run time; the safety gate catches one tool's exception. A bug stays inside its own file.
- **Contract tests over every plug-in**: `tests/test_plugin_contracts.py` loops over all tools, sources and agents,
  so a new one is checked without writing a new test (you still write one for its behaviour).
- **Lazy loading**: agent folders are listed without importing them; a heavy memory source runs only when asked.
- **Observability**: `plugins.broken()` and the `kurama_plugins_broken` metric show what failed to load.

---

### 8.5 KURAMA knows itself: explain, settings, help

Three abilities so you never have to remember how KURAMA works:

| You say | What happens | Cost |
|---|---|---|
| "how did you do that?", "how do you measure my internet speed?", "explain the code you gave me", "can I use this with VS Code?" | `explain_self` collects FACTS: your last request from the trace (what ran, with which arguments, what came back), the **cards** of those tools (+ the 2 closest by meaning), and the start of a file it made (a notebook, a script). One smart-model call (gpt-oss-120b, low reasoning: the fast one invented menu buttons) answers from those facts only. | ~800–1,500 tokens, only when asked |
| "make the speed test 30 seconds", "set end of speech wait to 1500 ms", "talk faster +30%", "set the daily summary time to 9 PM" | the setting is found by name or meaning, the value parsed with its unit ("2 minutes" for a seconds setting) and checked against its range; saved and applied at once (`restart=True` ones after a restart) | 0 tokens |
| "what settings can I change?", "undo that setting", "reset all settings" | the list with current values; undo the last change; back to defaults | 0 tokens |
| "help me use kurama", "help with sending files to my phone", "can you translate a pdf?" | every area with real example commands, or the closest tools by meaning, plus "teach me your own command" and "I can make a new tool" | 0 tokens |

**How it stays true:** nothing here is a hand-kept description. `core/selfindex.py` builds each tool's card from the
tool's description, the docstring at the top of its file, the settings its code reads (`config.KEY`) and its example
phrases. A contract test fails if any tool lacks them. Change the code, and the explanation changes with it.

**Why settings are a fixed list:** the AI never edits code or arbitrary config. `usersettings.SETTINGS` names what may
change, with ranges; everything else needs a code change, and KURAMA says so. That keeps "change yourself" safe.

**Questions about itself win before the word patterns** ("how do you measure my internet speed" must explain, not run
a speed test): `fastpath._window_first` checks a few high-confidence, verified meanings first.

**Try these (copy them into the chat):**
1. "what is my internet speed" then "how did you measure that?"
2. "make the speed test 30 seconds", "what is my internet speed" (it now runs ~30 s), "undo that setting"
3. "what time is it" then "how do you get the time?"
4. "set up colab" then "explain this notebook" then "can I use it with VS Code?"
5. "what settings can I change?", "talk faster +25%", "reset all settings"
6. "help me use kurama", "help with sending files to my phone", "can you convert a pdf to word?"
7. "minimize vs code", "open kurama project", "show my commands"

## 9. How KURAMA understands a request

Most real problems happen here ("it used the wrong tool"). Five mechanisms:

1. **Area scores by meaning** (`semantic.scores`). Each area has "documents": its description
   (`config.TOOL_GROUP_DESCRIPTIONS`), examples (`config.ROUTER_EXAMPLES`, `config.TOOL_EXAMPLES`), tool descriptions,
   and learned wordings. Your sentence is compared with all of them (cosine similarity 0..1). A "plain chat"
   pseudo-area wins → no tools are sent.
2. **Thresholds** (`config.py`): `SEMANTIC_MIN` (0.66), `SEMANTIC_MARGIN`, `MEANING_GATE_MARGIN` (a shortcut runs
   only if its area is within 0.15 of the best), `MEANING_SHORTCUT_MIN` (0.82), `AMBIENT_ACTION_MIN` (0.80),
   `FILLER_MIN` (0.86), `CONTEXT_TOOL_SEL_MIN` (0.80).
3. **Word rules** (`config.ROUTER_RULES`): only while the model loads, or for Devanagari text.
4. **Masking names** (`fastpath.meaning_label`): unknown words become X, so a name never drags the meaning.
5. **Learning** (`learn.py`): after a correction, the earlier wording is stored with the tool that finally did it.
   Wrong rows can be deleted from `data/learned.json` (and the same position in `learned.npy`).

Two newer uses of the same idea:
- **The question decides the tools for a short answer** (route method `answer`, section 3.4).
- **Filler is judged by meaning** (`taskgraph.filler`: closer to `FILLER_EXAMPLES` than to `NOT_FILLER_EXAMPLES`).

---

## 10. The AI models

| Tier | Chain (first that works answers) | Used for |
|---|---|---|
| fast | gpt-oss-20b → gpt-oss-120b → **gemini-2.5-flash → gemini-flash-lite** → qwen | most chat and tool calls, planning, re-planning |
| smart | gpt-oss-120b → gpt-oss-20b → Gemini → qwen | requests that need two areas or reasoning |
| voice | qwen → gpt-oss-20b → gemini-2.5-flash | plain spoken chat (qwen starts fastest) |
| vision | qwen → gpt-oss-120b → gemini-2.5-flash | screenshots, photos |
| writer | gpt-oss-120b → gemini-2.5-flash | background writing jobs |

Gemini models are in the chains only when `GEMINI_API_KEY` is in `.env`.

**How a request moves along the chain** (`llm.py`):
- `_chain()` drops models that spent their daily self-budget (`budget.py`) or are **cooling down** (`_cool`).
- A 429 with a short wait → wait and retry the same model (`_plan_retry`, max `LLM_MAX_WAIT_S`).
- A 429 with a long wait (a daily limit) → the model is skipped for its `Retry-After` (min `LLM_COOLDOWN_S`
  120 s, max 1 h). The log says "<model> is rate-limited: skipped for N s". Before this, every request first failed
  on both used-up gpt-oss models.
- Any other error → the next model.
- `ratelimit.py` spaces requests per model (`MODEL_TPM`, `MODEL_LIMITS`: Gemini ~9–14 requests/min).

**Why this order:** Groq is fastest and has the biggest free quota. Gemini is good at tool calls and has its own free
quota (it uses `max_output_tokens` and `thinking_budget=0`; see `_bound`). qwen is last: on 11-01 it claimed actions
it never did. To change models, edit `LLM_*` and `TIER_CHAIN` in `config.py`; nothing else names a model.

---

## 11. Tokens: where they go and how they are cut

Measured from 445 AI requests (10-29 → 11-01): ~2,175 input tokens and 2.24 AI calls per AI request. One AI call's
input is: system prompt (~160) + prompt lines (things, question, context: 0–150) + 6 turns of history (200–800) +
tool schemas (200–600 for 1–3 tools) + your message. Every extra round re-sends all of it.

| Cut | How | Saves |
|---|---|---|
| Shortcuts (2/3 of requests) | `fastpath` | everything |
| Choices, answers to questions, Telegram messages | `workmem.choose`, `tg_message_text` | a whole AI request |
| Few tools | ≤3 general tools, by meaning | ~25k per call |
| Text tool only by meaning | `_about_context()` (was sent on 45% of AI requests because VS Code was open) | ~300 per request |
| Direct replies | the tool's own sentence ends a simple action (`DIRECT_REPLY_TOOLS`); for short single requests also `DIRECT_REPLY_SINGLE` (≤ `DIRECT_REPLY_MAX_WORDS` words, not multi-part) | the second call (~1,000) |
| History trims | replies cut to `HISTORY_MSG_MAX_CHARS`; tool lines only on the last 2 | 100–400 |
| Task-graph steps | no chat history, only their tools and inputs; shortcut first; learned plans | 1,000–4,000 per multi-step request |
| Cooldown | used-up models are skipped | failed calls and seconds |

To find the next cut: the report's "Most tokens" and "Asked the AI most often" sections (section 20).

---

## 12. Long-term memory, data and storage

| What | Where | Format | Written by |
|---|---|---|---|
| Chats, sessions, summaries, AI/tool/routing logs, schedules, to-dos, kv settings | `data/jarvis.db` | SQLite (WAL) | `store.py` |
| Working memory: things, choice | `data/jarvis.db` kv keys `workmem_things`, `workmem_choice` | JSON in kv | `workmem.py` |
| Current folder + history | kv `conversation_focus`, `focus_history` | kv | `focus.py` |
| One row per request (your evidence) | `data/traces.db` | SQLite | `trace.py` |
| Search index over notes and code | `data/memory.db` | FTS5 + vectors | `memory.py` |
| Learned wordings | `data/learned.json` + `.npy` | JSON + numpy | `learn.py` |
| Learned plans | `data/learned_plans.json` | JSON (request text, vector, step links) | `taskgraph.py` |
| Meaning-model cache | `data/semantic_router.npz`, `data/models/` | numpy / ONNX | `semantic.py` |
| Side logs (speech, wake, hold-to-talk, Files, window freezes) | `data/logs/*.log` | text, self-trimming | various |
| Server and worker logs | `data/logs/server.log`, `worker_*.log` | text | logging |
| Things KURAMA made | `data/outputs/` | files | jobs, workspace |
| Your editable lists | `~/Documents/KURAMA/*.xlsx` | Excel | `sheets.py` |
| Secrets | `.env` | text | you |

Why SQLite: one file, no server, transactions, full-text search, crash-safe. Why Excel for your lists: you can fix
them by hand, so your data is never locked away.

---

## 13. Privacy and safety

- **The safety gate** (`safety.execute`): `blocked` never runs; `confirm` asks you (card / voice / Telegram);
  every call is logged.
- **Keys and passwords never reach the AI** (11-01: with `.env` open in VS Code, a "yes" was read as "use the
  highlight" and the reply printed the Groq key). `jarvis/tools/interactive/_secrets.py`:
  - `private_file(path)`: `.env`, `*.pem`, `*.key`, `id_rsa`, `credentials*`... are never "open" for KURAMA
    (`context.snapshot`);
  - `private(text)`: a highlight containing a key (Groq, OpenAI, Google, AWS, GitHub, Telegram tokens, `PASSWORD=`...)
    is invisible (`rewrite.peek`, `rewrite.grab` → "That's from a file with keys or passwords…");
  - a bare "yes"/"no" is never a selection or meaning action.
- **Passwords** in your messages are masked in traces (`trace.redact`); KURAMA's own password is only a hash in `.env`.
- **Gemini's free tier** may use prompts to improve Google's products; it is used only when Groq is used up.
- **Inside a plan, "close X"** closes only windows the plan opened (section 4.5).

---

## 14. Voice and the desktop

- **The desktop window** (`scripts/kurama_wallpaper.py`, system python3: GTK3 + WebKit2) shows `frontend/` as your
  wallpaper (`?wallpaper=1`) and a mini chat (`?mini=1`); hold-to-talk display; a hang guard writes stacks to
  `data/logs/hang.log` and restarts itself. `scripts/kurama_fm.py` reads the Files app (AT-SPI).
- **Power**: `scripts/kurama-power.sh on|off|status`.
- **Voice pipeline**: record (`voice.js`) → `/stt` → `/chat` (mode voice) → sentences → `/tts` → play; barge-in.
- **Talk mode**: speech long after KURAMA spoke is kept only if it names KURAMA, is a shortcut, or by meaning is a
  greeting or a clear request.
- **Keys**: hold Alt = talk (Alt+Shift cancels), Super+J = cursor to the chat box and back, Ctrl+Alt+K = mini chat.

---

## 15. Background work

- **Workers** (`jarvis/workers/`): tiny loops (`Worker.tick()` every ≥5 s) running as threads in the server:
  `scheduler`, `telegram_bot`, `resource_guard`, `process_watch`, `crash_watchdog`, `clipboard_watch`, `daily_digest`,
  `brief`, `timemachine`, `location_tracker`, `guard`.
- **Jobs** (`core/jobs.py`): long work (essay, video, scan, picture) in a thread pool; saved to `data/outputs/`;
  announced when done; the output becomes a thing in working memory. A tool still busy after 3 s moves to the
  background by itself (`safety._call_or_background`).
- **Follow-up jobs** (`agent.start_after_job` / `after_job`): the task-graph steps that need a job's output.
- **Job list** (`core/jobqueue.py`): things to do later; "start the jobs" runs them.
- **Rate limits** (`core/ratelimit.py`): jobs always yield to your requests.

---

## 16. Technologies: what each one is, where KURAMA uses it, what to learn

This is the list of everything you must know to understand KURAMA fully. If you can explain every row in your own
words and point at the file that uses it, you know the stack that real AI-product teams use.

**Levels:** ★ = learn it well (you need it daily), ◆ = understand the idea and read the KURAMA code, ○ = know what it
is and when you'd reach for it.

### 16.1 Language and core Python

| Technology | Level | Where in KURAMA | What to learn |
|---|---|---|---|
| **Python 3.12** | ★ | everything in `jarvis/` | functions, classes, dataclasses, type hints (`str \| None`), f-strings, comprehensions, `pathlib`, `re`, `json`, exceptions, context managers (`with`), decorators |
| **Decorators + registries** | ★ | `registry.py` `@tool(...)` | how a decorator records a function in a dict at import time; why "one tool = one file" works |
| **Threads, locks, events, queues** | ★ | `jobs.py` (thread pool), `workers/`, `learn.py` (one worker queue), `telegram_bot.py` (uploads beside the chat) | `threading.Thread/Lock/Event`, `queue.Queue`, `concurrent.futures`, race conditions, "never block the voice loop" |
| **asyncio** | ◆ | FastAPI routes, `run_in_threadpool`, edge-tts | event loop, `async/await`, why blocking code goes to a thread pool |
| **subprocess** | ★ | every laptop tool (`xdotool`, `pactl`, `fd`, `rg`), `tools/interactive/_proc.py` | `run` vs `Popen`, timeouts, never `shell=True` with user text, an allowlist |
| **Regex** | ★ | `fastpath.py`, `spelling.py`, `planner.py` | groups, named groups, lookahead, `re.I`, why regex is used only as a *candidate* and meaning decides |
| **Lazy imports + memory** | ◆ | `memory.py`, `semantic.py`, `send_file_telegram._small_photo` | import inside the function, unload when idle, measure RSS (`make rss`) |

### 16.2 AI and LLM engineering

| Technology | Level | Where | What to learn |
|---|---|---|---|
| **LLM APIs (chat completions, tool calling)** | ★ | `llm.py` | messages (system/user/assistant/tool), temperature, max tokens, JSON schema for tools, streaming tokens |
| **Groq** (gpt-oss-20b/120b, qwen, Whisper) | ★ | `llm.py`, `stt.py` | rate limits (tokens/min, requests/day), 429 + `Retry-After`, model tiers |
| **Gemini** (free fallback) | ○ | `llm.model_for()` | a second provider behind the same interface |
| **LangChain core** | ★ | `ChatGroq`, `@tool` schemas, `HumanMessage/AIMessage/ToolMessage` | Runnables, `bind_tools`, `invoke` vs `stream`, tool-call objects |
| **LangGraph** | ★ | `agent.py` `_build()` | `StateGraph`, nodes, edges, conditional edges, cycles (`llm ⇄ tools`), parallel fan-out with `Send`, state reducers |
| **Prompt engineering** | ★ | `agent.SYSTEM_PROMPT` (< 250 tokens), `_messages()` | short system prompt, give facts not prose, few tools, history trimming, rolling summary |
| **Agent patterns** | ★ | `planner.py`, `taskgraph.py` | ReAct loop, plan-and-execute, task DAG with `depends_on`, re-planning a failed step, "claimed but didn't do" checks (`meta.needs_tool`) |
| **Token economics** | ★ | section 11, `budget.py`, `ratelimit.py` | counting tokens, cutting them, caching, routing cheap → expensive |
| **Embeddings** (fastembed, `bge-small-en-v1.5`, ONNX Runtime) | ★ | `semantic.py`, `memory.py`, `recipes.py` | a sentence → 384 numbers; cosine similarity; thresholds and margins |
| **Semantic routing** | ★ | `router.py`, `semantic.scores()`, `fastpath.meaning_ok()` | pick tools by meaning, not keywords; learned examples; a gate that vetoes wrong shortcuts |
| **RAG (retrieval-augmented generation)** | ★ | `memory.py` | chunking, BM25 (FTS5) + vectors, **reciprocal rank fusion**, incremental indexing, citations |
| **Speech: STT, TTS, VAD, wake word** | ◆ | `stt.py` (Whisper), `tts.py` (edge-tts), `audio.py` (webrtcvad), `wake.py` | sample rate, PCM/WAV, voice activity detection, sentence-by-sentence TTS while the LLM streams, barge-in |
| **Evaluation** | ★ | `tests/eval/harness.py`, `tests/eval/cases.jsonl` | a fixed test set, scorecard metrics (instant %, right %, router %), never "it felt better" |
| **Learning from feedback** | ◆ | `learn.py`, `recipes.py`, `style.py`, `mywords.py` (read `docs/LEARNING.md`) | explicit feedback only (👍/👎, corrections), answer cache keyed by meaning, safe "unlearn" |

### 16.3 Backend, data and caching

| Technology | Level | Where | What to learn |
|---|---|---|---|
| **HTTP + REST** | ★ | `jarvis/api/` | methods, status codes, JSON bodies, headers, auth token |
| **FastAPI + Pydantic + uvicorn** | ★ | `api/app.py`, `api/routes/*.py` | routers, request models with validation, dependencies, OpenAPI docs at `/docs`, `run_in_threadpool` |
| **Server-Sent Events (SSE)** | ◆ | `/api/v1/chat`, `api/turns.py` | one-way streaming of events (`delta`, `tool`, `confirm`, `done`) |
| **SQLite** | ★ | `store.py` (`jarvis.db`), `trace.py` (`traces.db`), `memory.py` | SQL (SELECT/JOIN/GROUP BY/indexes), transactions, **WAL mode**, schema migrations (`store._migrate`), why one file beats a server for one user |
| **FTS5** | ◆ | `messages_fts`, `chunks_fts` | full-text search, BM25 ranking |
| **Caching** | ★ | weather/web (`WEATHER_CACHE_S`, `WEB_CACHE_S`), meaning vectors (`semantic_router.npz`), answer cache (`ANSWER_CACHE`, 👍 answers reused by meaning ≥ 0.95), `ASK_CACHE` | TTL caches, cache keys, invalidation ("cleared whenever the index changes"), semantic caching |
| **Rate limiting + backoff** | ★ | `ratelimit.py` (per-model token buckets), `llm._plan_retry`, `_cool` | token bucket, exponential backoff, circuit-breaker-style cooldown |
| **Background jobs** | ★ | `jobs.py`, `longjobs.py`, `jobqueue.py` | job states, persistence, resume after restart, "yield to interactive work" |
| **httpx** | ◆ | `notify.py`, `netdoctor.py` | clients, timeouts (connect/read/write), connection pools, streaming, multipart upload |
| **Telegram Bot API** | ◆ | `workers/telegram_bot.py`, `telesec.py` | long polling (`getUpdates`), sendPhoto/sendDocument, a PIN gate for risky commands |

### 16.4 Frontend and desktop

| Technology | Level | Where | What to learn |
|---|---|---|---|
| **HTML/CSS/JavaScript (ES modules)** | ★ | `frontend/` (`app.js`, `api.js`, `voice.js`) | DOM, events, `fetch`, `async/await`, modules, CSS variables, flex/grid |
| **Web Audio + MediaStream** | ◆ | `voice.js` `Mic`, `Recorder`, `Player` | `getUserMedia`, AudioContext, AudioWorklet, recording WAV in the browser |
| **GTK3 + WebKit2 (PyGObject)** | ○ | `scripts/kurama_wallpaper.py` | a native window hosting a web page, messages page ⇄ host (`hostSay`) |
| **Linux desktop (X11)** | ◆ | `xdotool`, `wmctrl`, `pactl`/PipeWire, `gsettings`, `brightnessctl`, AT-SPI | how the desktop is controlled from code; PipeWire modules (`devaudio.py`) |
| **systemd / autostart / signals** | ○ | `scripts/kurama-power.sh`, `ptt.py` (`SIGUSR2`) | processes, PIDs, signals, autostart |

### 16.5 Engineering practice (what makes it "industry level")

| Practice | Level | Where | What to learn |
|---|---|---|---|
| **Git** | ★ | the whole repo | small commits with clear messages, branches, `git log -p`, `git bisect` to find which commit broke something |
| **pytest** | ★ | `tests/` (~1,820 tests), `tests/conftest.py` | fixtures, `monkeypatch`, `tmp_path`, parametrize, mocking every network call |
| **Lint gate + pre-commit** | ◆ | `pyproject.toml`, `.pre-commit-config.yaml`, `make lint` | static checks that block commits; secrets never committed |
| **CI** | ◆ | `.github/workflows/ci.yml` | every push runs lint + tests on a clean machine |
| **Observability** | ★ | `trace.py` (one row per request), `store` logs of LLM/tool calls, `scripts/trace_report.py`, `MONITORING.md` | tracing, metrics, logs; debugging from evidence |
| **Safety by design** | ★ | `safety.py`, `telesec.py`, `_secrets.py` | one gate for every action, least privilege, confirm destructive actions, secrets never in prompts |
| **Configuration** | ★ | `config.py` + `.env` | one source of truth; secrets from the environment (12-factor) |
| **Resource budgets** | ◆ | `resource_guard` worker, CLAUDE.md budgets | idle RSS < 600 MB, lazy load, idle unload |
| **Type checking (mypy)** | ◆ | `make type`, `[tool.mypy]` in `pyproject.toml`, the `TYPED` list in `Makefile` | type hints, `Optional`, `TypedDict`, generics; a gate that covers a few modules and grows one module at a time |
| **Coverage** | ◆ | `make cov`, `fail_under` in `pyproject.toml` | line vs branch coverage; a floor that only goes up; coverage shows untested code, not good tests |
| **Metrics (Prometheus)** | ◆ | `core/metrics.py`, `/api/v1/metrics`, `make metrics` | counters vs gauges, labels, scraping, Grafana dashboards on top |
| **Typed results** | ◆ | `core/results.py` | return data, not sentences; keep the old contract while moving over (`Reply` is still a `str`) |
| **Refactoring safely** | ★ | ADR 0010 (the fastpath split) | move code without changing it, keep the old names importable, let the tests prove nothing changed |
| **ADRs** | ○ | `docs/adr/` | context → decision → consequences; never edit an old one, supersede it |

---

## 17. The dependency map

Arrows mean "imports / calls". Lower boxes never call upper ones.

```
frontend/app.js ──HTTP──► api/routes/chat.py ──► api/turns.py ──► core/agent.py
                                                                  │   │   │   │
        ┌─────────────────────────────────────────────────────────┘   │   │   └──► core/trace.py, core/learn.py
        ▼                                                             │   ▼
core/fastpath.py ──► slash.py              core/planner.py ◄──────────┤  core/taskgraph.py (steps)
        │ ──► semantic.py ◄── router.py ◄──────────────────────────────┤
        │        │               │                                     ▼
        │        ▼               ▼                               core/llm.py ──► ratelimit, budget, store
        │   memory.py      registry.py ──discover──► tools/core/* ──► tools/core/_hub.py
        │   (Embedder)           │                                         │
        ▼                        ▼                                         ▼
core/safety.py ◄──────────── every tool call ────────────────────► tools/general/*.py
   │        └──► core/workmem.py ◄── focus.py, fastpath, agent (things, choices)
   ▼                                                                       ▼
core/store.py (logs, kv)                              core/<feature>.py (links, todos, ytdl, cleanup...)
                                       core/config.py ◄──── everyone reads settings here
```

Rules of thumb:
- `config.py` depends on nothing; everything depends on it.
- `store.py`, `llm.py`, `safety.py`, `registry.py`, `workmem.py` are foundation: run the full test suite after
  touching them.
- A service in `core/<feature>.py` affects that feature only. Grep before changing:
  `grep -rn "links\." jarvis | head`.
- `fastpath.py` and `agent.py`: many features pass through them; small edits, many tests.

---

## 18. "I want to change X"

| I want to... | Change this | Check with |
|---|---|---|
| Change what the AI is told | `agent.py` `SYSTEM_PROMPT` (< 250 tokens: a test checks) | `pytest tests/test_p7c.py` |
| Use another model / order | `config.py` `LLM_*`, `TIER_CHAIN`, `MODEL_PARAMS`, `MODEL_LIMITS` | `pytest tests/test_llm.py tests/test_phase3.py`, live check |
| Fix "it used the wrong tool" | `config.ROUTER_EXAMPLES` / `TOOL_EXAMPLES`, or the tool's description in `tools/core/<tool>.py` | `python -m tests.eval.harness` |
| Make a frequent request 0 tokens | `config.MEANING_SHORTCUTS` + `fastpath.meaning_intent()`, or `slash.py` | scorecard "instant" % |
| Change a 0-token answer's wording | `fastpath.render()` / `templates.py` / `phrases.py` | tests for that intent |
| "it / that image" points at the wrong thing | `focus.refer()` order, `workmem.kind_named` nouns, `WORKMEM_FRESH_S` | `pytest tests/test_workmem.py` |
| A tool's file isn't remembered | make its result contain the full path (or note it with `workmem.note`) | `workmem.things()` after a call |
| "yes" goes to the wrong tools | `agent._open_question` (`_OFFER`, `QUESTION_TTL_S`) | `pytest tests/test_workmem.py -k offer` |
| Tasks split or linked wrongly | `planner.py` (`PLAN_PROMPT`, `_REF`, `split_clauses`), `FILLER_EXAMPLES` | `pytest tests/test_taskgraph.py tests/test_p7c.py` |
| Steps marked failed wrongly | `taskgraph.judge`, `workmem._FAILED` | `pytest tests/test_taskgraph.py` |
| Turn off the task graph | `config.TASK_GRAPH = False` (old chains) | restart |
| A short action should (not) skip the second AI call | `config.DIRECT_REPLY_SINGLE`, `DIRECT_REPLY_STEPS`, `DIRECT_REPLY_MAX_WORDS` | `pytest tests/test_phase3.py` |
| Change when it asks yes/no | the tool's `safety=`, or `safety.ask()` inside it | its test |
| Treat another file type as private | `_secrets._PRIVATE_SUFFIX` / `_PRIVATE_NAMES` | `pytest tests/test_privacy_guard.py` |
| Change thresholds | `config.py` (each value has a comment) | related tests + scorecard |
| Change the UI | `frontend/app.js`, `index.html`, `styles.css`; the window in `scripts/kurama_wallpaper.py` | reload the page |
| Add a slash command | `slash.py` `COMMANDS` | `pytest tests/test_slash.py` |
| Add a background loop | `workers/<name>.py` (subclass `Worker`) + `config.WORKERS_ENABLED` | its log |

---

## 19. Debugging

### 19.1 The method (use it every time)

1. **Find the evidence.** Don't guess. Find the trace of the bad request.
2. **Locate the step.** Shortcut (path `fastpath`)? Plan (the `plan` column: method, steps)? Router (wrong
   `route_groups` / `tools_sent`)? The AI (wrong tool, no tool)? The tool (`result` says error)? Memory (the wrong
   "it")? The model chain (`llm`: which models failed)? The UI?
3. **Prove the cause.** Re-run that one step alone (snippets below) until you can say "this line, with this
   input, produces this wrong output".
4. **Fix the class, not the sentence.** Fix it for every phrasing and every tool of that kind.
5. **Test with your real way of typing** (typos, "bro", "..", Nepali/Hindi), then the scorecard, then live.

### 19.2 The toolkit

```bash
cd /media/leo/Project1/New_project/KURAMA

# what went wrong lately (traces + side logs + steps + models)
venv/bin/python scripts/trace_report.py --days 3
venv/bin/python scripts/trace_report.py --show 3fa9c1          # one request in full

# ask the running KURAMA (same path as the UI; the answer streams)
curl -sN -X POST http://127.0.0.1:8000/api/v1/chat -H 'Content-Type: application/json' -d '{"text":"show me link stroe"}'

# which shortcut would take a sentence? (0 tokens; uses the real meaning model)
venv/bin/python -c "
from jarvis.core import registry, semantic, fastpath as f; registry.REGISTRY._ensure(); semantic.ensure_ready()
i=f.match('send hello to telegram'); print(i and (i.tool, i.args))"

# how would a multi-task request be planned? (rules/learned = 0 tokens; llm = one AI call)
venv/bin/python -c "
from jarvis.core import registry, semantic, planner; registry.REGISTRY._ensure(); semantic.ensure_ready()
p=planner.plan('create a folder test in downloads and open it in vs code'); print(p.method, p.tasks)"

# what is in working memory right now? (the running KURAMA's things and waiting choice)
venv/bin/python -c "
from jarvis.core import workmem; print(workmem.things()[:5]); print(workmem.choice()); print(workmem.line())"

# which areas/tools would the AI get?
venv/bin/python -c "
from jarvis.core import registry, router, semantic; registry.REGISTRY._ensure(); semantic.ensure_ready()
r=router.route('remove sofascore from link store', log_it=False); print(r.groups, [t.name for t in registry.REGISTRY.schemas_for(r.groups)])"

# was a model skipped for its limit? / did Gemini answer?
grep -h "rate-limited: skipped\|falling back" data/logs/server.log | tail

# the terminal chat (no UI)
venv/bin/python -m jarvis

# tests and the scorecard
venv/bin/python -m pytest -q tests/test_taskgraph.py          # one file
venv/bin/python -m pytest -q                                   # all (~3.5 min)
venv/bin/python -m tests.eval.harness                          # must stay >= 65% instant / 100% right / 98% router

# restart KURAMA after a code change
scripts/kurama-power.sh off; scripts/kurama-power.sh on
```

### 19.3 Reading a trace

`--show <id>` prints: `text`, `path` (fastpath / ai / multi), `route_method` + `route_groups`, `tools_sent`,
`tools` (what ran, with arguments and the first 300 characters of the result), `plan` (method, tasks, **steps**
like `1:ok 2:skipped`, **replanned**), `llm` (each AI call: model, purpose, tokens, ms, error), `retried`, `asked` /
`denied`, `answer`, `ms`, `error`. Typical readings:

| You see | It means |
|---|---|
| `path: ai`, `tools: []`, answer says "Done" | the AI claimed without acting (the safety nets should have caught it: check `meta.claims`) |
| the right tool missing from `tools_sent` | routing (section 9) |
| the right tool ran, `result` starts with "error" | the tool / service |
| `route_method: answer` with odd tools | KURAMA's question was routed (section 3.4): was the question really about that? |
| `plan.steps` has `failed` but the tool worked | the tool answered "error"-like text, or `judge` is too strict |
| `plan.steps` has `skipped` | a step it needed failed: look at that step first |
| `plan.method: llm` for a simple two-part request | a part had no shortcut; making it one makes the whole plan 0 tokens |
| `llm` entries with gemini or qwen | Groq's gpt-oss limit was used up that day |
| `intent: choice` | a reply picked from a list |
| `route_method: rules` | the meaning model wasn't loaded |

---

## 20. Monitoring and improving it yourself

You don't need anyone to keep KURAMA healthy. Here is the routine. MONITORING.md has the detailed tables.

### 20.1 Every 2–3 days (15 minutes)

1. `venv/bin/python scripts/trace_report.py --days 3`
2. Read these sections first, in this order:
   - **Likely mistakes** (you corrected KURAMA right after): the most valuable rows.
   - **AI answered a command without any tool** and **Retried**: honesty problems.
   - **Multi-step requests with a failed / skipped / waiting step**: task-graph problems.
   - **Short replies routed by KURAMA's own question**: did "yes" get the right tools?
   - **Failed tool calls**: tool bugs.
   - **Models**: gemini/qwen lines mean Groq's daily limit was hit; how many failed?
   - **Most tokens** and **Asked the AI most often**: what to make cheaper.
   - The side logs: speech drops, wake misses, hold-to-talk, window freezes.
3. For each problem: `--show <id>`, then section 19.1 (locate → prove → fix the class).

### 20.2 Deciding what to fix

| Symptom (how often) | First thing to try |
|---|---|
| Same request goes to the AI many times | a meaning shortcut (`MEANING_SHORTCUTS`) or a slash command |
| Wrong tool offered | more meaning examples for the right area (`ROUTER_EXAMPLES` / `TOOL_EXAMPLES`) |
| Right tool, wrong action / argument | the general tool's description in `tools/core/<tool>.py` |
| "it / this" wrong | `focus.refer` order; the tool's result missing the full path |
| Steps linked wrongly | `PLAN_PROMPT`, `_REF`, `FILLER_EXAMPLES` |
| A fake "done" | `meta.claims` patterns (add the new grammar, with a test that it is NOT matched in normal answers) |
| Too many tokens | `DIRECT_REPLY_SINGLE`, a shortcut, fewer history turns (`HISTORY_TURNS`) |

### 20.3 After a fix

1. A test with 3+ phrasings, the way you really type.
2. `venv/bin/python -m pytest -q` (all green) and `venv/bin/python -m tests.eval.harness` (≥65% / 100% / 98%).
3. Add the phrasings to `tests/eval/cases.jsonl` if they are about routing or shortcuts.
4. Restart, one live check with `curl`.
5. `scripts/trace_report.py --mark-fixed`, a line in `PROGRESS.md` and in MONITORING.md's Fix history, commit.

### 20.4 Health numbers to keep an eye on

| Number | Where | Healthy |
|---|---|---|
| Instant shortcuts | scorecard | ≥ 65% (68% on 11-01) |
| Router right | scorecard | ≥ 98% |
| Tokens per AI request | report header | falling over time (2,175 on 11-01) |
| AI calls per AI request | report "Most tokens" | close to 1 for simple actions |
| Core RAM | `data/logs/worker_resource_guard.log` | ~390 MB with the meaning model, ~140 MB without |
| Groq daily use | report "Models" | gemini/qwen lines = the limit was hit |

---

## 21. How to learn it: a day-by-day plan (1–2 hours a day)

**12 weeks, about 1.5 hours a day.** Each day has one thing to *read* and one thing to *do*. If a day takes longer,
move on anyway and come back at the weekend. Day 7 of every week is for review: re-explain the week out loud, as if
teaching someone, and write what you still don't get in a `NOTES.md` of your own.

**Rule for every day:** keep KURAMA running, open the files beside this guide, and predict before you check ("this
sentence will go to the fast path, tool X"), then check with the snippets in 19.2.

### Week 1: Python as KURAMA uses it
| Day | Read / learn | Do |
|---|---|---|
| 1 | Sections 1–2 of this guide. `CLAUDE.md`. | Draw the life of one request on paper from memory. |
| 2 | Python: functions, dataclasses, type hints, `pathlib`. Read `core/paths.py`. | Write a function that lists the 5 biggest files in a folder (with a test). |
| 3 | Decorators. Read `core/registry.py` `tool()`. | Write your own `@register` decorator that fills a dict. |
| 4 | Regex. Read `core/spelling.py` (small) and one area of the fast path (`core/intents/files.py`, `findfile_intent`). | Add a typo fix to `spelling.py` + test. |
| 5 | Exceptions + context managers. Read `core/safety.py` `execute()`. | Trace a tool call through the gate with a print. |
| 6 | `subprocess`. Read `tools/interactive/_proc.py`. | Write a tool helper that runs `uptime` with a timeout. |
| 7 | Review. | Explain the safety gate out loud. |

### Week 2: concurrency and the laptop
| Day | Read / learn | Do |
|---|---|---|
| 8 | Threads, locks, events. Read `core/jobs.py` (the manager). | Start a fake job that sleeps 10 s; watch it in the UI. |
| 9 | Queues. Read `learn.py` (the single worker queue). | Write a producer/consumer with `queue.Queue`. |
| 10 | `asyncio` basics; why FastAPI uses a thread pool. | Write an async function that fetches two URLs at once with httpx. |
| 11 | Workers. Read `workers/base.py` and `workers/resource_guard.py`. | Exercise 11 in 21.3: a worker logging battery every 10 min. |
| 12 | X11 tools: `xdotool`, `wmctrl`, `pactl`. Read `tools/general/_apps.py` `open_verified`. | Use each CLI by hand in a terminal. |
| 13 | Memory budgets. Read the lazy-load notes in `memory.py`'s docstring. | Run `make rss` before and after a search; explain the difference. |
| 14 | Review. | — |

### Week 3: HTTP, FastAPI, streaming
| Day | Read / learn | Do |
|---|---|---|
| 15 | HTTP: methods, status codes, headers, JSON. | Use `curl` against `http://127.0.0.1:8000/api/v1/health`. |
| 16 | FastAPI + Pydantic tutorial (official docs, first chapters). Read `api/app.py`. | Open `/docs` and call 3 endpoints from the page. |
| 17 | Read `api/routes/chat.py` and `api/turns.py` `run_turn()`. | Add a tiny endpoint `GET /api/v1/ping` + test. |
| 18 | Server-Sent Events. | Stream a chat reply with `curl -N` and read the events. |
| 19 | httpx: timeouts, pools, multipart. Read `core/notify.py` `telegram_call`, `_upload`. | Explain why uploads use a fresh connection (11-04 bug). |
| 20 | Telegram Bot API. Read `workers/telegram_bot.py` (`poll`, `_answer`, `_upload_in_background`). | Add a slash command `/uptime`. |
| 21 | Review. | — |

### Week 4: SQL, SQLite, caching
| Day | Read / learn | Do |
|---|---|---|
| 22 | SQL basics: SELECT, WHERE, GROUP BY, JOIN, indexes (SQLBolt or similar). | Open `data/traces.db` with Python's `sqlite3`; count requests per path. |
| 23 | Transactions and WAL. Read `core/store.py` `init()` and `_migrate()`. | Add a column in a migration on a copy of the DB. |
| 24 | FTS5 and BM25. | Search `messages_fts` for a word you said yesterday. |
| 25 | Caching: TTL, keys, invalidation. Find `WEATHER_CACHE_S`, `WEB_CACHE_S` users. | Write a `@ttl_cache(seconds)` decorator + test. |
| 26 | Semantic answer cache. Read `recipes.py` (kept answers) + `docs/LEARNING.md` §1–6. | Ask a question, 👍 it, ask it again: check the trace says 0 tokens. |
| 27 | Rate limits. Read `core/ratelimit.py`. | Explain a token bucket with numbers on paper. |
| 28 | Review. | — |

### Week 5: LLMs and LangChain
| Day | Read / learn | Do |
|---|---|---|
| 29 | How chat LLMs work: tokens, context, temperature, tool calling (Groq docs). | Call Groq directly with `ChatGroq` in a 10-line script. |
| 30 | LangChain messages and tools. Read `registry.py` schemas. | Bind one tool to `ChatGroq`; print the tool call it returns. |
| 31 | Read `core/llm.py` `chat()`, `_chain()`, `_on_error()`. | Explain what happens on a 429 with and without `Retry-After`. |
| 32 | Prompt design. Read `agent.SYSTEM_PROMPT` and `_messages()`. | Count the tokens of one real prompt from a trace. |
| 33 | Token economics. Section 11. | Find the most expensive request this week in `make report`. |
| 34 | Model tiers and fallbacks. `config.TIER_CHAIN`. | Predict which model answers a voice chat; check the trace. |
| 35 | Review. | — |

### Week 6: LangGraph and agents
| Day | Read / learn | Do |
|---|---|---|
| 36 | LangGraph quickstart (official docs): StateGraph, nodes, edges. | Build a 3-node toy graph. |
| 37 | Conditional edges and cycles. Read `agent._build()`. | Add a cycle to your toy graph (a tool loop). |
| 38 | Parallel fan-out with `Send`. Read section 4 of this guide. | Make your toy graph run 3 steps in parallel. |
| 39 | Read `agent._route_node`, `_llm_node`, `_tools_node`. | Follow one AI request in a trace, step by step. |
| 40 | Planning. Read `planner.plan()`, `add_dependencies`, `merge_tails`. | Exercise 4 in 21.3 (predict 5 plans). |
| 41 | Task graph. Read `taskgraph.py`, `agent._step_node`, `_finish_node`. | Run a 3-part request with one dependency; read its plan in the trace. |
| 42 | Review. | — |

### Week 7: embeddings, routing, RAG
| Day | Read / learn | Do |
|---|---|---|
| 43 | Embeddings and cosine similarity (any good intro). | Embed 5 sentences with fastembed; print the similarity matrix. |
| 44 | Read `semantic.py` `scores()`, `best_of()`. | Predict the area of 10 sentences; check (19.2 snippet). |
| 45 | Read `router.py` and `registry.schemas_for()`, `reach()`. | Exercise 2 in 21.3. |
| 46 | The meaning gate. Read `fastpath.match()`, `meaning_ok()`. | Find a sentence the gate vetoes; explain why. |
| 47 | RAG. Read `memory.py` docstring, `search()`, the RRF function. | Index a folder of your notes; search it. |
| 48 | Evaluation. Read `tests/eval/harness.py`. | Run `make eval`; add 3 cases of your own. |
| 49 | Review. | — |

### Week 8: KURAMA's own systems
| Day | Read / learn | Do |
|---|---|---|
| 50 | Working memory. Section 3; `workmem.py`. | Exercise 3 in 21.3. |
| 51 | Choices. `workmem.choose()`, `act_on()`. | Find something, then "open 2 in vs code"; read the trace. |
| 52 | Learning. `docs/LEARNING.md` §7–19; `learn.py` `_judge`. | Teach "when I say X, do Y"; then forget it. |
| 53 | Recipes. `recipes.py` `observe`, `feedback`. | 👎 a reply and read what was stored. |
| 54 | Safety. Section 13; `telesec.py`. | Explain which Telegram commands ask for the PIN and why. |
| 55 | Background jobs end to end: `generate_image.py` → `jobs.then_send` → `send_output`. | Make an image and send it; find each step in the logs. |
| 56 | Review. | — |

### Week 9: voice and audio
| Day | Read / learn | Do |
|---|---|---|
| 57 | Digital audio: sample rate, PCM, WAV. Read `audio.py` top. | Record 3 s with `sounddevice`; save a WAV. |
| 58 | VAD. Read `audio.Endpointer`. | Print speech/non-speech per frame for your recording. |
| 59 | STT. Read `stt.py` (Whisper, `heard_well`). | Transcribe your WAV via the API route. |
| 60 | TTS. Read `tts.py` and how sentences are spoken while the LLM streams. | Speak a sentence with edge-tts in 5 lines. |
| 61 | Hold-to-talk path: `ptt.py` → `kurama_wallpaper.py` `ptt()` → `app.js` `kuramaPTT`. | Hold Alt and follow `data/logs/ptt.log` line by line. |
| 62 | PipeWire + echo cancel. Read `devaudio.py`. | `pactl list short sinks/sources` and explain each line. |
| 63 | Review. | — |

### Week 10: frontend
| Day | Read / learn | Do |
|---|---|---|
| 64 | Modern JS: modules, `fetch`, `async/await`, DOM events (MDN). | Read `frontend/api.js` whole. |
| 65 | Read `app.js` `sendChat()` and how SSE events draw a bubble. | Add a small UI change (a timestamp on messages). |
| 66 | Web Audio. Read `voice.js` `Mic`, `Recorder`. | Explain the `system: false` change of 11-04. |
| 67 | CSS: variables, flex, grid. Read `styles.css` top. | Change the theme colour in one place. |
| 68 | The music card and workspace in `app.js`. | Add a "+10 s" button to the music card. |
| 69 | The desktop host: `kurama_wallpaper.py` `on_page`, `show_panel`, `_mark_ready`. | Explain why the panel now waits for the page's "ready". |
| 70 | Review. | — |

### Week 11: testing, debugging, observability
| Day | Read / learn | Do |
|---|---|---|
| 71 | pytest: fixtures, monkeypatch, tmp_path, parametrize. Read `tests/conftest.py`. | Write a parametrized test for `spelling.fix`. |
| 72 | Mocking network. Read a Telegram test. | Test your `/uptime` command with a fake. |
| 73 | Traces. Section 19.3; `trace.py`. | `make report`; pick one failure and find its cause. |
| 74 | Debugging method (19.1). | Exercise 10 in 21.3: fix a real bug with a test that fails first. |
| 75 | Git deeper: `log -p`, `blame`, `bisect`. | Use `git log -S "act_on"` to find when choices changed. |
| 76 | Lint gate, pre-commit, CI: `pyproject.toml`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`. | Install pre-commit; make a commit pass the hooks. |
| 77 | Review. | — |

### Week 12: industry level, by doing it
| Day | Read / learn | Do |
|---|---|---|
| 78 | Sections 23 and 23.3; ADR 0009 and `core/results.py`. | Make `list_folder` return a `Reply(text, paths=[...])` like `find_files` + a test. |
| 79 | Section 8.4 and ADR 0011 (plug-ins). | `make new-memory NAME=habits_log`: make it search your habits; check `recall` finds one. Delete it after. |
| 80 | Type checking: mypy basics. | Add `core/intents/todo.py` to `TYPED` in the Makefile; fix what `make type` finds. |
| 81 | Coverage. | `make cov`; open `data/coverage/index.html`; write one test for the least-covered core file you use daily. |
| 82 | Metrics: Prometheus text format. | `make metrics`; add one metric (e.g. errors in the last 24 h) to `core/metrics.py` + the test in `test_api.py`. |
| 83 | ADRs. | Read `docs/adr/`; write ADR 0011 for a choice you make yourself. |
| 84 | Final review. | Explain KURAMA end to end in 15 minutes, without notes. |

**After week 12** you can explain, change and debug every part. Then keep the routine of section 20 (15 minutes
every 2–3 days) and work through section 23.2 one item at a time.

### 21.3 Practice exercises (in order; each with a test you write)

1. **Read a trace.** Pick one "Likely mistake", `--show` it, say at which step it went wrong.
2. **Predict routing** for 10 sentences the way you speak; check with the router snippet.
3. **Watch working memory.** Ask KURAMA to find a file, then run the workmem snippet: is it there? Then say "open
   it in vs code" and check which path ran in the trace.
4. **Predict a plan.** Write 5 multi-task sentences; predict method, steps and links; check with the plan snippet.
5. **Change a template** in `fastpath.render()`; run its test; see it live.
6. **Add meaning examples** for a request that often goes to the AI; run the scorecard.
7. **Add a slash command** `/ip` that answers your local IP.
8. **Add a small tool** "how many files are in this folder" (service + tool + `files` TABLE action + test + put it
   in `DIRECT_REPLY_SINGLE`).
9. **Add a filler example** you often say ("chal na", "suna"), with a test that `taskgraph.filler` drops it and
   doesn't drop a real request.
10. **Fix a real bug from a trace** with the method in 19.1, with a test that fails before your fix.
11. **Add a worker** that logs your battery % every 10 minutes.
12. **Draw the flow** of one big feature (music, downloads, reminders) on paper.

### 21.4 How to read a big file without drowning

- Read the module docstring first (most files explain themselves at the top).
- List the functions: `grep -n "^def \|^class \|    def " jarvis/core/agent.py`.
- Follow one call from the entry point; ignore everything else for now.
- Use the tests as examples: `grep -rn "workmem\." tests | head` shows how a module is called.

---

## 22. Lessons for any big project

1. **Layers with one-way dependencies.** You can test, replace or run any layer alone.
2. **A single source of truth for settings**, with a comment on *why* each value is what it is.
3. **Contracts for extension points.** Every tool has the same shape, so the 151st is as easy as the first.
4. **Cheapest path first**, and measure how often each path is used.
5. **Observability from day one.** A bug you can't see is a bug you guess at.
6. **Fix classes, not instances.** One special case per complaint turns into thousands of fragile rules.
7. **Safety by default.** One gate, deny when unsure, ask for anything destructive, never read secrets.
8. **Remember facts, not prose.** Store what really happened (paths, ids, statuses) as data; give the AI those
   facts instead of hoping it remembers sentences.
9. **Plan, then execute small checked steps.** Pass real outputs between steps; check each one; skip honestly.
10. **Resource frugality.** Lazy imports, idle unloading, one process where possible. Measure memory.
11. **Tests at several levels**, written with real users' messy input.
12. **Graceful degradation.** A fallback for every outside dependency (models, network, the meaning model).
13. **Write it down.** A diary (`PROGRESS.md`), a fix history (`MONITORING.md`) and a map (this file).

---

## 23. Industry level: where KURAMA stands, and what is left

"Industry level" does **not** mean using the biggest tools. It means choosing the right tool for the load,
measuring the result, testing the code, and being able to change any part safely. For **one user on an 8 GB laptop**,
a big company would choose most of what KURAMA already uses (SQLite, not Postgres; an in-process cache, not Redis;
one process, not Kubernetes). Learn the server-scale version too, so you know why it is *not* used here:

| Concern | KURAMA (right for one laptop) | Server-scale equivalent (learn the idea) |
|---|---|---|
| Database | SQLite in WAL mode, migrations in `store._migrate` | PostgreSQL + Alembic migrations |
| Search / retrieval | FTS5 BM25 + vectors fused with RRF (`memory.py`) | Elasticsearch/OpenSearch + pgvector/Qdrant, same hybrid idea |
| Cache | TTL caches in memory/SQLite, semantic answer cache | Redis with TTLs; semantic cache (e.g. GPTCache) |
| Jobs | thread pool + SQLite job table, resume after restart | Celery/RQ/Arq with Redis, or a durable workflow engine (Temporal) |
| Rate limits | per-model token bucket + cooldown | API gateway limits, circuit breakers |
| Agent | LangGraph graph with a task DAG | the same (LangGraph is used in production) + LangSmith tracing |
| Observability | `traces.db`, per-call logs, trace report | OpenTelemetry traces + Prometheus metrics + Grafana dashboards |
| API | FastAPI + Pydantic + SSE | the same, behind nginx, with auth |
| Quality gates | pytest + scorecard + lint gate + CI | the same, plus coverage thresholds and type checking |
| Deploy | a power script on one laptop | Docker images, CI/CD, staging → production |

### 23.1 Already at industry level

- A real **agent architecture**: routing by meaning → planning → a task graph with dependencies → one safety gate → tracing.
- **Hybrid RAG** (BM25 + vectors + rank fusion) with incremental indexing and lazy, unloadable embeddings.
- **Cost engineering**: two of every three requests cost 0 tokens; model fallback chains; rate limiting; caches.
- **Observability**: every request is a trace with route, tools, tokens and latency; a report finds the failures;
  `/api/v1/metrics` exposes the same numbers in Prometheus format for any dashboard.
- **Tests**: ~1,830 offline tests plus an evaluation scorecard; mocked network; a **coverage floor** (`make cov`).
- **Safety**: confirm levels, a PIN for risky remote commands, secrets kept out of prompts and git.
- **Quality gates** (`make check`, also in CI): lint gate (syntax, undefined names, duplicate definitions, unused
  results, closures over loop variables), **type gate** (`make type`), frontend parse check (`make js-check`), tests,
  scorecard. Pre-commit hooks block `.env` and private keys.
- **Code layout**: the fast path is split by area (`core/intents/`); tools can return **typed results** (`Reply`).
- **Plug-in architecture** (section 8.4): tools, memory sources and agents are added as files, found by
  themselves, isolated when broken and checked by contract tests; a scaffold writes each one.
- **Self-knowledge** (section 8.5): cards built from the code, explanations grounded in the real trace, a safe
  settings list changed by voice, help by meaning.
- **Decisions are written down**: `docs/adr/` (10 records).

### 23.2 What is left (smaller now, in the order to do it)

1. **`config.py` (~1,430 lines)**: move the long example and word lists into data files under `jarvis/core/data/`
   and keep only settings in `config.py`.
2. **`frontend/app.js` (~3,000 lines)**: split into ES modules (chat, voice, music card, workspace); no build step
   needed (ADR 0008). Add `// @ts-check` to each new module.
3. **More typed results**: every tool that lists things (`list_folder`, `recent_files`, links, to-dos) returns a
   `Reply` with its items; then `workmem` can drop the text parsing.
4. **Widen the type gate**: add one module at a time to `TYPED` in the `Makefile` (next: `intents/todo.py`,
   `intents/media.py`, `store.py`, `memory.py`); each needs a few `Optional` checks.
5. **Widen the lint gate**: unused imports (F401, ~47) need care because tests patch module attributes; then
   `E7`, then `B` rules, one folder at a time.
6. **End-to-end UI tests** (Playwright) for the chat and the mini window, run by hand (too heavy to run all day).
7. **Push to GitHub** so CI runs on every change (it has never run there yet).

Each item is one phase: do it, measure, test, commit, update this list.

### 23.3 How large production codebases work (and how KURAMA maps to it)

What teams of 10–1,000 engineers do so that a big codebase keeps working while many people change it every day.
You don't need all of it for a one-person project, but you should know each one, why it exists, and its small
version, because interviews and real jobs assume it.

| Practice | What it is, why it exists | In KURAMA |
|---|---|---|
| **Version control flow** | Short-lived branches, a pull request (PR) per change, `main` always releasable ("trunk-based development") | Git with small commits; try a branch + PR on GitHub for your next change |
| **Code review** | Every change is read by someone else before it merges; catches bugs and spreads knowledge | `/code-review` in Claude Code, or review your own diff the next day |
| **CI (continuous integration)** | Every push runs lint, types and tests on a clean machine; red CI blocks the merge | `.github/workflows/ci.yml` (not pushed yet) |
| **CD (continuous delivery)** | A merge to `main` builds and deploys automatically, first to staging, then production | `make restart` is the one-laptop version |
| **Environments** | dev → staging → production, each with its own config and data | `.env` + `config.py`; tests use a temp database (`tests/conftest.py`) |
| **Testing pyramid** | Many fast unit tests, fewer integration tests, a few end-to-end tests; plus contract, load and regression tests | ~1,830 unit/integration tests + `tests/eval` regression scorecard; no e2e yet |
| **Static analysis** | Linters and type checkers catch bugs before running the code | `make lint`, `make type` |
| **Coverage floor** | Coverage may not go down; new code comes with tests | `fail_under` in `pyproject.toml` |
| **Dependency management** | Pinned versions, lock files, automatic security updates (Dependabot), audits (`pip-audit`) | `requirements*.txt` pinned; run `pip-audit` now and then |
| **Secrets management** | Secrets in a vault (AWS Secrets Manager, Vault), never in code, rotated | `.env` only, pre-commit blocks it, `_secrets.py` keeps keys out of prompts |
| **Configuration** | Settings from the environment (12-factor), feature flags to turn features on without a deploy | `config.py` reads env vars; flags like `FASTPATH`, `WORKERS_IN_SERVER` |
| **Observability** | Logs (what happened), metrics (how much, how fast), traces (one request end to end), dashboards and alerts | logs, `traces.db`, `/api/v1/metrics`, `scripts/trace_report.py` |
| **SLOs and alerting** | A target ("95% of replies under 2 s") and an alert when it is missed; on-call engineers respond | budgets in CLAUDE.md; `resource_guard` and notifications |
| **Incidents and postmortems** | After an outage: a blameless write-up of cause, fix and prevention | `PROGRESS.md` and `MONITORING.md` fix history do this |
| **Resilience** | Timeouts, retries with backoff, circuit breakers, fallbacks, idempotent jobs | Groq backoff + model fallback, upload deadlines, resumable jobs |
| **Caching layers** | Browser → CDN → app cache (Redis) → database; every cache has a TTL and an invalidation rule | TTL caches for weather/web/answers (ADR 0007) |
| **Queues and workers** | Slow work goes to a queue (Kafka, RabbitMQ, SQS, Celery) so requests stay fast | SQLite job queue + background jobs |
| **Database migrations** | Every schema change is a versioned, reversible script (Alembic, Flyway) | `store._migrate` |
| **Backups and recovery** | Scheduled backups and a tested restore | one file (`data/`) to copy; KURAMA's reset keeps a backup |
| **API design** | Versioned URLs (`/api/v1`), schemas (OpenAPI), auth, rate limits, pagination | FastAPI `/api/v1`, OpenAPI at `/docs`, bearer token |
| **Containers and infrastructure as code** | Docker images run the same everywhere; Terraform describes servers | not needed on one laptop; learn Docker next |
| **Code ownership and modules** | Clear module boundaries, an owner per area (`CODEOWNERS`), no 5,000-line files | `core/intents/` split, one tool = one file |
| **Plug-in architecture** | Extension points with small contracts; new features plug in instead of editing old code; one failing plug-in is isolated | tools, `memories/`, `agents/` via `core/plugins.py` (section 8.4) |
| **Documentation** | README to start, ADRs for decisions, runbooks for "when X breaks, do Y", docs next to the code | README, LEARN.md, MONITORING.md, `docs/adr/` |
| **Versioning and changelog** | Semantic versioning (MAJOR.MINOR.PATCH) and a changelog per release | `version` in `pyproject.toml`; PROGRESS.md is the changelog |
| **Security practice** | Least privilege, input validation, threat modelling, dependency scanning, security review | the safety gate, confirm levels, PINs, shell allowlist |
| **Performance budgets** | Limits on latency, memory and bundle size, checked in CI | idle RSS < 600 MB, token budgets; `make rss` |

**How to use this table:** pick one row a week that KURAMA does not have yet (e2e tests, `pip-audit`, Docker, a
Grafana dashboard on `/metrics`), learn it with a 30-minute tutorial, then try its small version on KURAMA.

### 23.4 Smaller known weak spots

- **Reference words.** "it / that image / the essay" are matched with small noun lists (`workmem._NOUNS`,
  `focus.is_anaphora`). They only pick *which* remembered thing, never the action, but they can miss a new noun.
- **Dependency detection** in a rules plan uses reference words (`planner._REF`); the AI plan uses `depends_on`. A
  missed link makes two steps run at once.
- **Step checks can't see everything.** A file or folder can be checked; "an app opened" or "a message sent" relies
  on the tool's own report. If KURAMA restarts in the middle of a plan, the remaining steps are lost (follow-up jobs
  do survive).
- **Learned plans** could be reused for a request that only looks similar (threshold 0.93, same number of parts).
  Delete rows from `data/learned_plans.json` if one misbehaves.
- **Direct replies** end a short request after one action; a short request that needed two actions in one AI turn
  ends early. Watch for it in the traces.
- **The AI sometimes ignores its tools.** The safety nets catch most; more meaning shortcuts are the long-term fix.
- **The package name `jarvis/`** stays to avoid a risky rename.

---

## 24. Glossary

| Word | Meaning here |
|---|---|
| **Area / group** | A family of tools ("links", "files", "audio"). The router picks areas. |
| **General tool** | One of the 17 broad tools the AI sees (`tools/core/`), with an `action` argument. |
| **Real tool** | A tool that does the work (`tools/general/`). |
| **Shortcut / fast path** | A request answered without the AI (0 tokens). |
| **Meaning / semantic / embedding** | A sentence as a vector, so similar meanings are close; done locally. |
| **Meaning gate** | A shortcut runs only if the sentence's meaning agrees with its area. |
| **Working memory** | `workmem.py`: the real files/folders/images this conversation touched or made. |
| **Thing** | One entry of working memory: path, kind, which tool, when. |
| **Choice** | A numbered list of real paths KURAMA just showed; "2" picks one (0 tokens). |
| **Open question** | KURAMA's newest message, if it asked or offered something in the last 10 minutes. |
| **Tool line** | `[tools this turn: …]` added to a reply in the AI's history. |
| **Plan** | The steps of a multi-task request and their links (`depends_on`). Method: rules, learned or llm. |
| **Step** | One task in the task graph; status ok / failed / skipped / waiting / after. |
| **Filler** | A part of a request that asks for nothing ("let's work ..."); dropped by meaning. |
| **Re-plan** | One small AI call that corrects a failed step. |
| **Follow-up job** | Steps that wait for a background job's output, run when it is done. |
| **Direct reply** | The tool's own sentence used as the answer (no second AI call). |
| **Tier** | Which model chain: fast, smart, voice, vision, writer. |
| **Cooldown** | A model that hit its limit is skipped for a while (`llm._cool`). |
| **Token** | The AI's unit of text (≈ ¾ of a word); free tiers limit tokens per minute and per day. |
| **Trace** | One saved row per request, with everything that happened. |
| **Scorecard** | `tests/eval/harness.py`: instant %, right %, router %. |
| **SSE** | Server-Sent Events: the reply streamed piece by piece. |
| **Worker** | A small background loop inside the server. |
| **Job** | A long task in the background, announced when done. |
| **Confirm** | A tool that needs your yes before it runs. |
| **Private file** | A file with keys or passwords (`.env`...); KURAMA never reads it into a prompt. |
