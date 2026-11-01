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

> Names and line counts below are from 2026-11-01 (after the memory + multitasking rebuild). Files grow; if a name
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
8. [Tools: the two layers, the contract, how to add one](#8-tools)
9. [How KURAMA understands a request (routing in depth)](#9-how-kurama-understands-a-request)
10. [The AI models: tiers, fallbacks, limits](#10-the-ai-models)
11. [Tokens: where they go and how they are cut](#11-tokens)
12. [Long-term memory, data and where everything is stored](#12-long-term-memory-data-and-storage)
13. [Privacy and safety](#13-privacy-and-safety)
14. [Voice, wake word, hold-to-talk, the desktop window](#14-voice-and-the-desktop)
15. [Background work: workers, jobs, the job list](#15-background-work)
16. [Technologies, and why each one was chosen](#16-technologies-and-why)
17. [Who depends on whom (the dependency map)](#17-the-dependency-map)
18. ["I want to change X": which file, which setting](#18-i-want-to-change-x)
19. [Debugging: your toolkit, step by step](#19-debugging)
20. [Monitoring and improving it yourself (the routine)](#20-monitoring-and-improving-it-yourself)
21. [How to learn it: top-down, bottom-up, and exercises](#21-how-to-learn-it)
22. [Lessons for any big project](#22-lessons-for-any-big-project)
23. [Honest weak spots (technical debt)](#23-honest-weak-spots)
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

**Step 4: path ① (shortcut, 0 tokens).** `_fast()` → `jarvis/core/fastpath.py` `try_answer()` → `match()`, which
tries in order:
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
- `learn.py` judges the **previous** turn: if your message corrected it ("no, I meant..."), the earlier wording is
  learned as belonging to the right area.

### 2.3 The same request from other doors

| Door | Path |
|---|---|
| **Voice in the page** | `frontend/voice.js` records → `POST /api/v1/stt` (`api/routes/voice.py` → `core/stt.py`, Groq Whisper) → text → the same `/chat` with `mode: "voice"` → the reply spoken. |
| **Wake word** | `api/routes/wake.py` runs `core/wake.py` `WakeListener` (mic → voice activity → short Whisper check for "KURAMA") → the page starts listening. |
| **Hold Alt** | `core/ptt.py` (key hook in the server) → the desktop window (`scripts/kurama_wallpaper.py`) shows the panel → the page records → same as voice. |
| **Telegram** | `workers/telegram_bot.py` polls Telegram → the same `Agent` with `channel="telegram"` → replies through the Bot API. Same working memory: "send that image" on Telegram finds the image made on the laptop. |
| **Terminal** | `python -m jarvis` → `jarvis/cli.py` → `Agent.run()`. Handy for debugging without the UI. |

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
├── .env                 secrets (Groq key, Gemini key, Telegram token...). Never committed.
│
├── jarvis/              THE PYTHON PACKAGE (all the logic)
│   ├── core/            ~115 modules: brain + services + foundation (section 7)
│   ├── tools/
│   │   ├── core/        the 17 GENERAL tools the AI sees (thin dispatchers)
│   │   ├── general/     ~150 real tools (one file each)
│   │   └── interactive/ a few more real tools (code, files) + _secrets.py (key detection)
│   ├── api/             FastAPI server: app.py, turns.py, routes/
│   ├── workers/         background loops (reminders, Telegram, guards)
│   ├── agents/          optional focused helpers (coding agent)
│   ├── cli.py           terminal chat
│   └── server.py        `python -m jarvis.server` (starts the API)
│
├── frontend/            the UI: index.html, app.js, voice.js, orb.js, styles.css
├── scripts/             launchers, the desktop window, trace_report.py, tool_round.py
├── browser_ext/         tiny Brave/Chrome extension: the open tabs + your highlight
├── vscode_ext/          tiny VS Code extension: the open file, the selection, edits
├── tests/               ~140 test files; tests/eval/ = the scorecard
├── docs/                HANDOFF.md (state for a new session), plans
└── data/                everything KURAMA stores (not in git): databases, logs, outputs, models
```

---

## 7. Every core file

**Bold** = read these first; they are the skeleton. Line counts from 2026-11-01.

### 7.1 Brain (decides what to do)

| File | Lines | What it does | Change it when |
|---|---|---|---|
| **agent.py** | 1270 | The LangGraph graph (plan → route → llm ⇄ tools; schedule → step → finish); streaming; history, sessions, resume; `_open_question`, `did_line`, `_about_context`, direct replies; the safety nets; `SYSTEM_PROMPT`. | The AI's behaviour, the prompt, retries, how steps run or join. |
| **fastpath.py** | 4230 | 0-token shortcuts: `match()` (choice, patterns, meaning actions), `try_answer()`, `render()` (answer templates), `meaning_ok()`, `meaning_intent()`, `tg_message_text()`, `_focus_intent()`. | A shortcut does the wrong thing, or a frequent AI request should become 0 tokens. |
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
2. Add `jarvis/tools/general/my_tool.py` with `@tool(...)` calling it. `registry.discover()` finds it.
3. Let the AI reach it: add an action to the right general tool's `TABLE` in `jarvis/tools/core/<tool>.py`.
4. Help routing: 4–6 example phrasings in `config.TOOL_EXAMPLES["my_tool"]`.
5. If its own sentence is a complete answer for a short request, add it to `config.DIRECT_REPLY_SINGLE`.
6. Optional, for a very common request: a 0-token shortcut (`MEANING_SHORTCUTS` label + a few lines in
   `fastpath.meaning_intent()`, or a slash command).
7. Test with 3+ phrasings the way you really type; run the scorecard; a live `curl` (section 19).

---

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

## 16. Technologies and why

| Technology | Used for | Why this one (and what was rejected) |
|---|---|---|
| **Groq** (gpt-oss-20b, gpt-oss-120b, qwen3.8-27b, Whisper) | the AI, speech-to-text | Free tier, very fast. Rejected: local LLMs (no GPU, 8 GB RAM), paid APIs. |
| **Gemini** (2.5-flash, flash-lite; optional key) | fallback when Groq is used up | Free tier, good tool calls. Before qwen. `langchain-google-genai` (no torch). |
| **LangChain** (`ChatGroq`, `ChatGoogleGenerativeAI`, tool schemas) | one interface for messages and tools | Readable; the provider is swappable in `llm.model_for()`. |
| **LangGraph** | the agent as a graph; parallel steps with `Send`; the schedule → step loop | Explicit, testable states; a cycle (schedule ⇄ step) runs a whole task graph. Rejected: a hand-written loop; multi-agent frameworks (too many tokens). |
| **fastembed + ONNX Runtime** (`bge-small-en-v1.5`) | meaning: routing, shortcuts, filler, learned plans, search | ~250 MB, CPU only, no PyTorch. |
| **SQLite** (FTS5, WAL) | every database | No server, crash-safe, built-in search. |
| **FastAPI + uvicorn + SSE** | the API | Streaming replies; docs at `/docs`. |
| **Plain HTML/JS** | the UI | No build step, loads instantly. |
| **GTK3 + WebKit2** | the wallpaper/panel window | A real desktop window behind other windows. |
| **edge-tts** · **webrtcvad** | voices · speech detection | Free and natural · tiny, no torch. |
| **pynput, xdotool, wmctrl, pactl, brightnessctl** | controlling the laptop on X11 | Standard tools, each checked with `which`. |
| **psutil · openpyxl · yt-dlp · pytest** | system info · Excel · downloads · tests | Standard, cheap. |

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

## 21. How to learn it

### 21.1 Top-down (recommended first)

| Day | Read | Goal |
|---|---|---|
| 1 | Sections 1–5 of this guide; `CLAUDE.md`. | Know the shape. |
| 2 | `api/routes/chat.py`, `api/turns.py` `run_turn()`. | See a request arrive. |
| 3 | `agent.py`: `stream()`, `_begin_turn()`, `_fast()`, `_build()`, `_route_node()`, `_llm_node()`, `_tools_node()`. | The brain's main loop. |
| 4 | `fastpath.py`: `match()`, `meaning_ok()`, `meaning_intent()`, `try_answer()`, then ONE area (`links_intent()`). | The 0-token path. |
| 5 | `router.py` `route()`, `semantic.py` `scores()` / `best_of()`. | How meaning picks areas. |
| 6 | `registry.py`, `safety.py` (`execute`), `tools/core/_hub.py`, `tools/core/memory.py`. | How tools are found and run. |
| 7 | `workmem.py` (whole file), `focus.refer()`, `agent._open_question()`, `did_line()`, `_messages()`. | Short-term memory. |
| 8 | `planner.plan()`, `taskgraph.py`, `agent._after_schedule()`, `_step_node()`, `_finish_node()`. | The task graph. |
| 9 | `llm.py` `chat()`, `_chain()`, `_on_error()`, `model_for()`; `trace.py`; `scripts/trace_report.py`. | The models and the evidence. |
| 10 | One feature end to end: `tools/general/saved_links.py` → `core/links.py` → its tests. | A full vertical slice. |

Keep a running KURAMA and the snippets of 19.2 handy: predict what each sentence will do, then check.

### 21.2 Bottom-up (second)

`config.py` (skim) → `sheets.py` → `links.py` → `saved_links.py` → `registry.py` → `safety.py` → `workmem.py` →
`_hub.py` → `semantic.py` → `router.py` → `fastpath.py` (one area) → `planner.py` → `taskgraph.py` → `agent.py`.

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

## 23. Honest weak spots

- **`fastpath.py` is 4,200 lines of patterns.** It grew before routing by meaning. New shortcuts should use
  `MEANING_SHORTCUTS`; a future refactor could split it by area.
- **`config.py` is 1,280 lines**, mixing settings with long example lists. Examples could move to their own file.
- **`frontend/app.js` is 2,900 lines** in one file.
- **Working memory reads paths from tool sentences.** A tool whose result doesn't contain the full path isn't
  remembered. The structured fix is tools returning their outputs as data.
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
