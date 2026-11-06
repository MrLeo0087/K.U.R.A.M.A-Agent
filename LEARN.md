# LEARN.md: KURAMA from zero to expert

This guide takes you from "I have never seen the code" to "I can change any part of KURAMA myself". It has four
parts. Read them in order: each one needs the one before.

| Part | What you get | Needs code knowledge? |
|---|---|---|
| **1. KURAMA in plain words** | what it is, what problems it solves, how it works, told as a story with real examples | none |
| **2. The technologies** | every framework and idea KURAMA is built on, what to learn and a day-by-day plan | a little Python |
| **3. The code, file by file** | which file to open first, then next, and what each file is for | Python basics |
| **4. The deep technical details** | how each part works inside: the functions, the data, the numbers | Parts 1–3 |

Never trust a guide over the code: the code is the truth, this is the map. If a name below has moved,
`grep -rn "name" jarvis` finds it.

---

## Contents

**Part 1. KURAMA in plain words**

- [1. KURAMA in plain words](#1-kurama-in-plain-words)

**Part 2. The technologies**

- [2. Technologies: what each one is, where KURAMA uses it, what to learn](#2-technologies-what-each-one-is-where-kurama-uses-it-what-to-learn)
- [3. How to learn it: a day-by-day plan (1–2 hours a day)](#3-how-to-learn-it-a-day-by-day-plan-12-hours-a-day)

**Part 3. The code, file by file**

- [4. Reading the code: the order](#4-reading-the-code-the-order)
- [5. Every file, one line each](#5-every-file-one-line-each)

**Part 4. The deep technical details**

- [6. The life of one request](#6-the-life-of-one-request)
- [7. Short-term memory](#7-short-term-memory)
- [8. Multitasking: the task graph](#8-multitasking-the-task-graph)
- [9. The architecture: layers and why](#9-the-architecture-layers-and-why)
- [10. The folder map](#10-the-folder-map)
- [11. Every core file](#11-every-core-file)
- [12. Tools](#12-tools)
- [13. How KURAMA understands a request](#13-how-kurama-understands-a-request)
- [14. The AI models](#14-the-ai-models)
- [15. Tokens: where they go and how they are cut](#15-tokens-where-they-go-and-how-they-are-cut)
- [16. Long-term memory, data and storage](#16-long-term-memory-data-and-storage)
- [17. Privacy and safety](#17-privacy-and-safety)
- [18. Voice and the desktop](#18-voice-and-the-desktop)
- [19. Background work](#19-background-work)
- [20. The dependency map](#20-the-dependency-map)
- [21. "I want to change X"](#21-i-want-to-change-x)
- [22. Debugging](#22-debugging)
- [23. Monitoring and improving it yourself](#23-monitoring-and-improving-it-yourself)
- [24. Lessons for any big project](#24-lessons-for-any-big-project)
- [25. Industry level: where KURAMA stands, and what is left](#25-industry-level-where-kurama-stands-and-what-is-left)
- [26. Glossary](#26-glossary)

---

# Part 1. KURAMA in plain words

No code in this part. If you can use a phone, you can follow it.

## 1. KURAMA in plain words

### 1.1 What KURAMA is

KURAMA is a personal assistant that lives on your laptop, all day. You talk to it (hold **Alt** and speak, or say
"Hey KURAMA") or type to it (the small chat window beside the fox button, or Telegram on your phone). It
understands English, Nepali and Hindi, and it answers with its voice and in the chat.

What makes it different from a chatbot: **it can act on your laptop.** It opens apps and folders, controls
volume and windows, finds and sends files, plays music, writes documents, makes pictures, watches your model
training, reminds you of things, and much more: about 150 abilities. And it does most of this **for free**,
because most requests never reach a paid AI at all.

### 1.2 A day with KURAMA (real examples)

- **Morning.** "Good morning" → the time, the weather in your city, today's reminders. Instant, no AI used.
- **Working.** "Open kurama folder in VS Code" → your project opens. You misspelled it ("kurma")? It still knows.
- **A question about itself.** "How do you measure my internet speed?" → "I time a download and an upload with
  Cloudflare's test server for 15 seconds." You can change it: "make the speed test 30 seconds".
- **Two jobs at once.** "Write a 1000-word essay about Nepal and open YouTube" → YouTube opens at once; the essay is
  written in the background and KURAMA tells you when it's ready.
- **Linked jobs.** "Find my CV and send it to my phone" → it finds the file *first*, then sends *that* file.
- **Away from the laptop.** On Telegram: "/screen" → a screenshot of your laptop arrives on your phone.
- **Training a model.** "Set up colab" → a ready notebook; while it trains on Google's free GPU, "training status"
  tells you the accuracy, and it warns you if the training crashes.
- **Nepal law and facts.** "What is the fee for Nepal citizenship?" → "Looking that up in the Nepal documents…", and a
  few seconds later the answer with its source (your document service, thousands of Nepal legal documents).
- **A photo you can't read.** Hold Alt, "what is written on the screen?" → the text in its own script (Tamil, Hindi,
  anything) and a line with its meaning in English.
- **Claude Code works for an hour while you're out.** "/claude on" before you leave → Telegram tells you when the
  task starts, asks "❓ it wants to run npm install, yes or no?" (you answer from the phone), and "✅ finished in 47
  min". "/claude status" any time: progress, time left, what it's doing, and a screenshot.
- **Something goes wrong.** RAM is almost full → a warning, and "Say yes to clean your RAM". You say "yes": done.
- **You get lost.** "How can I send a file to my phone?" → it tells you the exact words to say, it doesn't guess.

### 1.3 How it works: the office story

Imagine KURAMA as a small, very efficient office. Your request walks through it like this:

```
 You ──► EARS ──► FRONT DESK ──► (most requests stop here: done instantly, free)
                     │
                     ▼ not sure
                 DISPATCHER ──► picks the 1-3 right DEPARTMENTS
                     │
                     ▼
                  EXPERT (the AI on the internet) ──► asks a WORKER to do the job ──► GUARD checks risky jobs
                     │
                     ▼
                 the answer, spoken and shown;  the NOTEBOOK remembers what happened
```

- **The ears** turn your voice into text (a speech recognition service), and fix common slips ("opne" → "open").
- **The front desk** knows the everyday requests by heart: time, weather, volume, open an app, play music, your
  own commands. It recognises them **by meaning, not exact words**, using a small model that runs on your laptop.
  It answers in a few milliseconds and costs nothing. About three of every four requests end here.
- **The dispatcher** handles everything else. It decides which department the request belongs to (files, web,
  music, coding...), so the expert only sees the few tools that matter. Fewer tools to read = cheaper and smarter.
- **The expert** is a large AI model on the internet (Groq, free tier). It reads your request and the chosen
  tools, and decides what to do. It is the only part that costs "tokens", so it is used as little as possible.
- **The workers** are the tools: one small program for each ability (open a folder, send to Telegram, take a
  screenshot...). They do the real work.
- **The guard** stops anything risky (deleting files, shutting down, running commands) until you say yes.
- **The notebook** is memory: what you just talked about ("send *it*" means the picture it just made), facts you
  told it, your notes, your documents.
- **The front desk first decides what KIND of request it is**, because each kind has its own path:

  | Kind | Example | Where it goes |
  |---|---|---|
  | **General** | "hello", "tell me a joke", "what is gravity?" | a ready answer, or one small AI reply with no tools |
  | **Search** (live, today) | "latest news", "gold price today", "weather tomorrow" | the web |
  | **Automatic** (an action) | "open YouTube", "send this to Telegram", "set a timer" | the tools |
  | **Help** (how to use KURAMA) | "how can I send a file to my phone?" | the exact words to say; never the action itself |
  | **Nepal documents** | "what is the citizenship fee?", "divorce process", "नेपालको सबैभन्दा ठूलो जिल्ला कुन हो" | your Nepal legal and general-knowledge document service, in the background |

  Search is for things that change (today's news, prices); the Nepal documents are for laws, processes, fees and
  facts about Nepal that are written in documents.
- **Background helpers** run quietly all day: reminders, the Telegram bot, the RAM and battery guard, the training
  watcher. Long jobs (an essay, a video) run here too, so the conversation never waits.

### 1.4 The problems we solved (the interesting, hard parts)

Each one below is a real problem, the idea that solved it, and what you get.

| Problem | The idea | Result |
|---|---|---|
| **The AI is free but very limited** (a few thousand words per minute) | Answer everyday requests without the AI at all; send the AI only the 1–3 tool groups that matter, never all 150 tools | ~3 of 4 requests cost nothing; AI requests are ~3x smaller |
| **People say the same thing in many ways** ("minimize YouTube", "put YouTube down") | Compare *meanings* with a small local language model instead of matching exact words | Typos and new phrasings still work |
| **A question can look like a command** ("how can I send a file?" once *started* sending) | Decide the *kind* of request first, from how it starts: a command, a question about using KURAMA, a question about what it did | Questions are answered, never done |
| **"Send it", "open that folder"** | A working memory of the things it made or touched in this conversation | Follow-ups work like with a person |
| **Several tasks in one sentence, some depending on others** | Split the request into steps with links between them; run independent ones together, dependent ones in order, each step getting the real result of the one before | "Find X and send it" sends the right file |
| **8 GB laptop, no GPU** | Small models that load only when needed and unload when idle; heavy work on free cloud services | Under 600 MB of memory when idle |
| **Voice must feel instant** | Speak the first sentence while the rest of the answer is still being written | You hear the answer almost at once |
| **It must never do something dangerous by mistake** | One gate that every action passes through; risky ones need your yes; a PIN for risky Telegram commands | Safe even from your phone |
| **It should get better by itself** | It learns only from you: thumbs up/down, corrections, "when I say X, do Y" | Your own shortcuts, free forever |
| **It should explain itself** | Descriptions of every ability are built from the code itself; explanations use the real record of what it did | "How did you do that?" gets a true answer |
| **Large project, one person** | Every request is recorded (what was understood, which tool ran, how long, how many tokens); 1,800+ automatic tests | Problems are found from evidence, fixes don't break other things |

### 1.5 What it costs and what it needs

- **Money:** nothing. Free AI tier (Groq, Gemini as backup), free voices (Microsoft Edge voices), free speech
  recognition (Groq Whisper), free cloud GPU for training (Colab, Kaggle).
- **Laptop:** Ubuntu, 8 GB RAM, no graphics card. It shares the laptop with VS Code and Chrome.
- **Internet:** needed for the AI, the voice and the web. Without it, the instant commands still work.

### 1.6 Words you will meet (plain meanings)

| Word | Plain meaning |
|---|---|
| **AI model / LLM** | the "expert": a program that reads text and writes an answer (here: on Groq's servers) |
| **Token** | a piece of a word; the free AI allows only so many per minute and per day |
| **Tool** | one ability KURAMA has (a small program), e.g. "take a screenshot" |
| **Instant command / shortcut / fast path** | a request answered without the AI: free and immediate |
| **Router** | the dispatcher: picks which tool groups a request needs |
| **Meaning model / embeddings** | a small local model that turns sentences into numbers, so similar meanings are close |
| **Trace** | the record of one request: what was understood, what ran, how long, how many tokens |
| **Worker** | a background helper that runs all day (reminders, Telegram...) |
| **Job** | a long task running in the background (an essay, a video) |
| **Agent** | the part that lets the AI use tools in a loop until the job is done |

---

# Part 2. The technologies

Now the tools of the trade. You can't read KURAMA's code without knowing what these are. For each one: where
KURAMA uses it and what to learn. After the list comes a day-by-day plan (1–2 hours a day).

## 2. Technologies: what each one is, where KURAMA uses it, what to learn

This is the list of everything you must know to understand KURAMA fully. If you can explain every row in your own
words and point at the file that uses it, you know the stack that real AI-product teams use.

**Levels:** ★ = learn it well (you need it daily), ◆ = understand the idea and read the KURAMA code, ○ = know what it
is and when you'd reach for it.

### 2.1 Language and core Python

| Technology | Level | Where in KURAMA | What to learn |
|---|---|---|---|
| **Python 3.12** | ★ | everything in `jarvis/` | functions, classes, dataclasses, type hints (`str \| None`), f-strings, comprehensions, `pathlib`, `re`, `json`, exceptions, context managers (`with`), decorators |
| **Decorators + registries** | ★ | `registry.py` `@tool(...)` | how a decorator records a function in a dict at import time; why "one tool = one file" works |
| **Threads, locks, events, queues** | ★ | `jobs.py` (thread pool), `workers/`, `learn.py` (one worker queue), `telegram_bot.py` (uploads beside the chat) | `threading.Thread/Lock/Event`, `queue.Queue`, `concurrent.futures`, race conditions, "never block the voice loop" |
| **asyncio** | ◆ | FastAPI routes, `run_in_threadpool`, edge-tts | event loop, `async/await`, why blocking code goes to a thread pool |
| **subprocess** | ★ | every laptop tool (`xdotool`, `pactl`, `fd`, `rg`), `tools/interactive/_proc.py` | `run` vs `Popen`, timeouts, never `shell=True` with user text, an allowlist |
| **Regex** | ★ | `fastpath.py`, `spelling.py`, `planner.py` | groups, named groups, lookahead, `re.I`, why regex is used only as a *candidate* and meaning decides |
| **Lazy imports + memory** | ◆ | `memory.py`, `semantic.py`, `send_file_telegram._small_photo` | import inside the function, unload when idle, measure RSS (`make rss`) |

### 2.2 AI and LLM engineering

| Technology | Level | Where | What to learn |
|---|---|---|---|
| **LLM APIs (chat completions, tool calling)** | ★ | `llm.py` | messages (system/user/assistant/tool), temperature, max tokens, JSON schema for tools, streaming tokens |
| **Groq** (gpt-oss-20b/120b, qwen, Whisper) | ★ | `llm.py`, `stt.py` | rate limits (tokens/min, requests/day), 429 + `Retry-After`, model tiers |
| **Gemini** (free fallback) | ○ | `llm.model_for()` | a second provider behind the same interface |
| **LangChain core** | ★ | `ChatGroq`, `@tool` schemas, `HumanMessage/AIMessage/ToolMessage` | Runnables, `bind_tools`, `invoke` vs `stream`, tool-call objects |
| **LangGraph** | ★ | `agent.py` `_build()` | `StateGraph`, nodes, edges, conditional edges, cycles (`llm ⇄ tools`), parallel fan-out with `Send`, state reducers |
| **Prompt engineering** | ★ | `agent.SYSTEM_PROMPT` (< 250 tokens), `_messages()` | short system prompt, give facts not prose, few tools, history trimming, rolling summary |
| **Agent patterns** | ★ | `planner.py`, `taskgraph.py` | ReAct loop, plan-and-execute, task DAG with `depends_on`, re-planning a failed step, "claimed but didn't do" checks (`meta.needs_tool`) |
| **Token economics** | ★ | section 15, `budget.py`, `ratelimit.py` | counting tokens, cutting them, caching, routing cheap → expensive |
| **Embeddings** (fastembed, `bge-small-en-v1.5`, ONNX Runtime) | ★ | `semantic.py`, `memory.py`, `recipes.py` | a sentence → 384 numbers; cosine similarity; thresholds and margins |
| **Semantic routing** | ★ | `router.py`, `semantic.scores()`, `fastpath.meaning_ok()` | pick tools by meaning, not keywords; learned examples; a gate that vetoes wrong shortcuts |
| **RAG (retrieval-augmented generation)** | ★ | `memory.py` | chunking, BM25 (FTS5) + vectors, **reciprocal rank fusion**, incremental indexing, citations |
| **Speech: STT, TTS, VAD, wake word** | ◆ | `stt.py` (Whisper), `tts.py` (edge-tts), `audio.py` (webrtcvad), `wake.py` | sample rate, PCM/WAV, voice activity detection, sentence-by-sentence TTS while the LLM streams, barge-in |
| **Evaluation** | ★ | `tests/eval/harness.py`, `tests/eval/cases.jsonl` | a fixed test set, scorecard metrics (instant %, right %, router %), never "it felt better" |
| **Learning from feedback** | ◆ | `learn.py`, `recipes.py`, `style.py`, `mywords.py` (read `docs/LEARNING.md`) | explicit feedback only (👍/👎, corrections), answer cache keyed by meaning, safe "unlearn" |

### 2.3 Backend, data and caching

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

### 2.4 Frontend and desktop

| Technology | Level | Where | What to learn |
|---|---|---|---|
| **HTML/CSS/JavaScript (ES modules)** | ★ | `frontend/` (`app.js`, `api.js`, `voice.js`) | DOM, events, `fetch`, `async/await`, modules, CSS variables, flex/grid |
| **Web Audio + MediaStream** | ◆ | `voice.js` `Mic`, `Recorder`, `Player` | `getUserMedia`, AudioContext, AudioWorklet, recording WAV in the browser |
| **GTK3 + WebKit2 (PyGObject)** | ○ | `scripts/kurama_wallpaper.py` | a native window hosting a web page, messages page ⇄ host (`hostSay`) |
| **Linux desktop (X11)** | ◆ | `xdotool`, `wmctrl`, `pactl`/PipeWire, `gsettings`, `brightnessctl`, AT-SPI | how the desktop is controlled from code; PipeWire modules (`devaudio.py`) |
| **systemd / autostart / signals** | ○ | `scripts/kurama-power.sh`, `ptt.py` (`SIGUSR2`) | processes, PIDs, signals, autostart |

### 2.5 Engineering practice (what makes it "industry level")

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

## 3. How to learn it: a day-by-day plan (1–2 hours a day)

**12 weeks, about 1.5 hours a day.** Each day has one thing to *read* and one thing to *do*. If a day takes longer,
move on anyway and come back at the weekend. Day 7 of every week is for review: re-explain the week out loud, as if
teaching someone, and write what you still don't get in a `NOTES.md` of your own.

**Rule for every day:** keep KURAMA running, open the files beside this guide, and predict before you check ("this
sentence will go to the fast path, tool X"), then check with the snippets in 19.2.

### Week 1: Python as KURAMA uses it
| Day | Read / learn | Do |
|---|---|---|
| 1 | Sections 1–6 of this guide. `CLAUDE.md`. | Draw the life of one request on paper from memory. |
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
| 26 | Semantic answer cache. Read `recipes.py` (kept answers) + `docs/LEARNING.md` §1–10. | Ask a question, 👍 it, ask it again: check the trace says 0 tokens. |
| 27 | Rate limits. Read `core/ratelimit.py`. | Explain a token bucket with numbers on paper. |
| 28 | Review. | — |

### Week 5: LLMs and LangChain
| Day | Read / learn | Do |
|---|---|---|
| 29 | How chat LLMs work: tokens, context, temperature, tool calling (Groq docs). | Call Groq directly with `ChatGroq` in a 10-line script. |
| 30 | LangChain messages and tools. Read `registry.py` schemas. | Bind one tool to `ChatGroq`; print the tool call it returns. |
| 31 | Read `core/llm.py` `chat()`, `_chain()`, `_on_error()`. | Explain what happens on a 429 with and without `Retry-After`. |
| 32 | Prompt design. Read `agent.SYSTEM_PROMPT` and `_messages()`. | Count the tokens of one real prompt from a trace. |
| 33 | Token economics. Section 15. | Find the most expensive request this week in `make report`. |
| 34 | Model tiers and fallbacks. `config.TIER_CHAIN`. | Predict which model answers a voice chat; check the trace. |
| 35 | Review. | — |

### Week 6: LangGraph and agents
| Day | Read / learn | Do |
|---|---|---|
| 36 | LangGraph quickstart (official docs): StateGraph, nodes, edges. | Build a 3-node toy graph. |
| 37 | Conditional edges and cycles. Read `agent._build()`. | Add a cycle to your toy graph (a tool loop). |
| 38 | Parallel fan-out with `Send`. Read section 8 of this guide. | Make your toy graph run 3 steps in parallel. |
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
| 50 | Working memory. Section 7; `workmem.py`. | Exercise 3 in 21.3. |
| 51 | Choices. `workmem.choose()`, `act_on()`. | Find something, then "open 2 in vs code"; read the trace. |
| 52 | Learning. `docs/LEARNING.md` §11–22; `learn.py` `_judge`. | Teach "when I say X, do Y"; then forget it. |
| 53 | Recipes. `recipes.py` `observe`, `feedback`. | 👎 a reply and read what was stored. |
| 54 | Safety. Section 17; `telesec.py`. | Explain which Telegram commands ask for the PIN and why. |
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
| 73 | Traces. Section 22.3; `trace.py`. | `make report`; pick one failure and find its cause. |
| 74 | Debugging method (19.1). | Exercise 10 in 21.3: fix a real bug with a test that fails first. |
| 75 | Git deeper: `log -p`, `blame`, `bisect`. | Use `git log -S "act_on"` to find when choices changed. |
| 76 | Lint gate, pre-commit, CI: `pyproject.toml`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`. | Install pre-commit; make a commit pass the hooks. |
| 77 | Review. | — |

### Week 12: industry level, by doing it
| Day | Read / learn | Do |
|---|---|---|
| 78 | Sections 25 and 25.3; ADR 0009 and `core/results.py`. | Make `list_folder` return a `Reply(text, paths=[...])` like `find_files` + a test. |
| 79 | Section 12.4 and ADR 0011 (plug-ins). | `make new-memory NAME=habits_log`: make it search your habits; check `recall` finds one. Delete it after. |
| 80 | Type checking: mypy basics. | Add `core/intents/todo.py` to `TYPED` in the Makefile; fix what `make type` finds. |
| 81 | Coverage. | `make cov`; open `data/coverage/index.html`; write one test for the least-covered core file you use daily. |
| 82 | Metrics: Prometheus text format. | `make metrics`; add one metric (e.g. errors in the last 24 h) to `core/metrics.py` + the test in `test_api.py`. |
| 83 | ADRs. | Read `docs/adr/`; write ADR 0011 for a choice you make yourself. |
| 84 | Final review. | Explain KURAMA end to end in 15 minutes, without notes. |

**After week 12** you can explain, change and debug every part. Then keep the routine of section 23 (15 minutes
every 2–3 days) and work through section 25.2 one item at a time.

### 3.3 Practice exercises (in order; each with a test you write)

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

### 3.4 How to read a big file without drowning

- Read the module docstring first (most files explain themselves at the top).
- List the functions: `grep -n "^def \|^class \|    def " jarvis/core/agent.py`.
- Follow one call from the entry point; ignore everything else for now.
- Use the tests as examples: `grep -rn "workmem\." tests | head` shows how a module is called.

---

---

# Part 3. The code, file by file

Now open the code. Read the files **in this order**: each one builds on the ones before, and together they follow
one request from your mouth to the answer. For each file: what it does, the problem it solves, and what to look at
first. Open the file beside this guide; don't read it all, read the parts named.

## 4. Reading the code: the order

**Before you start:** run KURAMA once (`make run`), say a few things, and run `make report` to see the traces of
what you said. Seeing it work first makes the code much easier to follow.

### Stage A: where everything starts

**1. `jarvis/core/config.py`: every setting in one place**
- *Does:* holds every number, name and switch: which AI models, voices, folders, limits, example phrases.
- *Solves:* settings scattered across 400 files would be impossible to change safely.
- *Look at:* the model names near the top, `TOOL_EXAMPLES`, `MEANING_SHORTCUTS`. Just skim: you'll come back here.

**2. `jarvis/api/app.py`: the server starts**
- *Does:* starts the web server the chat window talks to, and the background helpers.
- *Solves:* one process for everything (saves memory on an 8 GB laptop).
- *Look at:* `create_app` and the `lifespan` function (what happens at start-up).

**3. `jarvis/api/routes/chat.py` and `jarvis/api/turns.py`: a message arrives**
- *Does:* receives your chat message and streams the answer back word by word.
- *Solves:* the AI part is slow and blocking; the window must stay smooth. `turns.py` runs each request in its own
  thread and sends pieces back as they come.
- *Look at:* the `/chat` route, then how `turns.py` calls `agent.stream`.

### Stage B: understanding a request

**4. `jarvis/core/agent.py`: the conductor**
- *Does:* takes one request and decides the path: instant command, offer accepted, or the AI with tools.
- *Solves:* one place that ties all the parts together, with the cheapest path tried first.
- *Look at:* `_run` (short, read it fully). Every line is one step of Part 1's office story.

**5. `jarvis/core/spelling.py` and `jarvis/core/mywords.py`: clean the words**
- *Does:* fixes common slips ("opne" → "open") and swaps your own commands ("good night" → "lock the screen").
- *Solves:* voice and fast typing are messy; your shortcuts should work everywhere.
- *Look at:* the `_FIX` list; `expand` in mywords (6 lines).

**6. `jarvis/core/querykind.py`: what kind of request is it?**
- *Does:* decides first whether it's a question about using KURAMA ("how can I…"), about what it did ("how did
  you…"), a repeat ("run it again for 30 seconds"), or a normal request.
- *Solves:* a question that sounded like a command used to be *done* instead of answered.
- *Look at:* `QUERY_OPENINGS` in config.py, then `route`.

**7. `jarvis/core/fastpath.py` and `jarvis/core/intents/*.py`: the front desk**
- *Does:* recognises everyday requests and runs the right tool with no AI.
- *Solves:* cost and speed: three of four requests are answered here, free, in milliseconds.
- *Look at:* `match` (the order things are tried), then one area file, e.g. `intents/desktop.py` (volume).

**8. `jarvis/core/semantic.py`: understanding by meaning**
- *Does:* runs the small local model that turns sentences into numbers and compares them.
- *Solves:* "minimize YouTube" and "put YouTube down" mean the same; word rules can't know that.
- *Look at:* `best_of` (the one function most of KURAMA uses).

**9. `jarvis/core/router.py`: the dispatcher**
- *Does:* picks the 1–3 tool groups a request needs before the AI sees it.
- *Solves:* sending all 150 tools to the AI on every request would waste the free limit.
- *Look at:* `route`.

### Stage C: doing the work

**10. `jarvis/core/registry.py`: how a tool is made and found**
- *Does:* the `@tool` label that turns a plain Python function into a tool the AI can use; finds every tool file.
- *Solves:* adding a tool is one file; nothing central to edit.
- *Look at:* `tool`, `discover`, `call`.

**11. `jarvis/tools/general/echo_time.py`, then `find_files.py`: two real tools**
- *Does:* tell the time; find files. The first is the simplest tool there is; the second a real one.
- *Solves:* each ability lives in its own small file, easy to read, test and fix.
- *Look at:* the `@tool(...)` line and the docstring: that's what the AI reads.

**12. `jarvis/tools/core/_hub.py` and `jarvis/tools/core/files.py`: the general tools**
- *Does:* 17 "general" tools the AI sees, each pointing to many real tools by an `action` word.
- *Solves:* the AI picks better from 17 clear choices than from 150.
- *Look at:* the `TABLE` in files.py.

**13. `jarvis/core/safety.py`: the guard**
- *Does:* every action passes here: safe ones run, risky ones wait for your yes, every one is logged.
- *Solves:* nothing dangerous happens by mistake, from the chat or the phone.
- *Look at:* `execute`.

**14. `jarvis/core/llm.py` and `jarvis/core/budget.py`: talking to the AI**
- *Does:* sends requests to Groq, retries when busy, falls back to another model, counts tokens.
- *Solves:* the free tier is often busy or over its limit; KURAMA must keep working.
- *Look at:* `chat` and the fallback chain.

### Stage D: memory and multitasking

**15. `jarvis/core/planner.py` and `jarvis/core/taskgraph.py`: several tasks at once**
- *Does:* splits "find my CV and send it to my phone" into steps with links; runs them in the right order.
- *Solves:* parallel where possible, in order where needed, each step getting the real result of the one before.
- *Look at:* `plan` in planner.py; the step loop in taskgraph.py.

**16. `jarvis/core/workmem.py` and `jarvis/core/focus.py`: "it", "this", "that folder"**
- *Does:* remembers the things made or touched in this conversation, and the folder you're talking about.
- *Solves:* follow-ups like "send it" or "open the second one".
- *Look at:* `record_call` and `choose` in workmem.py.

**17. `jarvis/core/store.py`: the database**
- *Does:* one SQLite file for logs, chat, jobs, settings.
- *Solves:* durable, fast, no extra server to run.
- *Look at:* the table list at the top (`CREATE TABLE`).

**18. `jarvis/core/memory.py`, `jarvis/core/memories.py`, `jarvis/core/profile.py`: long-term memory**
- *Does:* searches your documents (by words and by meaning together), keeps facts about you, and lets new kinds of
  memory be added as one file.
- *Solves:* "what did I write about X?" over thousands of files, on a small laptop.
- *Look at:* `search` in memory.py; `MemorySource` in memories.py.

**19. `jarvis/core/trace.py`: the record of every request**
- *Does:* writes what was understood, what ran, how long and how many tokens, for every request.
- *Solves:* problems are found from evidence, not guesses. `make report` reads it.
- *Look at:* `begin` and `end`.

**20. `jarvis/core/learn.py` and `jarvis/core/recipes.py`: learning from you**
- *Does:* turns your thumbs up, corrections and repeats into new instant commands.
- *Solves:* it gets cheaper and more right every day, only from your feedback.
- *Look at:* the module docstrings first.

### Stage E: around the conversation

**21. `jarvis/core/jobs.py`: background jobs**
- *Does:* runs long work (essays, videos, scans) in the background and tells you when it's done.
- *Solves:* the conversation never waits for a long job.

**22. `jarvis/workers/inproc.py` and `jarvis/workers/resource_guard.py`: background helpers**
- *Does:* starts the helpers (reminders, Telegram, guards); resource_guard watches RAM, CPU and battery.
- *Solves:* things that must happen without you asking.

**23. `jarvis/core/stt.py`, `tts.py`, `ptt.py`, `wake.py`: the voice**
- *Does:* speech to text, text to speech (sentence by sentence), hold-Alt-to-talk, and "Hey KURAMA".
- *Solves:* a voice that feels instant and never cuts you off.

**24. `frontend/app.js`, `frontend/voice.js`, `scripts/kurama_wallpaper.py`: the window**
- *Does:* the chat page (JavaScript) and the desktop window around it (the fox button, the mini chat).
- *Solves:* a small, smooth window that is always there.

**25. `jarvis/core/selfindex.py`, `usersettings.py`, `nextstep.py` and `jarvis/tools/general/explain_self.py`:
KURAMA knows itself**
- *Does:* describes every ability from its own code, explains what it did, changes safe settings, offers the next
  step ("say yes to send it to Telegram").
- *Solves:* you never have to remember how KURAMA works: ask it.

**26. `tests/`: how everything is checked**
- *Does:* 1,800+ small automatic checks, run with `make test`.
- *Look at:* `tests/test_registry.py` (short and clear): each test is a tiny example of how a part is used.

After these 26 stops you know the whole flow. The rest of the files are features; the list below says what each
one does, so you can find any of them.

## 5. Every file, one line each

<!-- FILES:START -->

_Generated by `scripts/file_guide.py` from each file's own description; run `make files-guide` after adding a file._

#### `jarvis/`: Start-up (how KURAMA is launched)

| File | Lines | What it does |
|---|---|---|
| `__init__.py` | 1 | JARVIS voice assistant. |
| `__main__.py` | 9 | `python -m jarvis` -> terminal text chat (`--voice` / `--wake` -> voice loop). |
| `cli.py` | 68 | Terminal text chat: `python -m jarvis`. |
| `server.py` | 44 | `python -m jarvis.server [--port 8000] [--host 127.0.0.1] [--no-warm]` -> http://127.0.0.1:8000 Thin shim kept for old commands/autostart entries: it runs the KURAMA API… |
| `voice.py` | 371 | Voice loop: `python -m jarvis --voice` (wake word on by default) or `--wake` / `--no-wake`. |

#### `jarvis/api/`: The web server the window talks to

| File | Lines | What it does |
|---|---|---|
| `__init__.py` | 6 | KURAMA HTTP API (FastAPI): the only thing the frontend talks to. |
| `__main__.py` | 8 | — |
| `app.py` | 165 | KURAMA API app factory + runner. |
| `audio.py` | 83 | Audio helpers for the API: browser recordings -> 16 kHz wav (STT), and text -> streamed mp3 (TTS). |
| `device.py` | 141 | This laptop at a glance, for the dashboard's "This laptop" card (GET /api/v1/device). |
| `security.py` | 83 | Request guard for the KURAMA API (pure ASGI, so SSE streams pass through untouched). |
| `settings.py` | 108 | Settings for the KURAMA HTTP API (jarvis.api). |
| `status.py` | 185 | Laptop + KURAMA status snapshot for /api/v1/status (LAPTOP-LOCAL: it describes the machine the API runs on; a future server deployment needs a small "laptop agent" to re… |
| `turns.py` | 269 | Chat turns + web confirmations: the bridge between the blocking agent and the async API. |

#### `jarvis/api/routes/`: Its addresses (one file per area)

| File | Lines | What it does |
|---|---|---|
| `__init__.py` | 1 | API routers. |
| `chat.py` | 105 | POST /api/v1/chat (SSE) and POST /api/v1/confirm. |
| `claude.py` | 27 | Claude Code watch, laptop side: the hook (scripts/claude_hook.py) posts Claude Code's events here and waits for the owner's answer to a permission question (jarvis/core/… |
| `dash.py` | 593 | Dashboard panels (laptop-local): one cheap summary for the cards, details when a card is clicked, a fuller forecast, and a few direct actions (open in VS Code, show in f… |
| `info.py` | 673 | Read-mostly panels: health, status (+SSE stream), jobs, alerts, profile facts, tools. |
| `metrics.py` | 17 | GET /api/v1/metrics: Prometheus text format (scrape it, or read it with `make metrics`). |
| `voice.py` | 122 | POST /api/v1/stt (recording -> text) and POST /api/v1/tts (text -> streamed mp3). |
| `wake.py` | 108 | Wake word for the dashboard: while KURAMA sleeps, the API listens with a cheap Python loop (sounddevice + webrtcvad + short-burst recognition, jarvis.core.wake.WakeListe… |

#### `jarvis/core/`: The brain and the services (most of the logic)

| File | Lines | What it does |
|---|---|---|
| `__init__.py` | 1 | Core services: config, LLM client, budget, storage. |
| `agent.py` | 1473 | LangGraph agent on LangChain messages: route -> llm (model.bind_tools with only the routed groups' tools) -> tools (our own node: safety confirm/blocked + logging) -> ll… |
| `assist.py` | 1043 | Help with whatever is highlighted in any app (one tool, several jobs), plus code in VS Code: READ (the answer comes to the chat; the selection is not touched) explain wh… |
| `audio.py` | 419 | Audio I/O: mic capture with webrtcvad endpointing, a stoppable player, and a barge-in monitor. |
| `audiomaker.py` | 95 | Text -> MP3 with edge-tts (free, 0 tokens): the highlighted text, a file (txt/md/pdf), a web page, the newest workspace document, or words typed after 'make an audio of:… |
| `automation.py` | 357 | File automations (0 tokens): overnight downloads, a tidy Downloads folder, and backups that check themselves. |
| `brief.py` | 170 | Morning brief (0 tokens): the first time I use the laptop each day (unlock, wake from sleep, or KURAMA's first screen of the day) KURAMA says what matters today, in a fe… |
| `browsertab.py` | 99 | The tab open in the browser right now, told by KURAMA's tiny browser extension (browser_ext/, load it once in Brave: brave://extensions -> Developer mode -> Load unpacke… |
| `budget.py` | 39 | Daily token budget tracker backed by the SQLite llm_calls log. |
| `charts.py` | 357 | Charts from data (0 tokens to draw): my money, a CSV/Excel/JSON file, or a link (a government data page, a .csv/.xlsx download, an HTML table). |
| `claudewatch.py` | 775 | Claude Code watch: KURAMA follows a long Claude Code task for you while you are away, like the Colab training link. |
| `cleanup.py` | 297 | Clean RAM / storage / KURAMA (0 tokens, no internet). |
| `cloudshare.py` | 63 | Share a big file by uploading it to a free host and returning ONE download link (no account, no API key). |
| `cmdalerts.py` | 176 | Long-command alerts: any terminal command that runs longer than N minutes tells you when it ends (0 tokens). |
| `codenav.py` | 304 | Go to the real code of a function/class (0 tokens): the name highlighted in VS Code -> where it is DEFINED (the project first, then the installed library) -> opened in V… |
| `coderun.py` | 136 | Run the highlighted code and show what it prints (0 tokens): 'run this code' / '/run'. |
| `codetidy.py` | 142 | Format and check a code file on this laptop, 0 tokens (ruff for Python, the json module for JSON). |
| `config.py` | 1602 | Central configuration. |
| `contacts.py` | 170 | Contacts kept in a real Excel sheet (~/Documents/KURAMA/contacts.xlsx): add, find (fuzzy), list, update, delete. |
| `context.py` | 127 | What is open right now (0 tokens to collect, ~30 to send): the file open in VS Code and the code selected in it, or the browser's tab. |
| `convert.py` | 440 | File converter: documents, images, audio/video, tables — all local, 0 tokens. |
| `decode.py` | 180 | Decode / prettify the highlighted text on this laptop, 0 tokens: JSON, JWT, base64, URL-encoding, query strings, Unix timestamps, HTML entities, \u escapes, XML, hex; an… |
| `devaudio.py` | 423 | Device sound and the mic ("Hear device sound" in settings). |
| `diagram.py` | 273 | Diagrams, 0 tokens, drawn with Pillow (data/outputs/diagrams/*.png): - project: from the project's README only (headings -> branches, their bullet points -> leaves). |
| `dictation.py` | 309 | Voice typing in any app: "dictate" -> what you say is typed where the cursor is, until "stop dictation". |
| `dictionary.py` | 72 | Offline English dictionary (0 tokens): Open English WordNet 2024 in data/wordnet/wn.db (the `wn` package). |
| `digest.py` | 137 | Daily digest (P7): a zero-LLM template of the day's activity. |
| `diskclean.py` | 191 | ML disk cleaner: what fills the disk, with the ML culprits named, and safe ways to free it (0 tokens). |
| `doctor.py` | 255 | Laptop doctor: "why is my laptop slow?" answered from real measurements, with fixes it can do for you (0 tokens). |
| `edge_pool.py` | 183 | Warm, reusable edge-tts websockets. |
| `editor.py` | 127 | VS Code, exactly (the 'KURAMA editor link' extension, vscode_ext/): which file is open, what is selected (text + lines), unsaved edits, and edits INTO the editor (one Ct… |
| `episodes.py` | 137 | Episodic memory (P7): past chat sessions and messages, zero LLM tokens. |
| `errmem.py` | 144 | Error memory: explain a Python/terminal error once, remember it, and remember how YOU fixed it. |
| `expenses.py` | 538 | Money tracker (0 tokens): what I spend and earn, by day / week / month / year, budgets and monthly bills. |
| `fastpath.py` | 3002 | Zero-token fast path: high-confidence regex intents that call one tool directly and answer from a template, with no LLM call. |
| `filemanager.py` | 72 | The Files app (Nautilus) as context, like the VS Code file and the browser tab: which folder is open and what is selected, used when Files is the app the user used most … |
| `focus.py` | 154 | Conversation focus = KURAMA's "current folder": the folder/file the user is talking about right now, plus a short history, so follow-ups work like a shell's cwd: "list f… |
| `geolocate.py` | 292 | Where is the laptop? |
| `goals.py` | 798 | Goals = long tasks that last weeks or months (my list is for short to-dos). |
| `greeting.py` | 105 | Startup greeting for voice mode: time of day + a weather one-liner + running jobs / saved notes. |
| `guard.py` | 206 | Laptop guard: while armed, anyone who unlocks the laptop, types a wrong password or wakes it up gets their photo taken with the webcam and sent to your Telegram, with wh… |
| `habits.py` | 241 | Daily habits with streaks (0 tokens): 'add a habit: drink water 8 glasses a day, remind me at 10 am', 'I drank 2 glasses of water', 'did exercise', 'my habits', 'delete … |
| `hotkey.py` | 97 | Global push-to-talk hotkey via pynput (X11). |
| `identity.py` | 51 | The assistant's name (default KURAMA, changeable by the user) and the words it answers to. |
| `installer.py` | 188 | Install / remove / update apps from apt, snap or flatpak — finds the right source, then installs in the background. |
| `jobqueue.py` | 231 | KURAMA's job list: things YOU want KURAMA to do later (a to-do is for you, a job is for KURAMA). |
| `jobs.py` | 581 | Background jobs: JobManager singleton (ThreadPoolExecutor, SQLite `jobs` table, cancel events, progress strings, on_done callbacks) and the Announcer (text: print; voice… |
| `kaggle_gpu.py` | 275 | Train on Kaggle's free GPU from the laptop: "train this on GPU" -> push, watch, download the results. |
| `lanes.py` | 58 | Lanes (master plan phase 1, the good idea from KURAMA Version_4, by meaning instead of an AI call): every request is general (chat / knowledge / feelings: no tools), sea… |
| `learn.py` | 320 | KURAMA learns which area a request belongs to from how each turn went (0 tokens, all local). |
| `lecture.py` | 140 | Lecture recorder: record a class (the microphone, or the laptop's own sound for an online class), then turn it into a transcript saved in ~/Notes/Lectures (a background … |
| `libhelp.py` | 250 | Library help for the highlighted code: what a function takes, and whether YOUR call is right. |
| `links.py` | 262 | Links = named links the user keeps ('this is the link for Claude Code, save it' -> later 'give me my Claude Code link'). |
| `live.py` | 472 | Real-time answers from sources that are actually live, not search-engine snippets (which are often days old). |
| `llm.py` | 557 | Groq chat through LangChain (ChatGroq): per-model settings from config, our own retry/backoff on 429/5xx (retry-after aware), tier fallback chain, daily budget, and a ca… |
| `locationlog.py` | 215 | Location history for the laptop and the phone (0 chat tokens). |
| `longjobs.py` | 380 | Long Job Engine (Night Shift foundation, step 1): durable background jobs on top of jobs.JobManager. |
| `memories.py` | 80 | Memory sources: every kind of thing KURAMA remembers, behind one small contract, so a new kind of memory is one new file and never touches the others. |
| `memory.py` | 909 | Semantic memory (P7): hybrid RAG over the user's code and notes. |
| `meta.py` | 166 | Freedom routing (P7b): the `request_tools` meta-tool. |
| `metrics.py` | 72 | Prometheus-style metrics (text format 0.0.4) from the SQLite logs KURAMA already writes: LLM calls and tokens, tool calls, routing, jobs, and this process's RAM/CPU. |
| `modes.py` | 188 | KURAMA power modes: how much of KURAMA runs, so it fits next to big tasks on an 8 GB laptop. |
| `music.py` | 656 | Music without the browser (0 tokens): only the sound, ~30-60 MB instead of a ~300 MB browser tab. |
| `mywords.py` | 115 | The owner's own words: "when I say good night, lock the screen" -> saying "good night" (the whole request) runs "lock the screen", forever, until the owner changes or fo… |
| `nepaldocs.py` | 96 | The owner's Nepal documents service (a RAG API over thousands of Nepal legal and general-knowledge documents: citizenship, passport, marriage and divorce, traffic rules … |
| `nepdate.py` | 40 | Bikram Sambat (BS) <-> Gregorian (AD) date helper. |
| `netdoctor.py` | 209 | Internet doctor: "internet is slow / not working" -> which link is broken (Wi-Fi, router, provider, DNS), the fix, an optional speed test, and "tell me when it's back" (… |
| `nextstep.py` | 84 | The next step, offered after an answer: one short line ("Want it on your phone? |
| `notebook_template.py` | 166 | The ready-to-run training notebook (.ipynb) that links a Colab or Kaggle run to KURAMA. |
| `notes.py` | 94 | Study notes inbox: quick notes from the laptop or the phone (text, voice, photos) filed by subject and date in ~/Notes/<Subject>/<YYYY-MM-DD>.md, and "show my DSA notes … |
| `notify.py` | 562 | notify(title, text, level): one alert fanned out to every available channel. |
| `ocr.py` | 465 | Read the text in a picture: a screen area you drag, the whole screen, an image file, a copied image or a photo sent on Telegram. |
| `organizer.py` | 436 | Smart file organizer: rename and sort a messy folder (Downloads by default) by what is INSIDE the files. |
| `overview.py` | 89 | One "status" for everything that's going on (0 tokens): training runs (epoch x/N, accuracy, loss trend, ETA), background jobs, downloads, a lecture being recorded, page … |
| `pageread.py` | 118 | 'What is this page about?' = the page open in the browser RIGHT NOW (never an older link from the chat). |
| `paths.py` | 305 | Smart path resolution for spoken/loose paths ("project1 then tara folder", "tara source code in project1", "/media/leo/project1/tara"). |
| `phone.py` | 210 | Phone <-> laptop bridge over the Telegram bot (0 tokens): files and photos you send land on the laptop, voice notes become text (Groq Whisper: audio quota, not chat toke… |
| `phonecmds.py` | 81 | The Telegram commands on the laptop too (0 tokens): /camera, /video, /where, /here, /history, /guard, /track, /mute, /unmute, /notifications, /control... |
| `phrases.py` | 69 | Many ways to say hello, thanks and goodbye (0 tokens), picked at random so KURAMA never sounds the same twice. |
| `planner.py` | 587 | Multi-intent planner: cheap regex detection first, a tiny fast-tier structured call only when flagged. |
| `plugins.py` | 57 | Plugin discovery shared by every extension point (agents, memory sources; tools use registry.discover). |
| `ports.py` | 83 | Which program uses which port (0 tokens, psutil): 'what is running on port 8000', 'show my open ports'. |
| `privacy.py` | 23 | Keep KURAMA data private to this user: called first thing by every entry point. |
| `profile.py` | 355 | Profile memory (P7 tiered memory, tier a): facts about the user as key -> value. |
| `progress.py` | 103 | Everything running right now, in one list, for the Progress section of the main and the mini window: background jobs (writing, downloads, file sends, images, scans, the … |
| `ptt.py` | 296 | Hold-to-talk: hold a key combo (default Ctrl+Space), speak, let go -> KURAMA hears it, without opening the chat. |
| `qr.py` | 115 | Scan QR codes / barcodes on the screen, in a dragged area, a copied image or a picture file (zxing-cpp, 0 tokens). |
| `querykind.py` | 161 | What KIND of request this is, decided first, before any tool is picked (0 tokens, by meaning): help "how can I send a file to my phone?", "do you have the ability to con… |
| `ratelimit.py` | 172 | Thread-safe per-model token buckets for the Groq free tier (TPM + RPM). |
| `readlater.py` | 533 | Reading list ("read later"), 0 tokens: links saved in a real Excel sheet (~/Documents/KURAMA/read_later.xlsx). |
| `recipes.py` | 613 | Learned shortcuts and kept answers: KURAMA gets cheaper and more right every day from how its replies went. |
| `registry.py` | 465 | Tool registry: `@tool(group=..., safety=..., description=...)` on a plain function -> a LangChain StructuredTool (compact JSON schema from type hints + docstring, group … |
| `reminders.py` | 258 | P9b reminders and scheduled commands (SQLite `schedules`), shared by the schedule tools, the fast path and the scheduler worker. |
| `remotedesk.py` | 204 | Remote desktop (RustDesk): start it with unattended access and report the ID + password, so you can control the whole laptop screen from your phone's RustDesk app. |
| `reset.py` | 195 | Clearing and resetting KURAMA, in layers (personal facts are kept unless you fully reset): clear_chat : forget the current conversation (chat history + rolling summary),… |
| `results.py` | 26 | Typed tool results: a tool can return `Reply(text, paths=[...], ...)` instead of a plain string. |
| `rewrite.py` | 335 | Rewrite the selected text in place, in any app: select text, say "make this formal" / "fix grammar" / "translate to Nepali" / "shorten this", and the new text replaces t… |
| `router.py` | 288 | Tool-group router: keyword rules first, fast-tier classifier only for unmatched commands. |
| `safety.py` | 316 | Safety gate for tool calls: safe -> run, confirm -> needs the user's yes, blocked -> refuse. |
| `selfindex.py` | 158 | KURAMA's knowledge of its own tools, built from the code itself (never a hand-kept list that goes stale): for each tool, what it does (its description), how it works (it… |
| `selfknow.py` | 173 | KURAMA's knowledge about itself (docs/kurama_self.md) + the owner password gate for sensitive parts. |
| `semantic.py` | 266 | Semantic router: picks tool groups by MEANING, not keywords (0 LLM tokens). |
| `sheets.py` | 66 | Small Excel sheets KURAMA keeps for the user (~/Documents/KURAMA/*.xlsx): editable by hand in LibreOffice, written atomically under a file lock (server and Telegram may … |
| `shellcheck.py` | 35 | Shell allowlist check (stdlib only, so tiny daemons can use it without importing the agent). |
| `slash.py` | 357 | Slash commands: one short word instead of a sentence = no routing, no LLM, 0 tokens. |
| `sound.py` | 31 | Short system sounds for alarms, timers and reminders (freedesktop sound theme via paplay; no Python audio). |
| `spelling.py` | 32 | Common slips fixed before a request is understood (0 tokens): real words used by mistake, which the typo fixer leaves alone because they ARE words ('remain me' -> remind… |
| `store.py` | 860 | SQLite store (stdlib sqlite3, WAL, thread-safe) for LLM/tool/routing logs and chat messages. |
| `stt.py` | 341 | Speech-to-text on Groq Whisper: STT_MODEL first, STT_FALLBACK on any error. |
| `study.py` | 197 | Timetable and daily quiz. |
| `style.py` | 103 | The owner's standing rules for how KURAMA answers ("from now on, keep your answers short", "always call me boss", "never use emojis"): kept in data/style.json until the … |
| `suggest.py` | 221 | Suggestions under the chat box and on the first screen: a big pool of things KURAMA can do (all answered by the 0-token fast path), picked at random so they change every… |
| `taskgraph.py` | 221 | Task graph (Phase 2 of the memory + multitasking rebuild): a planned request runs as STEPS with real inputs and outputs, not as separate mini-chats that pass each other … |
| `telesec.py` | 132 | Telegram security: a PIN for risky actions, plus a /lock switch. |
| `templates.py` | 137 | Ready-made answers (0 tokens) for questions that always get the same answer: small talk and the usual setup guides. |
| `tgformat.py` | 134 | Markdown made readable in Telegram (owner 11-06: "the .md file with tables is hard to read"): to_html(md) Telegram's HTML: headings and **bold** in bold, `code`, links, … |
| `tgtopics.py` | 181 | Telegram sections: KURAMA's messages sorted into topics of your own Telegram group instead of one long chat. |
| `timemachine.py` | 396 | Code time machine: silent snapshots of the projects you work on, so "what changed since it worked?" and "give me train.py from 2 hours ago" always have an answer, commit… |
| `todos.py` | 341 | To-do list: the tasks the user has to do (KURAMA's own SQLite table `todos`, 0 tokens). |
| `toolsmith.py` | 577 | Toolsmith (P7c): when no tool fits, KURAMA offers to build a small one, but ONLY after the user says yes. |
| `trace.py` | 235 | Request traces for improving KURAMA (see MONITORING.md): one row per request in data/traces.db. |
| `training.py` | 514 | Training Guard: launch or watch ML training runs (local or Google Colab) and report on them. |
| `tts.py` | 427 | Text-to-speech with edge-tts and sentence-level streaming. |
| `uiagent.py` | 731 | Screen agent: control any app's UI (tabs, buttons, menus, settings, typing) — cheapest path first. |
| `usage.py` | 130 | Token usage / API cost report (P7) from the llm_calls and routing logs. |
| `usersettings.py` | 268 | Settings the owner can change by voice or text ("make the speed test 30 seconds"). |
| `vault.py` | 127 | Lock a folder (or file) with a password: AES-256 encrypted, one file, the original removed; unlock restores it. |
| `videomaker.py` | 143 | Short videos, free: scenes of (picture + spoken line + caption) joined by ffmpeg into one MP4. |
| `voicecfg.py` | 68 | Voice settings the dashboard can change: the laptop's microphone volume (PulseAudio/PipeWire, pactl) and how easily the wake word triggers (kv 'wake_sensitivity'). |
| `wake.py` | 653 | Wake word without a wake-word model: "Hey KURAMA" to wake, "sleep KURAMA" to sleep. |
| `webwatch.py` | 97 | Website watcher: tell me when a page changes (exam results, college notices, a GitHub release, a price) (0 tokens). |
| `when.py` | 357 | Natural-language times for reminders/scheduled commands, parsed WITHOUT an LLM where possible. |
| `wifishare.py` | 122 | Send to phone over Wi-Fi: serve one file/folder on the LAN with a secret link + QR code. |
| `words.py` | 15 | Is it a real English word? |
| `workmem.py` | 332 | Working memory: the THINGS KURAMA made or touched in this conversation and the CHOICE it is waiting on. |
| `workspace.py` | 204 | Long tool results (file lists, search hits, reports) are saved in full as a small markdown file under data/outputs/results/. |
| `writer.py` | 195 | Long-document writer job: outline (1 structured call) -> sections (max ~1500 tokens each), appended progressively to data/outputs/<YYYYmmdd-HHMM>-<slug>.md. |
| `ytdl.py` | 358 | Video/audio downloader (yt-dlp): YouTube and 1000+ sites, any quality (1080p, 4K...) with sound, or MP3. |

#### `jarvis/core/intents/`: Instant commands, by area

| File | Lines | What it does |
|---|---|---|
| `__init__.py` | 1 | Zero-token fast-path intents, split by area (fastpath.py re-imports them all). |
| `base.py` | 108 | Shared pieces of the zero-token fast path: the Intent/FastResult types and small text helpers. |
| `control.py` | 282 | Fast-path intents for reminders, laptop power (shutdown/restart/sleep) and the clock. |
| `desktop.py` | 474 | Fast-path intents for the desktop: volume, brightness, media keys, DND, night light, power modes, alert mute, usage. |
| `files.py` | 317 | Fast-path intents for files and folders: open, search, list a folder, find, send to Telegram. |
| `media.py` | 432 | Fast-path intents that make things: music, video, audio, diagrams, charts, images. |
| `todo.py` | 622 | Fast-path intents for saved links, the to-do list, long goals and the reading list. |

#### `jarvis/tools/core/`: The few general tools the AI sees

| File | Lines | What it does |
|---|---|---|
| `__init__.py` | 1 | v2 general tools: the ~17 tools the AI sees (each one action-based; the specialised tools do the work). |
| `_hub.py` | 97 | v2 general tools: the ONLY tools the AI sees (about 17 instead of 133). |
| `apps.py` | 88 | open apps, websites and folders by name; close, force-kill, arrange windows, press keys (safe dispatcher). |
| `code.py` | 86 | help with the owner's coding: explain/fix an error, run tests, where was I, what changed, git status / commit, a new project, the Python environment, requirements.txt, n… |
| `create.py` | 36 | make things: a picture (optionally as the wallpaper or sent to Telegram), a long document/essay (background job), speech audio, a chart, a diagram, a short video (safe d… |
| `files.py` | 55 | list, find, read, write, move, copy, delete (asks first), make folders, organize, convert, lock. |
| `info.py` | 37 | quick facts: time (anywhere), date (also Nepali calendar), weather, calculator/units, contacts, where the phone or the laptop is (safe dispatcher). |
| `kurama.py` | 75 | about KURAMA itself: what it is and can do, rename it, its power mode, background jobs, clear the chat, pause alerts, remote desktop, make a new tool when nothing fits (… |
| `laptop.py` | 92 | every switch and setting of the laptop in one tool (sound, screen, radios, power, health). |
| `life.py` | 42 | the owner's personal trackers: money (spending, budget, report), habits, long goals, studies (timetable, notes, quiz, lecture recorder), the day's summary, token use (sa… |
| `media.py` | 37 | music and videos: play a song/artist/playlist, pause, resume, next, previous, stop, what's playing, YouTube, hand-gesture control, download a video (safe dispatcher). |
| `memory.py` | 65 | what KURAMA keeps for the user: remember / recall / forget facts, past conversations, saved links, the reading list, the user's own documents, the workspace (safe dispat… |
| `run_command.py` | 42 | run ONE terminal command on the laptop. |
| `run_python.py` | 36 | run a short Python snippet on the laptop (for calculations, data, files, anything no tool does). |
| `schedule.py` | 36 | reminders (alerts at a time), alarms, timers, the stopwatch, scheduled commands; list, cancel, move, rename. |
| `telegram.py` | 33 | send a message, a file (by path OR by name: it is found on all disks), or the latest thing made, to the owner's own Telegram. |
| `text.py` | 51 | work on what the user selected or what is on screen: explain, meaning, translate, improve, summarize, reply, write code; read the screen (OCR); clipboard history; dictat… |
| `todo.py` | 41 | the user's to-do list (tasks they have to do), separate from reminders (alerts at a time). |
| `web.py` | 34 | answers from the internet: live results (sports, news, prices, today's facts), search, read a web page or the page open in the browser, Wikipedia, watch a page for a wor… |

#### `jarvis/tools/general/`: The real tools (one file each)

| File | Lines | What it does |
|---|---|---|
| `__init__.py` | 1 | Tool package: one file per tool, auto-discovered by jarvis.core.registry. |
| `_apps.py` | 343 | Shared helpers for open/close/focus app tools (not a tool): a cached index of .desktop files, fuzzy matching of spoken app names, names the user taught ("browser" = Brav… |
| `_desk.py` | 45 | Shared GNOME helpers for the P9a desktop tools (not a tool): gsettings get/set through _sys.run (so tests never touch the real settings), Do Not Disturb state and on/off… |
| `_files.py` | 96 | Shared helpers for the file tools (not a tool): path resolution, safe roots, trash. |
| `_geo.py` | 143 | Shared helpers for weather/time tools (not a tool): a tiny TTL cache, JSON GET with a timeout, and the free Open-Meteo geocoder (no API key) with spelling fallbacks ("Ne… |
| `_sys.py` | 120 | Shared helpers for the P5b desktop tools (not a tool): find a CLI with shutil.which (clear install hint when missing), run a fixed argv without a shell, pactl mute state… |
| `_tg.py` | 11 | Shared Telegram sharing check (not a tool). |
| `_web.py` | 120 | Shared helpers for the web tools: one lazy httpx client, TTL cache, HTML -> text (lxml or stdlib). |
| `about_me.py` | 17 | the assistant's knowledge about itself (docs/kurama_self.md); protected topics need the password (safe). |
| `add_reminder.py` | 19 | remind the user at a time, once or repeating (safe). |
| `add_watchdog_target.py` | 23 | let the crash watchdog keep a dev server alive (confirm; allowlisted binaries only). |
| `app_control.py` | 50 | drive the app on screen — shortcuts, keys, typing, click by name, or a free-form task (safe; risky clicks like send/delete/pay ask first). |
| `app_name.py` | 43 | the owner's own words, kept forever: a name for an app ("when I say browser, open Brave": works inside any sentence) or words for a whole command ("when I say good night… |
| `ask_knowledge.py` | 30 | answer a question about the user's code/notes from the top indexed chunks (safe). |
| `audio.py` | 38 | speaker volume, speaker mute and microphone mute in one tool (safe). |
| `backup.py` | 28 | back up project folders to another drive with rsync (never deletes there, skips venvs/caches, checks itself), weekly and when the drive is plugged in (safe). |
| `battery_status.py` | 51 | battery percentage, charging state, time left and health (upower). |
| `brightness.py` | 59 | get, set or step the screen backlight via brightnessctl (safe, no sudo). |
| `calculate.py` | 127 | safe math and common unit conversions, no LLM, no network (safe). |
| `cancel_job.py` | 21 | stop a running background job by id or title words (safe). |
| `cancel_schedule.py` | 16 | cancel a reminder / scheduled command by id or words (safe). |
| `claude_code.py` | 51 | watch Claude Code for the owner while they are away (core/claudewatch.py): on / off, status (with a screenshot on the phone), report, answer its permission question (yes… |
| `cleanup.py` | 21 | clean RAM (top RAM/CPU apps + KURAMA's idle memory), storage (self-rebuilding caches, old Trash) or KURAMA (its old logs, caches, temp files) — only safe things, 0 token… |
| `cleanup_scan.py` | 51 | the old disk report. |
| `clipboard.py` | 42 | read, write or show the history of the clipboard in one tool (safe). |
| `clipboard_history.py` | 61 | what was copied in the last 24 h (the clipboard_watch worker records every copy; SQLite, only on this laptop): list, search by words, 'N minutes ago', copy an old item b… |
| `close_app.py` | 39 | close an app's windows gracefully via wmctrl (safe: like clicking X, the app still asks about unsaved work; force-killing is kill_app, which needs a yes). |
| `code_to_file.py` | 315 | write code into the file open in VS Code (or a given path), like an editor assistant: "write a function that ... |
| `command_alerts.py` | 31 | tell me when long terminal commands finish (pip install, builds, scripts) (safe; turning it on or off asks first because it edits ~/.bashrc). |
| `contacts.py` | 33 | a name + phone number sheet (Excel, ~/Documents/KURAMA/contacts.xlsx): add, find, list, update, delete (safe). |
| `convert_currency.py` | 50 | live exchange rates (open.er-api.com, free, no key; cached 6 h) (safe). |
| `convert_file.py` | 51 | convert a file (or every file of a type in a folder) to another format, locally (safe). |
| `copy_path.py` | 33 | copy_path (P7c): copy a file or folder (asks first). |
| `daily_digest.py` | 16 | the day's digest on demand: conversations, jobs, alerts, notes, tokens, git, weather (safe). |
| `delete_skill.py` | 15 | delete_skill (P7c): remove a saved skill (asks first). |
| `delete_to_trash.py` | 20 | delete_to_trash (P7c): move a file or folder to the trash with `gio trash` (asks first; never rm -rf). |
| `dictate.py` | 22 | voice typing into any app (speech -> text typed at the cursor) until 'stop dictation' (safe). |
| `disk_cleaner.py` | 45 | what fills the disk (incl. |
| `do_not_disturb.py` | 27 | GNOME Do Not Disturb (org.gnome.desktop.notifications show-banners). |
| `download_file.py` | 25 | download a big file now or tonight, resuming if the connection breaks; tells you when done (safe). |
| `echo_time.py` | 35 | current date and time, locally or in any city/country (geocoded timezone; safe). |
| `expenses.py` | 57 | money tracker in ~/Documents/KURAMA/expenses.xlsx (add, reports, budgets, bills), 0 tokens (safe). |
| `explain_self.py` | 97 | KURAMA explains itself from facts, not guesses: what it just did (the last request's real record: the tools it ran, their arguments and results), how those tools work (t… |
| `find_and_send.py` | 155 | find a file by name anywhere on the laptop (home + every mounted disk) and send it to the user's Telegram. |
| `find_capability.py` | 29 | which of the assistant's tools fit a task or problem: by meaning (local model, core/selfindex.py), else by word match; with a way to ask for each (0 tokens) (safe). |
| `find_my_phone.py` | 38 | open Google Find My Device (or Find My iPhone) in the browser to locate/ring/lock the phone (safe). |
| `focus_app.py` | 19 | bring an open app's window to the front via wmctrl (safe). |
| `focus_mode.py` | 88 | a timed focus session: Do Not Disturb on, optional closing of config.FOCUS_CLOSE apps, and a timer that turns DND back off and notifies "focus session done". |
| `folder_lock.py` | 46 | lock a folder/file with a password (AES-256, typed in a box on the laptop) or unlock it (confirm). |
| `forget.py` | 35 | delete remembered notes (the last one, all, or one by id) or one learned fact about the user (confirm). |
| `generate_image.py` | 171 | make an image from a text prompt (the user's image workers, then Pollinations) as a background job (safe). |
| `gesture_control.py` | 70 | start/stop the user's hand-gesture media/YouTube control (camera + OpenCV + MediaPipe) (safe). |
| `get_date.py` | 23 | today's date and weekday, in Bikram Sambat (default) or Gregorian/AD (safe). |
| `goals.py` | 31 | long tasks that last weeks or months: countdowns, daily check-ins, progress log, report (safe). |
| `habits.py` | 29 | daily habits with streaks in ~/Documents/KURAMA/habits.xlsx, 0 tokens (safe). |
| `help_me.py` | 37 | what KURAMA can do, by area, with real ways to ask (from the tools' own examples), or for one need: the closest tools by meaning (core/selfindex.py). |
| `index_folder.py` | 28 | (re)index a folder of code/notes for search_knowledge/ask_knowledge, as a background job (safe). |
| `install_app.py` | 26 | install, remove or update apps (apt/snap/flatpak, auto-picked); Ubuntu asks the password (confirm). |
| `internet_doctor.py` | 39 | why the internet is slow or down (Wi-Fi, router, provider, DNS, web), speed test, reconnect, switch DNS, and "tell me when it's back" (safe; changing the network asks fi… |
| `job_result.py` | 32 | where a background job saved its output, plus the first lines (safe). |
| `jobs.py` | 61 | list, check, cancel or resume background jobs in one tool (safe). |
| `kaggle_train.py` | 32 | run a training script/notebook/project on Kaggle's free GPU, watch it, download results (safe). |
| `kill_app.py` | 123 | force-quit an app's processes (psutil). |
| `kurama_settings.py` | 35 | change KURAMA's own settings from a fixed safe list (core/usersettings.py): the speed test's length, reply length, voice timing, Telegram photo size, alert levels... |
| `laptop_doctor.py` | 72 | why is my laptop slow? |
| `laptop_guard.py` | 35 | arm/disarm the anti-theft guard, see where the laptop is, take a webcam photo now (safe). |
| `laptop_toggle.py` | 123 | the laptop's quick switches: Wi-Fi, Bluetooth, airplane mode, power mode, screen off. |
| `learned_shortcuts.py` | 46 | what KURAMA learned from 👍 / 👎 and clean repeats (0-token shortcuts, kept answers): list, forget (safe). |
| `lecture.py` | 34 | record a class (microphone, or the laptop's sound for an online class), stop it and get a transcript in ~/Notes/Lectures (background job), or a summary of the last one (… |
| `list_jobs.py` | 14 | what KURAMA is working on in the background (safe). |
| `list_schedules.py` | 11 | pending reminders and scheduled commands (safe). |
| `list_skills.py` | 16 | list_skills (P7c): the small tools KURAMA built and saved. |
| `list_watches.py` | 16 | active process/log watches and recently finished ones (safe). |
| `list_windows.py` | 21 | the open windows (title and app) from wmctrl (safe, read-only). |
| `live_search.py` | 27 | real-time answers — live/last/next game scores (ESPN), minutes-fresh news (Google News), or a short answer to a current-events question built only from fresh sources (sa… |
| `location_history.py` | 39 | show where the laptop (or phone) has been — a text summary and a map opened in the browser (safe). |
| `lock_screen.py` | 24 | lock the desktop session (loginctl, then gnome-screensaver-command, then xdg-screensaver). |
| `make_audio.py` | 34 | text -> MP3 (edge-tts, free) from the selection, a file, a web page, the newest workspace document or typed words (safe). |
| `make_chart.py` | 41 | charts (PNG, several views) from my spending, a CSV/Excel/JSON file or a data link; background job (safe). |
| `make_diagram.py` | 32 | a picture of a project (from its README only), of steps (flowchart) or of a Python file's calls, 0 tokens (safe). |
| `make_folder.py` | 32 | make_folder (P7c): create a folder. |
| `make_tool.py` | 18 | make_tool (P7c): offer to build a small tool when no other tool fits. |
| `make_video.py` | 47 | a short narrated video (pictures + voice + captions) about a topic, from the user's script, or a slideshow of a folder's pictures; ffmpeg, free; background job (safe). |
| `media_control.py` | 75 | play/pause/next/previous/stop/status of the active media player via playerctl (safe). |
| `mic_mute.py` | 22 | mute, unmute or toggle the microphone via pactl on @DEFAULT_SOURCE@ (safe). |
| `move_path.py` | 45 | move_path (P7c): move or rename a file or folder. |
| `music.py` | 57 | play music without the browser (YouTube sound via mpv + yt-dlp), playlists, local files, controls, 0 tokens (safe). |
| `mute_alerts.py` | 74 | pause one kind of KURAMA alert (RAM/resource, location, jobs...) or all of them for a while, on the laptop AND on Telegram. |
| `mute_audio.py` | 22 | mute, unmute or toggle the speakers via pactl on @DEFAULT_SINK@ (safe). |
| `nepal_docs.py` | 38 | answers about Nepal's laws, legal processes, government services and fees, and Nepal general knowledge (citizenship, passport, marriage and divorce, traffic rules and fi… |
| `night_light.py` | 44 | GNOME Night Light on/off and colour temperature (1700-4700 K). |
| `open_app.py` | 28 | launch an installed Ubuntu app by its spoken name (fuzzy .desktop match; safe). |
| `open_folder.py` | 34 | open a folder in the file manager by name (fuzzy), e.g. |
| `open_path.py` | 62 | open a file or folder in VS Code (default), the file manager or its own app. |
| `open_url.py` | 94 | open a URL or a known site (youtube, google, github, gmail...) in the browser (safe). |
| `organize_files.py` | 50 | rename + sort a messy folder by what is inside the files. |
| `page_summary.py` | 19 | what the page open in the browser right now is about; 'yes' = a detailed overview (safe). |
| `playlist.py` | 59 | play a named playlist from config.PLAYLISTS (URL -> browser; local folder -> mpv if installed, else the default player via xdg-open). |
| `power_mode.py` | 26 | switch how much of KURAMA runs (full / best AI / normal / basic / low RAM / laptop only / no AI) (safe). |
| `power_off.py` | 27 | shut down, restart or log out (confirm: always asks yes/no first). |
| `quiz.py` | 30 | questions made once from your notes, asked again with spaced repetition (safe; making costs ~800 tokens, asking and grading are free). |
| `read_clipboard.py` | 24 | the current clipboard text, truncated (xclip; safe, read-only). |
| `read_later.py` | 28 | my list = to-dos + links to read later (Excel sheet), with tags and optional due times (safe). |
| `read_text.py` | 22 | OCR. |
| `read_webpage.py` | 62 | fetch a public web page (6 s timeout, size cap) and return its readable text (safe). |
| `read_workspace.py` | 21 | read back what is in the dashboard's Workspace card (the latest search result, answer, list...) so KURAMA can summarize it or answer from it (safe). |
| `recall.py` | 52 | read back remembered notes (all, last, or matching a query) or, with which="profile", the facts KURAMA learned about the user (safe). |
| `recall_session.py` | 16 | what we talked about in past sessions (last / yesterday / a date / a topic), zero LLM (safe). |
| `remember.py` | 21 | save a short note the user dictates ("remember 1234") in SQLite (safe). |
| `remote_desktop.py` | 15 | start RustDesk remote control of the laptop and point to Telegram for the password, or stop it (safe). |
| `reset_kurama.py` | 26 | clear the conversation, or reminders+caches, or everything (keeps password + settings). |
| `resource_status.py` | 12 | KURAMA's own health (RAM, swap, CPU, disk, KURAMA RSS, workers). |
| `resume_job.py` | 16 | continue an interrupted writing job from its next section (safe). |
| `run_training.py` | 28 | start a training command in the background and guard it (confirm: it runs a program). |
| `saved_links.py` | 24 | named links the user keeps and asks for later ('give me my Facebook link') (safe). |
| `scan_qr.py` | 23 | read QR codes / barcodes on the screen, a dragged area, a copied image or a picture (0 tokens, safe). |
| `schedule_command.py` | 19 | run a KURAMA command later or repeatedly (confirm: it acts unattended). |
| `schedules.py` | 37 | list or cancel reminders and scheduled commands in one tool (safe). |
| `screenshot.py` | 61 | capture the full screen, the active window or a selected area to ~/Pictures/Screenshots/jarvis-YYYYmmdd-HHMMSS.png (gnome-screenshot, else scrot). |
| `search_knowledge.py` | 34 | hybrid (BM25 + vector) search over the user's indexed code and notes (safe). |
| `send_file_telegram.py` | 366 | send_file_telegram (P7c): send a local file to the user's Telegram (sendPhoto / sendDocument). |
| `send_last_result.py` | 70 | send the latest thing KURAMA made to the user's Telegram: the picture it just generated, the poem/essay it wrote, or the full list from the last search. |
| `send_message_telegram.py` | 29 | send_message_telegram (P7c): send text (e.g. |
| `set_alarm.py` | 18 | an alarm at a time ("6 am", "tomorrow at 7", "every weekday at 6:30") that rings for a while and also reaches the phone. |
| `set_my_name.py` | 16 | rename the assistant (default KURAMA); it answers to the new name from now on (safe). |
| `set_theme.py` | 84 | switch GNOME between light and dark mode without touching icon/cursor themes. |
| `set_timer.py` | 33 | a countdown that rings (sound + notification) when it ends; kept in the schedule so it survives a restart and can be listed/cancelled like reminders. |
| `set_wallpaper.py` | 108 | set the desktop wallpaper from a path, a name, or the next/random image in config.WALLPAPER_DIRS; sets both picture-uri and picture-uri-dark (light and dark mode). |
| `share_wifi.py` | 54 | show a QR code of the current Wi-Fi so a phone/guest can scan to join (0 tokens) (safe). |
| `shutdown_timer.py` | 122 | shut down / restart the laptop later ("after 2 min", "in 1 hour", "after 90 minutes", "at 11 pm"), cancel it, or say when it is set. |
| `skills.py` | 37 | list, run or delete the tools KURAMA built and saved (safe; deleting asks first). |
| `snap_window.py` | 90 | snap the active or a named window to the left/right half, maximize, minimize or restore it (wmctrl + xdotool; the work area comes from `wmctrl -d`, else the display size… |
| `status_now.py` | 14 | one answer to "what's going on?": training (epochs, accuracy, ETA), jobs, downloads, recording, page watches, guard, what's next, the laptop and recent alerts (safe, 0 t… |
| `stop_watch.py` | 24 | stop one watch (by number or name) or all of them (safe). |
| `stopwatch.py` | 52 | start / stop / lap / reset / status, kept in the database so it survives restarts. |
| `study_notes.py` | 27 | quick study notes filed by subject and date (~/Notes/<Subject>/), and showing them again (safe). |
| `suspend_computer.py` | 15 | put the computer to sleep with `systemctl suspend` (confirm). |
| `text_assist.py` | 86 | one tool for highlighted text/code in any app and code in VS Code: explain, meaning (Nepali), translate, improve/fix (in place), write code at the cursor, explain a file… |
| `tidy_downloads.py` | 30 | sort ~/Downloads into Documents/Images/Videos/... |
| `timetable.py` | 23 | save your class schedule once, then today/tomorrow/week/next class, with a heads-up before each class (safe; 0 tokens after it is saved). |
| `token_usage.py` | 18 | LLM tokens, calls, budget %, fast-path savings, STT seconds and cost for a period (safe). |
| `training.py` | 140 | Training Guard. |
| `use_skill.py` | 16 | use_skill (P7c): run a saved toolsmith skill (zero generation tokens). |
| `video_download.py` | 39 | download a YouTube (or other site) video in a chosen quality with sound, or as MP3 (safe). |
| `volume.py` | 64 | get, set (0-100) or step the speaker volume via pactl on @DEFAULT_SINK@ (safe). |
| `watch_log.py` | 22 | tail a log file and alert on errors / progress / completion (safe). |
| `watch_process.py` | 21 | alert when a PID or named process exits, with its runtime (safe). |
| `watchdog_status.py` | 22 | crash-watchdog targets and whether they are up (safe). |
| `weather.py` | 108 | current weather and a short forecast for any place via Open-Meteo (free, no key; safe). |
| `web_search.py` | 91 | top web results (title, URL, one-line snippet). |
| `web_watch.py` | 42 | tell me when a web page changes: exam results, college notices, releases, prices (safe, 0 tokens). |
| `wifi_share.py` | 28 | send a file/folder to the phone over the local Wi-Fi (link + QR, no internet, no size limit) (safe). |
| `wikipedia.py` | 104 | short summary of a person/topic from the free Wikipedia REST API, with MediaWiki opensearch + full-text search fallbacks for fuzzy names ("Cariminati" -> CarryMinati). |
| `window.py` | 48 | list open windows, switch to one, or snap/maximize/minimize one (safe). |
| `write_clipboard.py` | 26 | put text on the clipboard (xclip) and keep it in KURAMA's own history (safe). |
| `write_document.py` | 18 | start a long writing job (essay, article, story, report, code) in the background (safe). |
| `write_file.py` | 38 | write_file (P7c): write a text file (asks first only to overwrite an existing one). |
| `youtube.py` | 88 | play the first YouTube video for a query, open search results, or control the YouTube browser tab (pause/next/fullscreen via wmctrl + xdotool keys k, shift+n, f). |

#### `jarvis/tools/interactive/`: More real tools (code, files)

| File | Lines | What it does |
|---|---|---|
| `__init__.py` | 1 | Tool package: one file per tool, auto-discovered by jarvis.core.registry. |
| `_proc.py` | 96 | Shared helpers for the interactive tools (not a tool): allowlisted subprocess runs with a timeout and cancel support, folder resolution, and a guarded git runner (never … |
| `_secrets.py` | 182 | Shared secret detection for review_code (not a tool). |
| `code_nav.py` | 42 | jump to the real code of the highlighted function/class (project or installed library), 0 tokens (safe). |
| `code_tidy.py` | 20 | format / check / safely fix a code file on this laptop with ruff, 0 tokens (safe; backups kept). |
| `decode_text.py` | 21 | decode / prettify the highlighted text locally (JSON, JWT, base64, URL, timestamp...), 0 tokens (safe). |
| `dependency_doctor.py` | 205 | check a Python project's declared dependencies (safe). |
| `env_doctor.py` | 88 | CPU-only environment check (python, venv, pip, disk, RAM/swap, CLIs, Groq key). |
| `find_files.py` | 240 | find files by name (fdfind) or by content (rg) under a folder, compactly (safe). |
| `fix_error.py` | 37 | explain an error (pasted, or what's on the clipboard) and remember how you fixed it (safe). |
| `generate_requirements.py` | 235 | build requirements.generated.txt from a project's imports (safe; no LLM). |
| `git_branch.py` | 28 | create (and switch to) or switch to a git branch (confirm). |
| `git_change.py` | 36 | commit, or create/switch a branch (confirm: changes the repo; never pushes). |
| `git_commit.py` | 63 | commit staged changes with a given or auto-generated message (confirm). |
| `git_diff_summary.py` | 29 | `git diff --stat` for staged and unstaged changes (safe). |
| `git_info.py` | 34 | read-only git status, recent commits or a change summary (safe). |
| `git_log.py` | 24 | the last N commits of a repo, one line each (safe). |
| `git_status.py` | 65 | branch, ahead/behind and a compact changed-files summary of a git repo (safe). |
| `list_folder.py` | 96 | what's inside one or more folders, as a numbered list (folders first, then files with size and date), so the user can pick one: "send 3" / "send all" (handled by find_an… |
| `notebook_to_script.py` | 160 | convert a Jupyter notebook to a .py script next to it (safe; no LLM). |
| `python_env.py` | 84 | check a Python environment, or install a missing module into the RIGHT project venv (safe; installing asks first and warns about heavy packages like torch). |
| `review_code.py` | 228 | AI review of the staged diff, a file or the last commit (safe, token-cheap). |
| `run_tests.py` | 116 | run pytest -q in a project and report counts plus the first failure (safe). |
| `scaffold_project.py` | 211 | create a new Python project skeleton (src layout, tests, README...) (confirm). |
| `time_machine.py` | 67 | snapshots of your code you never have to think about. |
| `where_was_i.py` | 103 | back to a project after a break: what you were doing, what's unfinished, what broke last, and what to do next (safe; can open the project in VS Code). |

#### `jarvis/memories/`: Kinds of memory (one file each)

| File | Lines | What it does |
|---|---|---|
| `__init__.py` | 2 | Memory sources, one file each (see jarvis/core/memories.py for the contract). |
| `documents.py` | 13 | the owner's own notes and code, indexed for hybrid search (FTS5 + vectors). |
| `links.py` | 14 | named links the owner saved ('the link for Claude Code'). |
| `notes.py` | 16 | what the owner asked KURAMA to remember ('remember that my locker code is...'). |
| `profile.py` | 19 | facts about the owner (name, city, likes...), learned from what they said. |

#### `jarvis/agents/`: Agents

| File | Lines | What it does |
|---|---|---|
| `__init__.py` | 194 | KURAMA's focused helpers, OFF until the owner turns one on (Settings pill / "start coding agent" / /agent coding). |

#### `jarvis/agents/coding/`: The coding agent's link inside KURAMA (crash fixes, the ChatGPT bridge)

| File | Lines | What it does |
|---|---|---|
| `__init__.py` | 99 | The coding agent (owner: "separate from KURAMA, only when I turn it on"). |
| `blocks.py` | 129 | Read code answers (from Groq, or pasted from ChatGPT / Gemini / Claude) as file changes: each fenced block names its file ('# file: app/main.py' first line, a ```python … |
| `bridge.py` | 116 | The big-AI bridge (0 tokens): for work too big for the free Groq models, KURAMA writes ONE ready prompt for ChatGPT / Gemini / Claude on the web (the task, the last erro… |
| `changes.py` | 146 | Change sets: every file change the coding agent makes is first SHOWN (a diff in the workspace + one line in the chat) and waits for a yes; applying it keeps the old vers… |
| `fixer.py` | 104 | Crash -> fix (owner: no more copy-pasting errors to ChatGPT). |
| `project.py` | 133 | New project in one sentence (owner: a short plan first, then small, effective code; it knows where to put it). |
| `templates.py` | 70 | Project templates (0 tokens): the kind of project is picked by MEANING (local model), the template gives the files, their purpose, requirements and how to run it; the AI… |
| `terminal.py` | 70 | The VS Code terminal while the coding agent is on: the editor-link extension reports every command that FAILED (command, folder, exit code, the last part of its output). |
| `tools.py` | 119 | The coding agent's one tool for the AI (group coding_agent: offered only while the agent is on). |

#### `coder/`: The coding agent (its own project: plan, build, check, fix)

| File | Lines | What it does |
|---|---|---|
| `__init__.py` | 39 | KURAMA's coding agent: its own project (owner, 11-06: "a separate folder and backend, so it can be changed or upgraded on its own; memory shared, its own working process… |
| `api.py` | 413 | What KURAMA calls (jarvis/agents/coding/tools.py): start(request) a new project / file / feature: understood at once (0 tokens), a question if it can't tell, else the pl… |
| `budget.py` | 18 | What a run will cost, before it is spent: each file's output by its difficulty, plus what it is shown (the plan, the files it uses), plus a reserve for fixes. |
| `connect.py` | 158 | Do the files fit together? |
| `engine.py` | 217 | The two background jobs of a run, each a small LangGraph graph whose steps show as a checklist in KURAMA's Progress section: plan job understand (done before, 0 tokens) … |
| `fixloop.py` | 83 | Fix what the checks found, cheaply: each problem goes with only its file (cut around the line when the file is long), the plan's short brief and the other files' names; … |
| `github.py` | 103 | A starter project from GitHub (only when the owner asks: "from GitHub", "use a template"). |
| `link.py` | 94 | The ONLY place the coding agent touches KURAMA: background jobs, the Progress section's checklist, the folder open in VS Code, opening a folder, the workspace, Telegram. |
| `memory.py` | 110 | Per-project memory, in the project itself: .kurama/project.md (what it is, the stack, how to run it, each file's job, the decisions made) and TODO.md (what is left). |
| `models.py` | 17 | The AI calls of the coding agent, through KURAMA's LLM layer (same keys, same shared Groq rate limit, logged). |
| `onboard.py` | 119 | Learning a project KURAMA didn't build, once, within the token budget: 1. |
| `planner.py` | 113 | The plan, in ONE call: the files (each with its job, the files it uses and how hard it is), how they connect, the command to run it and what is left for later. |
| `preview.py` | 222 | Web projects, seen running (0 tokens unless a look is asked for): server a tiny local server for the project (http://127.0.0.1:<port>/) that adds a reporter to every pag… |
| `repomap.py` | 93 | A project's map without the AI: its files, and in each the functions, classes, exports and local imports. |
| `review.py` | 100 | Looking at changes, three ways (0 tokens unless said): diffs the last build's changed files side by side in VS Code (`code --diff old new`), so each can be kept or put b… |
| `run.py` | 75 | One run's state and its temporary memory: data/coder/runs/<id>/ holds the plan, the backups (for undo) and notes while it works; on success only the undo record is kept … |
| `safety.py` | 91 | Nothing the agent does is lost: before a file changes its old text is kept in the run's folder, new files and folders are listed, and undo puts it all back (new files go… |
| `scaffold.py` | 80 | The starting files, made without the AI (0 tokens), so the structure is industry standard: react `npm create vite` (React + TypeScript template: Vite, ESLint, tsconfig) … |
| `settings.py` | 24 | The coding agent's own settings (KURAMA's config only for shared paths). |
| `testing.py` | 112 | "write tests for this project" (pytest files for its Python modules, one call each, checked and run) and "make the tests pass" (run them, send only the failures and the … |
| `understand.py` | 75 | What to build and where, without the AI: the stack from the words (react, pygame, html/css/js, fastapi...), the folder ("here / this folder / in VS Code" = the project o… |
| `verify.py` | 85 | Check the written files without the AI and without running the program (0 tokens): Python ruff format (tidy), then compile + ruff's error rules (syntax, undefined names,… |
| `writer.py` | 104 | Each planned file, one call each: the writer sees the whole plan (so names and connections agree), the files this one uses (already written, cut to settings.FILE_CONTEXT… |

#### `jarvis/workers/`: Background helpers

| File | Lines | What it does |
|---|---|---|
| `__init__.py` | 1 | Background workers (P6): tiny daemons run by one supervisor process (`python -m jarvis.workers`). |
| `__main__.py` | 10 | python -m jarvis.workers [--only a,b] [--list] |
| `base.py` | 145 | Worker base class: a tiny daemon = tick() every interval_s on its own thread. |
| `brief.py` | 25 | Morning brief worker: the first unlock / wake-up of the day -> brief.deliver(). |
| `clipboard_watch.py` | 172 | Copy history worker ("clipboard_watch"): every text the user copies (Ctrl+C in any app) goes to the SQLite clipboard table, so "what did I copy 10 minutes ago?" works. |
| `crash_watchdog.py` | 261 | Crash watchdog (worker "crash_watchdog"): keep configured dev servers alive. |
| `daily_digest.py` | 49 | Daily digest worker (P7): once per day at config.DIGEST_TIME, build the digest (zero-LLM template by default) and send it via notify() (desktop + Telegram + alerts table… |
| `guard.py` | 22 | Laptop guard worker: while armed, photo + location to Telegram on unlock, wrong password or wake-up. |
| `inproc.py` | 70 | The background workers inside the server process (config.WORKERS_IN_SERVER, default on). |
| `location_tracker.py` | 53 | Location tracker worker (lightweight): records the laptop's location to build a history/trail. |
| `process_watch.py` | 512 | Training Guard worker ("process_watch"): watches training runs and long processes, alerts desktop + Telegram. |
| `resource_guard.py` | 189 | Resource guard (worker "resource_guard") and the snapshot behind the resource_status tool. |
| `scheduler.py` | 82 | Scheduler worker (P9b): every config.SCHEDULER_INTERVAL_S (15 s) fire due reminders / scheduled commands (reminders.run_due), plus a heads-up config.REMINDER_LEAD_S (10 … |
| `status.py` | 78 | Read the supervisor's status file (data/workers.json) so tools can tell what is running. |
| `supervisor.py` | 186 | run the enabled workers in ONE process. |
| `telegram_bot.py` | 711 | Telegram remote control (worker "telegram_bot"): long-polling getUpdates over plain httpx. |
| `timemachine.py` | 28 | Time machine worker: every TIMEMACHINE_EVERY_S, snapshot the protected projects that changed (0 tokens). |

#### `frontend/`: The window (what you see)

| File | Lines | What it does |
|---|---|---|
| `api.js` | 151 | Thin client for the KURAMA API (/api/v1/*). |
| `app.js` | 2998 | KURAMA UI controller. |
| `config.js` | 44 | Frontend configuration. |
| `dust.js` | 186 | KURAMA background field: ONE shared, half-resolution canvas behind the panels. |
| `money.js` | 72 | The Money window (click the Money & habits card): pick a date or a range (and a category), see every expense in it, totals by category against the budget, and delete a w… |
| `orb.js` | 652 | KURAMA orb v3: a layered hologram core on Canvas 2D, budgeted for an always-on 8 GB laptop. |
| `progress.js` | 91 | The Progress section (main window card + mini window panel): everything running now, each with its own bar — background jobs (writing, downloads, file sends, images, sca… |
| `slash.js` | 58 | Slash-command suggestions for the chat box: type "/" and pick a command (0 tokens, no routing). |
| `voice.js` | 552 | Browser-side voice: microphone (with the browser's echo cancellation), recorder, sentence splitter, a sentence-by-sentence TTS player (fetches /tts, decodes, plays gaple… |

#### `scripts/`: Scripts (start, stop, the desktop window, reports)

| File | Lines | What it does |
|---|---|---|
| `atspi_dump.py` | 81 | Dump the clickable/typeable elements of the ACTIVE window via AT-SPI, as JSON on stdout. |
| `claude_hook.py` | 58 | Claude Code hook for KURAMA's Claude Code watch (jarvis/core/claudewatch.py). |
| `file_guide.py` | 86 | Write the "every file" guide into LEARN.md (between <!-- FILES:START --> and <!-- FILES:END -->): each source file, its size and what it does, taken from the docstring a… |
| `gen_tool_guide.py` | 381 | Write the 'Every tool in detail' part of COMMAND.md from the live tool registry (run after adding tools): venv/bin/python scripts/gen_tool_guide.py What each tool does, … |
| `gesture_runner.py` | 136 | Runs the user's YouTube/media hand-gesture module (config.GESTURE_DIR/main.py) unchanged, in its own venv. |
| `kurama_fm.py` | 162 | What the Files app (Nautilus) shows: run with the SYSTEM python3 (PyGObject: Gdk, Gio, Atspi). |
| `kurama_glass.py` | 138 | KURAMA glass: the blur behind the mini chat panel, done by GNOME's Blur my Shell extension (0 KURAMA RAM/CPU). |
| `kurama_wallpaper.py` | 1806 | KURAMA live wallpaper: a native GTK + WebKit window that sits behind every window (X11). |
| `new_plugin.py` | 148 | Write the skeleton of a new tool, memory source or agent, plus its test (`make new-tool NAME=x` etc.). |
| `tool_round.py` | 241 | One test round over a SAMPLE of KURAMA's tools, asked the way the owner asks (typos, short, loose grammar). |
| `trace_report.py` | 324 | KURAMA monitoring report from data/traces.db (see MONITORING.md). |
| `wifi_share_server.py` | 128 | Tiny LAN file server for KURAMA's Wi-Fi share (stdlib only, run as its own process). |

<!-- FILES:END -->): each source file, its size and what it does, taken from the docstring a… |
| `gen_tool_guide.py` | 381 | Write the 'Every tool in detail' part of COMMAND.md from the live tool registry (run after adding tools): venv/bin/python scripts/gen_tool_guide.py What each tool does, … |
| `gesture_runner.py` | 136 | Runs the user's YouTube/media hand-gesture module (config.GESTURE_DIR/main.py) unchanged, in its own venv. |
| `kurama_fm.py` | 162 | What the Files app (Nautilus) shows: run with the SYSTEM python3 (PyGObject: Gdk, Gio, Atspi). |
| `kurama_glass.py` | 138 | KURAMA glass: the blur behind the mini chat panel, done by GNOME's Blur my Shell extension (0 KURAMA RAM/CPU). |
| `kurama_wallpaper.py` | 1806 | KURAMA live wallpaper: a native GTK + WebKit window that sits behind every window (X11). |
| `new_plugin.py` | 148 | Write the skeleton of a new tool, memory source or agent, plus its test (`make new-tool NAME=x` etc.). |
| `tool_round.py` | 241 | One test round over a SAMPLE of KURAMA's tools, asked the way the owner asks (typos, short, loose grammar). |
| `trace_report.py` | 324 | KURAMA monitoring report from data/traces.db (see MONITORING.md). |
| `wifi_share_server.py` | 128 | Tiny LAN file server for KURAMA's Wi-Fi share (stdlib only, run as its own process). |

<!-- FILES:END -->): each source file, its size and what it does, taken from the docstring a… |
| `gen_tool_guide.py` | 381 | Write the 'Every tool in detail' part of COMMAND.md from the live tool registry (run after adding tools): venv/bin/python scripts/gen_tool_guide.py What each tool does, … |
| `gesture_runner.py` | 136 | Runs the user's YouTube/media hand-gesture module (config.GESTURE_DIR/main.py) unchanged, in its own venv. |
| `kurama_fm.py` | 162 | What the Files app (Nautilus) shows: run with the SYSTEM python3 (PyGObject: Gdk, Gio, Atspi). |
| `kurama_glass.py` | 138 | KURAMA glass: the blur behind the mini chat panel, done by GNOME's Blur my Shell extension (0 KURAMA RAM/CPU). |
| `kurama_wallpaper.py` | 1806 | KURAMA live wallpaper: a native GTK + WebKit window that sits behind every window (X11). |
| `new_plugin.py` | 148 | Write the skeleton of a new tool, memory source or agent, plus its test (`make new-tool NAME=x` etc.). |
| `tool_round.py` | 241 | One test round over a SAMPLE of KURAMA's tools, asked the way the owner asks (typos, short, loose grammar). |
| `trace_report.py` | 324 | KURAMA monitoring report from data/traces.db (see MONITORING.md). |
| `wifi_share_server.py` | 128 | Tiny LAN file server for KURAMA's Wi-Fi share (stdlib only, run as its own process). |

<!-- FILES:END -->): each source file, its size and what it does, taken from the docstring a… |
| `gen_tool_guide.py` | 381 | Write the 'Every tool in detail' part of COMMAND.md from the live tool registry (run after adding tools): venv/bin/python scripts/gen_tool_guide.py What each tool does, … |
| `gesture_runner.py` | 136 | Runs the user's YouTube/media hand-gesture module (config.GESTURE_DIR/main.py) unchanged, in its own venv. |
| `kurama_fm.py` | 162 | What the Files app (Nautilus) shows: run with the SYSTEM python3 (PyGObject: Gdk, Gio, Atspi). |
| `kurama_glass.py` | 138 | KURAMA glass: the blur behind the mini chat panel, done by GNOME's Blur my Shell extension (0 KURAMA RAM/CPU). |
| `kurama_wallpaper.py` | 1806 | KURAMA live wallpaper: a native GTK + WebKit window that sits behind every window (X11). |
| `new_plugin.py` | 148 | Write the skeleton of a new tool, memory source or agent, plus its test (`make new-tool NAME=x` etc.). |
| `tool_round.py` | 241 | One test round over a SAMPLE of KURAMA's tools, asked the way the owner asks (typos, short, loose grammar). |
| `trace_report.py` | 324 | KURAMA monitoring report from data/traces.db (see MONITORING.md). |
| `wifi_share_server.py` | 128 | Tiny LAN file server for KURAMA's Wi-Fi share (stdlib only, run as its own process). |

<!-- FILES:END -->): each source file, its size and what it does, taken from the docstring a… |
| `gen_tool_guide.py` | 381 | Write the 'Every tool in detail' part of COMMAND.md from the live tool registry (run after adding tools): venv/bin/python scripts/gen_tool_guide.py What each tool does, … |
| `gesture_runner.py` | 136 | Runs the user's YouTube/media hand-gesture module (config.GESTURE_DIR/main.py) unchanged, in its own venv. |
| `kurama_fm.py` | 162 | What the Files app (Nautilus) shows: run with the SYSTEM python3 (PyGObject: Gdk, Gio, Atspi). |
| `kurama_glass.py` | 138 | KURAMA glass: the blur behind the mini chat panel, done by GNOME's Blur my Shell extension (0 KURAMA RAM/CPU). |
| `kurama_wallpaper.py` | 1806 | KURAMA live wallpaper: a native GTK + WebKit window that sits behind every window (X11). |
| `new_plugin.py` | 148 | Write the skeleton of a new tool, memory source or agent, plus its test (`make new-tool NAME=x` etc.). |
| `tool_round.py` | 241 | One test round over a SAMPLE of KURAMA's tools, asked the way the owner asks (typos, short, loose grammar). |
| `trace_report.py` | 324 | KURAMA monitoring report from data/traces.db (see MONITORING.md). |
| `wifi_share_server.py` | 128 | Tiny LAN file server for KURAMA's Wi-Fi share (stdlib only, run as its own process). |

<!-- FILES:END -->): each source file, its size and what it does, taken from the docstring a… |
| `gen_tool_guide.py` | 381 | Write the 'Every tool in detail' part of COMMAND.md from the live tool registry (run after adding tools): venv/bin/python scripts/gen_tool_guide.py What each tool does, … |
| `gesture_runner.py` | 136 | Runs the user's YouTube/media hand-gesture module (config.GESTURE_DIR/main.py) unchanged, in its own venv. |
| `kurama_fm.py` | 162 | What the Files app (Nautilus) shows: run with the SYSTEM python3 (PyGObject: Gdk, Gio, Atspi). |
| `kurama_glass.py` | 138 | KURAMA glass: the blur behind the mini chat panel, done by GNOME's Blur my Shell extension (0 KURAMA RAM/CPU). |
| `kurama_wallpaper.py` | 1806 | KURAMA live wallpaper: a native GTK + WebKit window that sits behind every window (X11). |
| `new_plugin.py` | 148 | Write the skeleton of a new tool, memory source or agent, plus its test (`make new-tool NAME=x` etc.). |
| `tool_round.py` | 241 | One test round over a SAMPLE of KURAMA's tools, asked the way the owner asks (typos, short, loose grammar). |
| `trace_report.py` | 324 | KURAMA monitoring report from data/traces.db (see MONITORING.md). |
| `wifi_share_server.py` | 128 | Tiny LAN file server for KURAMA's Wi-Fi share (stdlib only, run as its own process). |

<!-- FILES:END -->): each source file, its size and what it does, taken from the docstring a… |
| `gen_tool_guide.py` | 381 | Write the 'Every tool in detail' part of COMMAND.md from the live tool registry (run after adding tools): venv/bin/python scripts/gen_tool_guide.py What each tool does, … |
| `gesture_runner.py` | 136 | Runs the user's YouTube/media hand-gesture module (config.GESTURE_DIR/main.py) unchanged, in its own venv. |
| `kurama_fm.py` | 162 | What the Files app (Nautilus) shows: run with the SYSTEM python3 (PyGObject: Gdk, Gio, Atspi). |
| `kurama_glass.py` | 138 | KURAMA glass: the blur behind the mini chat panel, done by GNOME's Blur my Shell extension (0 KURAMA RAM/CPU). |
| `kurama_wallpaper.py` | 1806 | KURAMA live wallpaper: a native GTK + WebKit window that sits behind every window (X11). |
| `new_plugin.py` | 148 | Write the skeleton of a new tool, memory source or agent, plus its test (`make new-tool NAME=x` etc.). |
| `tool_round.py` | 241 | One test round over a SAMPLE of KURAMA's tools, asked the way the owner asks (typos, short, loose grammar). |
| `trace_report.py` | 324 | KURAMA monitoring report from data/traces.db (see MONITORING.md). |
| `wifi_share_server.py` | 128 | Tiny LAN file server for KURAMA's Wi-Fi share (stdlib only, run as its own process). |

<!-- FILES:END -->

---

# Part 4. The deep technical details

Now the inside of each part: the functions, the data, the numbers, the reasons. Sections refer to the files of
Part 3; read a section with its file open.

## 6. The life of one request

Follow one message from your keyboard to the answer. Every step names the file and the function, so you can open it
and read along.

### 6.1 The picture

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

### 6.2 Step by step

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
  Section 7.4 explains why.
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
  (section 8). One task goes to route.
- **route** (`_route_node`, `router.py`): picks at most 3 **areas** by meaning (`semantic.py`), then the general
  tools for them (`registry.schemas_for()`).
  - If KURAMA just asked something and your reply is short ("yes", "do it"), the tools come from **the meaning of
    KURAMA's question** (route method `answer`): "Want me to play some music?" → "yes" gets the music tools.
  - The text/code tool is added for the open VS Code file only when the request **means** it
    (`_about_context()`; section 15).
  - It also picks the model tier (fast / smart / voice).
- **messages** (`_messages()`): a short system prompt; the last 6 turns (the last 2 replies carry what their tools
  did); a rolling summary; "Things from this chat" (section 7); KURAMA's open question; one line of what is open
  (VS Code, Files, the browser; `context.py`).
- **llm** (`_llm_node`): calls the model through `llm.py` `chat()` with only those tools. Safety nets:
  - a refusal, or "I did it" with no tool behind it, is retried once with the tools (`meta.needs_tool`);
  - a claim that survives the retry is replaced by "I didn't do it: the action didn't run this time";
  - a tool-less answer about your saved things (links, to-dos, reminders, jobs, money) is retried with the tools;
  - a junk stream ("… … …", invisible spaces) is held back and replaced by the tool's own result.
- **tools** (`_tools_node`): every call goes through `safety.py` `execute()` (allowed? needs your yes? log it;
  record what it touched in working memory). A general tool maps its `action` to the real tool through
  `tools/core/_hub.py`. If every call was a simple action that worked, its own sentence is the answer (**direct
  reply**, no second AI call; section 15). Otherwise the result goes back to **llm** (at most 4 rounds).

**Step 7: the answer streams back.** agent → `turns.py` → SSE → `app.js` draws the bubble and, in voice mode, speaks
sentence by sentence (`frontend/voice.js` → `POST /api/v1/tts` → edge-tts).

**Step 8: after the answer (nothing waits for this).**
- `_remember()` adds the turn to the history with one line of what the tools did (`did_line()`), and saves it to
  the database (`store.py`). A choice that wasn't answered is dropped.
- `trace.py` writes one row to `data/traces.db`: text, path, route, tools, plan + step results, models, tokens,
  answer, time. This is your evidence (sections 22–23).
- `learn.py` judges the **previous** turn, but only from what *you* did: a correction ("no, I meant..."), a
  complaint or praise (judged by meaning), or a 👍/👎. Silence teaches nothing. `recipes.py` turns a confirmed
  request into a 0-token shortcut. All of it is explained with examples in `docs/LEARNING.md`.

### 6.3 The same request from other doors

| Door | Path |
|---|---|
| **Voice in the page** | `frontend/voice.js` records → `POST /api/v1/stt` (`api/routes/voice.py` → `core/stt.py`, Groq Whisper) → text → the same `/chat` with `mode: "voice"` → the reply spoken. |
| **Wake word** | `api/routes/wake.py` runs `core/wake.py` `WakeListener` (mic → voice activity → short Whisper check for "KURAMA") → the page starts listening. |
| **Hold Alt** | `core/ptt.py` (key hook in the server) → the desktop window (`scripts/kurama_wallpaper.py`) shows the panel → the page records → same as voice. |
| **Telegram** | `workers/telegram_bot.py` polls Telegram → the same `Agent` with `channel="telegram"` → replies through the Bot API. Same working memory: "send that image" on Telegram finds the image made on the laptop. |
| **Terminal** | `python -m jarvis` → `jarvis/cli.py` → `Agent.run()`. Handy for debugging without the UI. |

## 7. Short-term memory

"Short-term memory" means: what KURAMA knows about **this conversation**, beyond your words. Before 2026-11-01 the
chat history kept only words, so everything a tool did vanished: "send that image" had no image, "open it in VS
Code" had no "it", and "yes" got "nothing is waiting for a yes". There are now five layers.

### 7.1 The five layers

| Layer | What it holds | Where | Cost |
|---|---|---|---|
| **Chat history** | your last 6 messages and KURAMA's replies, plus a rolling summary of older ones | `Agent.history`, `Agent.summary`; saved in `data/jarvis.db` | the words themselves |
| **What the tools did** | one line per reply: `[tools this turn: make_folder(path=~/Downloads/x) -> Created folder …]` | appended to the reply in history (`did_line()`); only the last 2 replies keep it (`config.DID_TURNS`) | ~40–60 tokens |
| **Things** (working memory) | every real file / folder / image / video / document a tool touched or made, newest first, with its kind | `jarvis/core/workmem.py`, kv key `workmem_things` | ~50 tokens in the prompt; 0 tokens for shortcuts |
| **Choices** | the numbered list of real paths KURAMA just showed, and the tool call to repeat with the one you pick | `workmem.py`, kv key `workmem_choice`, 10 minutes | 0 tokens |
| **KURAMA's open question** | its newest message to you if it asked or offered something (any channel, alerts too) | `Agent._open_question()` | ~50 tokens, only when there is one |

### 7.2 How things are recorded (no tool needs to know about it)

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

### 7.3 How "it", "this folder", "that image" are resolved

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

### 7.4 Answers to KURAMA's questions

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

### 7.5 After a restart

The laptop chat now resumes like Telegram did: `_begin_turn()` → `_resume()` reloads the last 6 turns and the
summary from `data/jarvis.db` if the last message was within `config.SESSION_IDLE_S` (4 hours). Things and choices
live in the kv store, so they survive restarts too.

### 7.6 What short-term memory does NOT do

- It does not remember the *content* of a long answer (an essay is a file; the file is the thing).
- A thing that was deleted from disk is forgotten automatically (`things()` keeps only existing paths).
- It does not decide what you meant. It offers the AI and the shortcuts the right candidates; meaning still decides.

---

## 8. Multitasking: the task graph

### 8.1 The problem it solves

"create a new folder in download folder name new_project2 and open this folder in vs code" used to:
- split into 3 tasks by words (including "let's work" as a task of its own);
- run them **at the same time**, because nothing said that "this folder" needs the first task;
- give each task a full AI call with the whole chat (5,500 tokens);
- open an old Webcam folder in VS Code, while the AI claimed "Made it" with no tool behind it.

### 8.2 The new way, in one picture

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

### 8.3 What one step does (`Agent._step_node`)

1. **Inputs become the freshest things.** Every file/folder the needed steps made is noted again in working memory
   (`workmem.note`), so "it / this folder / that image" in this step resolve to them (section 7.3, rule 3).
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

### 8.4 The end (`Agent._finish_node` + `taskgraph.settle`)

- A step whose needed step failed is **skipped, with the reason**: *I skipped "open it in vs code" because "create a
  folder …" didn't work.* Nothing is faked.
- Steps that need a background job (the essay, the picture) become **one follow-up job** that waits for the job and
  runs on its real output (`start_after_job` → `after_job`).
- Independent steps never wait for unrelated ones.
- One answer: each step's sentence in order; "started job #N" lines last.
- A plan the AI made that fully worked is **learned** by meaning (`taskgraph.learn_plan` →
  `data/learned_plans.json`): the next request of the same shape ("make a folder X in downloads and open it in vs
  code" with any name) reuses the links between steps with 0 tokens (`config.TASK_PLAN_MATCH` 0.93).

### 8.5 Your 6-step example

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

### 8.6 Settings and switches (`config.py`)

`TASK_GRAPH` (False = the old chains, kept as a fallback), `PLANNER_MAX_TASKS` (8), `TASK_REPLAN`,
`TASK_REPLAN_MAX_TOKENS`, `TASK_PLANS_KEEP`, `TASK_PLAN_MATCH`, `FILLER_EXAMPLES` / `NOT_FILLER_EXAMPLES` /
`FILLER_MIN` (what counts as filler, by meaning).

---

## 9. The architecture: layers and why

### 9.1 The layers

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
   plus WORKERS (jarvis/workers/): small loops for reminders, Telegram, RAM guard... (section 19)
```

**The rule: a layer may use the layers below it, never above.** A tool never imports the agent; `config.py` imports
nothing of ours. That is what lets you test a tool alone, swap the UI, or run the brain from a terminal.
(`workmem` is foundation: the safety gate writes into it, and the brain reads it.)

### 9.2 The ideas behind it (and why each one beats the obvious way)

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

## 10. The folder map

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
│   ├── core/            ~115 modules: brain + services + foundation (section 11)
│   │   └── intents/     the fast-path intents by area (base, files, desktop, media, todo, control)
│   ├── memories/        memory sources, one file each (notes, profile, links, documents): section 12.4
│   ├── tools/
│   │   ├── core/        the 17 GENERAL tools the AI sees (thin dispatchers)
│   │   ├── general/     ~150 real tools (one file each)
│   │   └── interactive/ a few more real tools (code, files) + _secrets.py (key detection)
│   ├── api/             FastAPI server: app.py, turns.py, routes/
│   ├── workers/         background loops (reminders, Telegram, guards)
│   ├── agents/          optional focused helpers, one folder each (coding): found by themselves, section 12.4
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

## 11. Every core file

**Bold** = read these first; they are the skeleton. Line counts from 2026-11-01.

### 11.1 Brain (decides what to do)

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
| focus.py | 150 | KURAMA's current folder; `refer()` resolves "this / it / that image" (section 7.3). | Reference resolution order. |
| filemanager.py · browsertab.py · editor.py | 60–130 | The Files app, the browser tab, the VS Code link. | That context is wrong. |
| rewrite.py | 330 | Read / replace the highlight in any app; refuses keys and private files. | Selection features. |

### 11.2 Foundation (used by everyone)

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

### 11.3 Voice

| File | What it does |
|---|---|
| stt.py | Groq Whisper; a parallel Nepali-forced pass; drops noise and foreign garbage (`not_ours()`); `data/logs/stt.log`. |
| tts.py · edge_pool.py | edge-tts voices, sentence by sentence, warm connections. |
| audio.py | Mic capture with voice activity (webrtcvad), the player, barge-in. |
| wake.py | Wake word: loudness + VAD, then a short Whisper check; `match_wake()` handles mishearings. `data/logs/wake.log`. |
| ptt.py | Hold-to-talk key hook; `data/logs/ptt.log`. |
| dictation.py · devaudio.py · voicecfg.py | Voice typing; removing the laptop's own sound from the mic; mic settings. |

### 11.4 Services (the features; plain code, mostly 0 tokens)

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

### 11.5 API (`jarvis/api/`)

| File | What it does |
|---|---|
| app.py | Builds the FastAPI app, mounts routes, serves `frontend/`, warms the agent. |
| **turns.py** | Agent thread → event queue → SSE; confirmations; the talk-mode gate. |
| security.py | Every request must come from this laptop (the API can run tools). |
| routes/chat.py · voice.py · wake.py · info.py · dash.py | `/chat` + `/confirm`; `/stt` + `/tts`; the wake listener; panels. |

---

## 12. Tools

### 12.1 Two layers

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

### 12.2 The tool contract

One file = one tool, `@tool(group=..., safety=..., description=...)`; type hints + docstring become the JSON schema;
a safety level (`safe` / `confirm` / `blocked`); a mocked test. `confirm` = delete, shell, install, send email, kill
a process. Example: `jarvis/tools/general/brightness.py`.

**Good tool results help memory for free:** return a full sentence with the **full path** of what you made ("Created
folder /home/leo/Downloads/x"), and start failures with `error:`. Working memory records the path; the step checker
sees the failure; a short request can use the sentence as the direct reply.

### 12.3 How to add a tool (practise this)

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
7. Test with 3+ phrasings the way you really type; run the scorecard; a live `curl` (section 22).

### 12.4 The plug-in architecture: add a tool, a memory or an agent without touching the others

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
`memories.search(q, only=["documents"])`). Short-term memory (`workmem`, section 7) is different: it is "what just
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

### 12.5 KURAMA knows itself: explain, settings, help

Three abilities so you never have to remember how KURAMA works:

| You say | What happens | Cost |
|---|---|---|
| "how did you do that?", "how do you measure my internet speed?", "explain the code you gave me", "can I use this with VS Code?" | `explain_self` collects FACTS: your last request from the trace (what ran, with which arguments, what came back), the **cards** of those tools (+ the 2 closest by meaning), and the start of a file it made (a notebook, a script). One smart-model call (gpt-oss-120b, low reasoning: the fast one invented menu buttons) answers from those facts only. | ~800–1,500 tokens, only when asked |
| "make the speed test 30 seconds", "set end of speech wait to 1500 ms", "talk faster +30%", "set the daily summary time to 9 PM" | the setting is found by name or meaning, the value parsed with its unit ("2 minutes" for a seconds setting) and checked against its range; saved and applied at once (`restart=True` ones after a restart) | 0 tokens |
| "what settings can I change?", "undo that setting", "reset all settings" | the list with current values; undo the last change; back to defaults | 0 tokens |
| "run the speed test with 30 seconds" | **this test only**: the value goes to the tool as an argument, the saved setting stays; "make it permanent" (within 30 min) saves it | 0 tokens |
| "do you have the ability to convert pdf to md?", "is it possible to send a file to my phone?", "are you able to read my screen?" | **answered, never done**: what it can do and the words to say (a capability question once converted a random file for 5.3k tokens) | 0 tokens |
| "help me use kurama", "help with sending files to my phone", "can you translate a pdf?" | every area with real example commands, or the closest tools by meaning, plus "teach me your own command" and "I can make a new tool" | 0 tokens |

**How it stays true:** nothing here is a hand-kept description. `core/selfindex.py` builds each tool's card from the
tool's description, the docstring at the top of its file, the settings its code reads (`config.KEY`) and its example
phrases. A contract test fails if any tool lacks them. Change the code, and the explanation changes with it.

**Why settings are a fixed list:** the AI never edits code or arbitrary config. `usersettings.SETTINGS` names what may
change, with ranges; everything else needs a code change, and KURAMA says so. That keeps "change yourself" safe.

**How a question is told from a command (consistency rules, 11-05):**
- *Openings carry meaning.* "do you have the ability to …", "help me with …": the first 3–6 words are compared by
  meaning on their own (`config.MEANING_OPENINGS`, `fastpath._opening`), so a long or misspelled need can't hide that
  it is a question. Common slips ("ahve", "abality", "convery") are fixed first (`spelling.py`).
- *"How … that / it / you" right after an answer* is about that answer (`fastpath._about_last`: a request in the last
  15 minutes), so it is explained even when the words are loose ("how you measure that and what time you use?").
- *Nothing selected* when you say "explain this code" / "how can I use it": the editing helper no longer says "I
  couldn't see any highlighted text"; it explains what KURAMA just gave you.
- *Answers use your words, not internal names:* the facts given to the AI drop tool and file names, so it says "I
  time a download from Cloudflare", not "I call internet_doctor".
- *A vague target asks:* "open app" says "Which app?" (it opened KDE Connect).

**The kind of request is decided first (`core/querykind.py`).** Before any tool is chosen, the first 2–5 words are
compared by meaning with `config.QUERY_OPENINGS`:
- `command` ("can you…", "please…"): a polite command, done as usual;
- `help` ("how can I…", "help me with…") and `ability` ("do you have the ability to…"): answered with the words to
  say (`find_capability`), decided the same way a real request is (`selfindex.by_meaning`: the instant command that
  would run, else the router's areas); a how-to no tool fits ("how do I cook rice?") goes to the AI;
- `explain` ("how did you…", "how do you…"): `explain_self`;
- and "run it for 30 seconds" / "do it again": the last request again with the new value (`querykind.again`).

**Nepal documents (`core/nepaldocs.py`, `tools/general/nepal_docs.py`).** Laws, legal processes, fees and Nepal
general knowledge go to the owner's own document service (a RAG API: `KURAMA_RAG_API_URL` and `KURAMA_RAG_API_KEY`
in `.env`). `querykind.nepal()` decides it by meaning: closest to `config.LANE_EXAMPLES["nepal"]` and ahead of the
"search" lane (live data); in Devanagari, `config.NEPAL_DEVANAGARI_WORDS` stand in (the meaning model reads English
only). The service takes 5–15 s, so the tool starts a background job and says "Looking that up…"; the job writes the
answer as its reply (`» ` progress), which the chat shows and speaks by itself; from Telegram the answer goes back
to the phone. Answers are cached for 6 hours. KURAMA's own AI is not used: 0 tokens.

**The Claude Code watch (`core/claudewatch.py`, `scripts/claude_hook.py`, `api/routes/claude.py`).** Off by
default. "/claude on" (or "watch my Claude Code") creates `data/claude_watch.on` and adds ONE hook to every Claude
Code settings file (`~/.claude*/settings.json`, once, with a backup) for its key moments: a prompt, each tool, a
permission question, the end. The hook command first checks that flag file, so while the watch is off it does
nothing at all. While on, it posts each event to `POST /api/v1/claude/event`; the module keeps the task's state
(prompt, steps, files changed, to-do list from its to-do tool) and messages Telegram on start, question, finish and
after 10 quiet minutes. A permission question makes the hook wait (`GET /api/v1/claude/decision`) for "/claude yes"
or "/claude no" from the phone, then answers Claude Code; no answer in 10 min = the laptop's own dialog. "/claude
status" and "/claude report" are built from the events (0 tokens); on Telegram, status adds a screenshot.
"/claude say <next step>" continues a finished task in the background (`claude -p --resume <session>`, same
folder and account). Answering yes, sending a step and the screenshot need the Telegram PIN.

**Long replies are never cut.** A tool's whole output reaches you (`ToolResult.full`; only the AI's copy is
shortened). In the workspace a long text opens folded with "Show more" / "Show less". On Telegram
(`notify.send_long`) a long reply shows its start and folds the rest behind Telegram's own "show more"
(an expandable quote); longer than two messages, the whole text also comes as an .md file.

**Telegram sections (`core/tgtopics.py`).** "/topics setup" sorts what KURAMA sends by itself into topics of your
own Telegram group: ⚠️ Alerts, 🤖 Claude Code, ⏰ Reminders & jobs, 📌 Other (`notify.notify` asks
`tgtopics.where(source, level)`); your conversation with KURAMA stays in the private chat. Setup: a group with Topics
on, the bot added as an admin that can manage topics, any message in the group, then "/topics setup".

**Claude Code limits.** "/claude usage" runs Claude Code's own `/usage` for each account on the laptop
(`claude -p /usage`: a local command, 0 tokens, ~0.5 s) and shows the 5-hour window and the week: used, left and
when each resets, plus how much was used today.

**Every command is always listed.** A command added to `slash.COMMANDS` appears by itself in `/list` (laptop and
Telegram; Telegram shows its phone commands first, then all of these), in the chat box suggestions, and in the
Telegram "/" menu (max 100: the phone ones first). `tests/test_claude_watch.py` checks that nothing is ever missing.

**The next step is offered (`core/nextstep.py`).** After an image, a screenshot, a document: "Say yes to send it to
your Telegram". A RAM alert: "Say yes to clean your RAM". A bare "yes" within 3 minutes runs that instant command
(0 tokens). When the AI says it can't do something and used no tool, the closest instant command is suggested.

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
8. "run the speed test with 20 seconds" (one time) → "make it permanent" → "what settings can I change?"
9. "do you ahve abality to convery pdf into md file?" (typos on purpose: answered, nothing converted)
10. "set up colab notebook" → "how can I use it?" → "can I run it in VS Code?"

### 12.x The coding agent: its own project (`coder/`)

The coding agent lives in its own folder, `coder/`, apart from `jarvis/`, so it can grow on its own. It meets KURAMA
in only two files: `coder/link.py` (jobs, the Progress section, the workspace, Telegram) and `coder/models.py`
(KURAMA's AI layer, so the keys and the Groq rate limit are shared). KURAMA calls it from
`jarvis/agents/coding/tools.py` (`coder.start`, `coder.yes`, `coder.no`, `coder.undo_last`).

A run, step by step:

1. **Understand, 0 tokens** (`understand.py`): the stack your words name (React, Pygame, HTML/CSS/JS, FastAPI...),
   the folder ("here" = the project open in VS Code, else `~/projects/<name>`), new project or an addition. It never
   asks which stack: when you name none, the plan picks the best fit and shows it ("use X" changes it).
2. **Choose the start, 0 tokens** (`scaffold.py`, `github.py`): React starts from the official `npm create vite`
   template; "from GitHub" downloads a starter, checked first (open licence, small, no secrets, no GPU packages).
3. **Plan, 1 call** (`planner.py`): the files, each file's job, which files it uses, how hard it is, the run
   command. The plan goes to the workspace with its cost (`budget.py`). **Nothing is written before your yes.**
   Say "use Tailwind" or "drop the scoreboard" and it plans again.
4. **Build** (`engine.py`, a LangGraph graph): each file is written by `writer.py` with the plan and only the files
   it must agree with (the smart model for hard files, the fast one for easy files). Every file is backed up or
   listed first (`safety.py`), so "undo the project" puts everything back. Keys in code are replaced (secret guard).
5. **Check, 0 tokens** (`connect.py`, `verify.py`): links and imports exist, the script's ids are on the page,
   `from game import X` really finds X, Python compiles and passes ruff's error rules, JavaScript passes
   `node --check`.
6. **Fix** (`fixloop.py`): each problem with only its file (and the files it must agree with) goes to the smart
   model; then the checks run again, at most 3 rounds.
7. **Three memories.** The *run's* memory: while it builds, every next file gets a short list of what the files
   written so far define (functions, ids: `writer.run_memory`), so a big website stays consistent without
   re-sending whole files; it is deleted after the run. The *project's* memory: `.kurama/project.md`, the
   project card (overview, every file's job, a fresh map of what each file defines, decisions), plus a README for
   every new project. KURAMA's memory (your settings, notes) is shared as always.
8. **A project it didn't build** (`onboard.py`): the first time, it learns it ONCE from facts, never the full code:
   the map, the manifests (package.json, requirements), the README's start, entry points and last commits go to
   the fast model in one call (~3-4k tokens; a real 17 MB project took 3.7k) and the card is written. After
   that every request reads the card + a fresh map (0 tokens) and only the 2-3 files that matter. `/code learn`
   does it on purpose.
9. **Remember** (`memory.py`): `.kurama/project.md` in the project (stack, run command, files, decisions) and
   `TODO.md`, so the next request about this project needs no re-reading. Tokens per project: `data/coder/projects.json`.

The Progress section shows the plan as a checklist while it builds (done / doing / to do).

More it does while it is on (say it in your own words; matched by meaning, 0 tokens to pick):

| Say | What happens | Files |
|---|---|---|
| `/code` | the whole list of coding-agent commands (also in /list and Telegram's menu) | `jarvis/agents/coding/tools.py` |
| "learn this project" | read a project it didn't build, once; writes its card | `onboard.py` |
| "write tests for this project" | pytest files per module, then run | `testing.py` |
| "make the tests pass" | run, send only the failure + the code it blames, fix, run again (max 3) | `testing.py` |
| "review my changes" / "commit this" | a review of your git diff / a commit message (commits after yes) | `review.py` |
| "show me what you changed" / "reject app.js" | side-by-side diffs in VS Code / one file back | `review.py` |
| "preview it" / "check the page" | the page with an error-collecting server / fix what it showed | `preview.py` |
| "how does it look?" | the vision model's look at a screenshot (1 call) | `preview.py` |
| "continue the project" | the next unticked TODO.md item, planned | `api.py`, `memory.py` |
| "after that, add dark mode" | queued while a build runs, planned when it ends | `api.py` |
| "send it to Claude Code" | a big plan built by Claude Code instead (no Groq tokens) | `link.py` |
| "how many tokens did this project use?" | tokens per project | `api.py` |
| "undo the project" | everything of the last build put back | `safety.py` |

## 13. How KURAMA understands a request

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
- **The question decides the tools for a short answer** (route method `answer`, section 7.4).
- **Filler is judged by meaning** (`taskgraph.filler`: closer to `FILLER_EXAMPLES` than to `NOT_FILLER_EXAMPLES`).

---

## 14. The AI models

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

## 15. Tokens: where they go and how they are cut

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

To find the next cut: the report's "Most tokens" and "Asked the AI most often" sections (section 23).

---

## 16. Long-term memory, data and storage

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

## 17. Privacy and safety

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
- **Inside a plan, "close X"** closes only windows the plan opened (section 8.5).

---

## 18. Voice and the desktop

- **The desktop window** (`scripts/kurama_wallpaper.py`, system python3: GTK3 + WebKit2) shows `frontend/` as your
  wallpaper (`?wallpaper=1`) and a mini chat (`?mini=1`); hold-to-talk display; a hang guard writes stacks to
  `data/logs/hang.log` and restarts itself. `scripts/kurama_fm.py` reads the Files app (AT-SPI).
- **Power**: `scripts/kurama-power.sh on|off|status`.
- **Voice pipeline**: record (`voice.js`) → `/stt` → `/chat` (mode voice) → sentences → `/tts` → play; barge-in.
- **Talk mode**: speech long after KURAMA spoke is kept only if it names KURAMA, is a shortcut, or by meaning is a
  greeting or a clear request.
- **Keys**: hold Alt = talk (Alt+Shift cancels), Super+J = cursor to the chat box and back, Ctrl+Alt+K = mini chat.

---

## 19. Background work

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

## 20. The dependency map

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

## 21. "I want to change X"

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

## 22. Debugging

### 22.1 The method (use it every time)

1. **Find the evidence.** Don't guess. Find the trace of the bad request.
2. **Locate the step.** Shortcut (path `fastpath`)? Plan (the `plan` column: method, steps)? Router (wrong
   `route_groups` / `tools_sent`)? The AI (wrong tool, no tool)? The tool (`result` says error)? Memory (the wrong
   "it")? The model chain (`llm`: which models failed)? The UI?
3. **Prove the cause.** Re-run that one step alone (snippets below) until you can say "this line, with this
   input, produces this wrong output".
4. **Fix the class, not the sentence.** Fix it for every phrasing and every tool of that kind.
5. **Test with your real way of typing** (typos, "bro", "..", Nepali/Hindi), then the scorecard, then live.

### 22.2 The toolkit

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

### 22.3 Reading a trace

`--show <id>` prints: `text`, `path` (fastpath / ai / multi), `route_method` + `route_groups`, `tools_sent`,
`tools` (what ran, with arguments and the first 300 characters of the result), `plan` (method, tasks, **steps**
like `1:ok 2:skipped`, **replanned**), `llm` (each AI call: model, purpose, tokens, ms, error), `retried`, `asked` /
`denied`, `answer`, `ms`, `error`. Typical readings:

| You see | It means |
|---|---|
| `path: ai`, `tools: []`, answer says "Done" | the AI claimed without acting (the safety nets should have caught it: check `meta.claims`) |
| the right tool missing from `tools_sent` | routing (section 13) |
| the right tool ran, `result` starts with "error" | the tool / service |
| `route_method: answer` with odd tools | KURAMA's question was routed (section 7.4): was the question really about that? |
| `plan.steps` has `failed` but the tool worked | the tool answered "error"-like text, or `judge` is too strict |
| `plan.steps` has `skipped` | a step it needed failed: look at that step first |
| `plan.method: llm` for a simple two-part request | a part had no shortcut; making it one makes the whole plan 0 tokens |
| `llm` entries with gemini or qwen | Groq's gpt-oss limit was used up that day |
| `intent: choice` | a reply picked from a list |
| `route_method: rules` | the meaning model wasn't loaded |

---

## 23. Monitoring and improving it yourself

You don't need anyone to keep KURAMA healthy. Here is the routine. MONITORING.md has the detailed tables.

### 23.1 Every 2–3 days (15 minutes)

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
3. For each problem: `--show <id>`, then section 22.1 (locate → prove → fix the class).

### 23.2 Deciding what to fix

| Symptom (how often) | First thing to try |
|---|---|
| Same request goes to the AI many times | a meaning shortcut (`MEANING_SHORTCUTS`) or a slash command |
| Wrong tool offered | more meaning examples for the right area (`ROUTER_EXAMPLES` / `TOOL_EXAMPLES`) |
| Right tool, wrong action / argument | the general tool's description in `tools/core/<tool>.py` |
| "it / this" wrong | `focus.refer` order; the tool's result missing the full path |
| Steps linked wrongly | `PLAN_PROMPT`, `_REF`, `FILLER_EXAMPLES` |
| A fake "done" | `meta.claims` patterns (add the new grammar, with a test that it is NOT matched in normal answers) |
| Too many tokens | `DIRECT_REPLY_SINGLE`, a shortcut, fewer history turns (`HISTORY_TURNS`) |

### 23.3 After a fix

1. A test with 3+ phrasings, the way you really type.
2. `venv/bin/python -m pytest -q` (all green) and `venv/bin/python -m tests.eval.harness` (≥65% / 100% / 98%).
3. Add the phrasings to `tests/eval/cases.jsonl` if they are about routing or shortcuts.
4. Restart, one live check with `curl`.
5. `scripts/trace_report.py --mark-fixed`, a line in `PROGRESS.md` and in MONITORING.md's Fix history, commit.

### 23.4 Health numbers to keep an eye on

| Number | Where | Healthy |
|---|---|---|
| Instant shortcuts | scorecard | ≥ 65% (68% on 11-01) |
| Router right | scorecard | ≥ 98% |
| Tokens per AI request | report header | falling over time (2,175 on 11-01) |
| AI calls per AI request | report "Most tokens" | close to 1 for simple actions |
| Core RAM | `data/logs/worker_resource_guard.log` | ~390 MB with the meaning model, ~140 MB without |
| Groq daily use | report "Models" | gemini/qwen lines = the limit was hit |

---

## 24. Lessons for any big project

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

## 25. Industry level: where KURAMA stands, and what is left

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

### 25.1 Already at industry level

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
- **Plug-in architecture** (section 12.4): tools, memory sources and agents are added as files, found by
  themselves, isolated when broken and checked by contract tests; a scaffold writes each one.
- **Self-knowledge** (section 12.5): cards built from the code, explanations grounded in the real trace, a safe
  settings list changed by voice, help by meaning.
- **Decisions are written down**: `docs/adr/` (10 records).

### 25.2 What is left (smaller now, in the order to do it)

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

### 25.3 How large production codebases work (and how KURAMA maps to it)

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
| **Plug-in architecture** | Extension points with small contracts; new features plug in instead of editing old code; one failing plug-in is isolated | tools, `memories/`, `agents/` via `core/plugins.py` (section 12.4) |
| **Documentation** | README to start, ADRs for decisions, runbooks for "when X breaks, do Y", docs next to the code | README, LEARN.md, MONITORING.md, `docs/adr/` |
| **Versioning and changelog** | Semantic versioning (MAJOR.MINOR.PATCH) and a changelog per release | `version` in `pyproject.toml`; PROGRESS.md is the changelog |
| **Security practice** | Least privilege, input validation, threat modelling, dependency scanning, security review | the safety gate, confirm levels, PINs, shell allowlist |
| **Performance budgets** | Limits on latency, memory and bundle size, checked in CI | idle RSS < 600 MB, token budgets; `make rss` |

**How to use this table:** pick one row a week that KURAMA does not have yet (e2e tests, `pip-audit`, Docker, a
Grafana dashboard on `/metrics`), learn it with a 30-minute tutorial, then try its small version on KURAMA.

### 25.4 Smaller known weak spots

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

## 26. Glossary

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
