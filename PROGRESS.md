# JARVIS build progress

Status legend: [ ] todo · [~] in progress · [x] done · [h] done, needs human test · [b] blocked

## Workflow (user rule, 2026-10-23)
Build ONE phase at a time. After each phase: commit, give the user exact test steps, then STOP and wait for their OK ("works" / "continue"). Never auto-start the next phase. Fixes the user reports for a phase come first.

## Phases
- [x] P0 Bootstrap: git, .gitignore, .env.example, CLAUDE.md, PROGRESS.md
- [x] P1 Core: config.py (model IDs + voices, verify Groq models endpoint), Groq client (streaming, retry/backoff 429/5xx, 70b→8b fallback, token budget), SQLite logging (tool calls, tokens, routing latency), terminal text chat loop
- [h] P2 Voice I/O: mic capture, webrtcvad, Groq Whisper STT (turbo → large-v3, auto lang), edge-tts sentence streaming (<~1 s first sentence), barge-in, push-to-talk hotkey (pynput, X11), `python -m jarvis.core.tts "text"`
- [x] P3 Agent: LangGraph router + tool registry (decorator, auto JSON schema, one file per tool), tool-group router, safety levels (safe/confirm/blocked), confirmation flow, SQLite action log
- [x] P3-STOP: human end-to-end test with real Groq key passed (2026-10-23). User: "working very good".
- [x] P3b LangChain + multitasking (user request 2026-10-23): migrate LLM calls to ChatGroq and tools to langchain_core tools, keeping groups, safety, logging and token rules. Add a multi-task decomposer, a parallel LangGraph fan-out (Send), a background job manager (outputs under data/outputs/, announced when done), a per-model TPM rate limiter, and job status/cancel tools.
- [h] P4 Interactive core: Project Scaffolder, Environment Doctor (CPU-only), Smart File Search (rg/fd), Git Assistant, Test Runner
- [h] P5 General core (X11), plus user additions on 2026-10-23: weather for any place (Open-Meteo, free, no key), world time for any place, open any Ubuntu app, remember/recall notes ("remember 1234", "what do you remember", "what was the last thing"), and a zero-token fast path for simple commands. Original list: Volume, Media, Mic Mute, Brightness, Open/Close/Focus App, Window Snap, Workspace Launcher, Sleep/Lock, Screenshot, Clipboard, TTS Replies, Startup Greeting
- [ ] P6 Background core: Long-Process/Training Run Watcher (daemon pattern, Telegram alerts), Crash Watchdog, Resource Guard, Telegram Remote Control, n8n Bridge
- [ ] P7 Memory/RAG: RAG over code+notes (fastembed ONNX + FAISS-cpu/SQLite), Session Recall, API Cost/Token Tracker, Daily Digest
- [ ] P8a Dev-quality 1: Dependency Doctor, Secrets Auditor, Pre-commit Gate, Repo Hygiene, Auto Code Reviewer
- [ ] P8b Dev-quality 2: Docstring/Type Hint Generator, Notebook to Script, Requirements Generator, Config Diff Tracker, Benchmark Table Builder
- [ ] P8c Dev-quality 3: Checkpoint Cleaner, Dataset Sanity Checker, Env Snapshot, Flaky Test Detector, Semantic Code Search
- [ ] P9a General rest: DND, Night Light, Auto Dark/Light, Wallpaper, Kill Unresponsive App, Global Hotkey Macros, Smart Focus Mode, Notification Mirror, Battery tools, Play Saved Playlist, YouTube Control
- [ ] P9b Background rest: CPU/RAM-aware Job Scheduler, Auto-Resume, Anomaly Detector, Metrics HUD (CPU, RAM, token budget), Cloud/API Cost Tracker
- [ ] P10 External (one at a time, lazy): Wake-Word (openwakeword), Webcam Mouse (MediaPipe 320x240 ~15 fps), Screen-Watching Agent (mss + Tesseract), Gesture Media, Face Lock/Away, Network/Rate-limit Monitor, Auto Screen-Recording on Error, Live Handwriting OCR, Real-Time Voice Command Parsing
- [ ] P11 Advanced agents: Refactor Agent, Auto-PR Agent, Voice-to-Code Dictation, Self-Healing Pipeline Agent, Experiment Designer (optuna), optional Local LLM Fallback (Ollama 1.5–3B, on demand)
- [ ] P12 Hardening: <2.5 s to first spoken word, RAM profiling vs 1.5 GB cap, piper offline TTS fallback, tests, README, systemd --user autostart
- [ ] DEFERRED (very end): Speaker Identification (Resemblyzer needs torch → find ONNX alternative or skip)

DROPPED, do not build: Custom Object/Error-State Detector, Voice Cloning (Coqui/RVC), Multi-Machine Orchestrator, Auto-Sync to Remote GPU.

## Reuse sources (existing code, outside this repo, read-only)
- `/media/leo/Project1/Test_project/KURAMA_V2/kurama/voice/{stt,tts,recorder}.py`: Groq STT, edge-tts + clean_for_speech, sounddevice + webrtcvad recorder → adapt for P2.
- `/media/leo/Project1/Test_project/KURAMA/KURAMA_LINUX_V1/kurama/core/{store,llm,graph}.py`: SQLite log_llm/log_tool, LangGraph graph → ideas for P1/P3 (V1 uses langchain-groq; new build uses the Groq SDK directly).
- `.../KURAMA_LINUX_V1/kurama/tools/general/controllers.py`: Audio, Display, Window, Media, SystemPower, Clipboard/Screenshot controllers → port into one-file tools in P5/P9a.
- `.../KURAMA_LINUX_V1/kurama/tools/interactive/controllers.py`: WorkspacePython, EnvironmentDoctor, ProjectOrganizer, GitAssistant, TestRunner, NotebookScriptConverter → port in P4/P8b.

## Decisions
- P0: The package is named `jarvis/` as CLAUDE.md specifies, even though the repo folder and the old code are called KURAMA.
- P0: No Flet UI or desktop widget exists in the old code, so there is no `jarvis/ui/` to reuse. A minimal UI is out of scope unless requested; the terminal and voice are the interfaces.
- P0: No docs/roadmap.md exists, so tools are built from the phase list above.
- P0: System has Python 3.12.3, rg, fdfind (Ubuntu name for fd), xdotool, wmctrl, xclip, pactl, brightnessctl, ffmpeg.

- P1: Groq retired llama-3.3-70b-versatile, llama-3.1-8b-instant and llama-4-scout (all return 404, checked 2026-10-23). config.py now uses LLM_DEFAULT=openai/gpt-oss-120b, LLM_FAST=openai/gpt-oss-20b and LLM_VISION=qwen/qwen3.8-27b. CLAUDE.md still names the old Llama models; config.py is the source of truth. gpt-oss models are sent reasoning_effort=low and include_reasoning=False.
- P1: The LLM client uses the Groq SDK directly (groq 1.7.0), not langchain-groq. A retry-after over 20 s skips to the fallback model. When the budget is exhausted on every model, the cheapest model is still tried and Groq enforces the real limit. Daily budgets are about 90% of the free tier.
- P1: The database is data/jarvis.db with tables llm_calls, tool_calls, routing and messages. Peak RAM of the text chat is 44 MB. First streamed reply arrived in 0.86 s.
- P2: Push-to-talk is a toggle on Ctrl+Alt+J (HOTKEY_PTT or env JARVIS_HOTKEY). Enter also works, and q+Enter quits. Barge-in is energy-gated by BARGE_IN_RMS=1500. Playback uses ffplay. Peak RAM of the tts command is 51 MB. Edge-tts first audio arrives in 1.0 to 1.4 s, which is network-bound.
- P2: Real STT round trip (edge-tts audio → Groq) takes 0.47 s. Hindi is perfect. Nepali is auto-detected as Hindi and turbo garbles it, while large-v3 with language=ne is accurate. Added STT_LANGUAGE_HINT (env JARVIS_STT_LANG=ne) and STT_PREFER_FALLBACK_LANGS=("ne",), which tries large-v3 first.
- P2 fix (after the human test): the laptop mic made webrtcvad call about 90% of quiet-room frames "speech", so turns never ended (6–7 s delay), and speaker echo (RMS 5k–20k) set off barge-in. The endpointer now gates on energy: a learned 20th-percentile noise floor capped at VAD_FLOOR_CAP=800, speech counted only above max(VAD_MIN_RMS=900, 3×floor), and the turn ends when ≤20% of the last 900 ms is speech. Barge-in by voice now defaults to off (JARVIS_BARGE_IN=1 turns it on), and the hotkey interrupts instead. Tunable through JARVIS_VAD_SILENCE_MS and JARVIS_VAD_MIN_RMS.
- P3: langgraph is pinned at 1.2.16 and pulls langchain-core but no torch. It's imported lazily on the first request. Peak RAM of `python -m jarvis` is 77 MB. Tool groups are general, files, system, apps, media, dev, web and memory. Keyword rules route in about 3 ms; the 8b classifier fallback takes about 800 ms. The router skips groups that have no tools yet. Plain chat sends no tool schemas (210 vs 225 prompt tokens). The tool_calls table gained outcome and result columns, with automatic migration. A confirm tool asks [y/N] in text mode or "Say yes or no" in voice mode (accepts yes, haan, ho, हो, हाँ); an unanswered confirm is denied after 20 s. Dummy tools: get_time (safe) and dummy_delete (confirm).
- Latency fix (after P3): voice first-audio was about 1.5–2.3 s after the text appeared, and 4–7 s for long replies. Measured breakdown: LLM first sentence about 1.0 s, edge-tts fresh connection 1.0–1.5 s (spikes to 3.5 s), player start-up about 0.3 s. Fixes:
  (1) `jarvis/core/edge_pool.py` keeps warm reusable edge websockets (pool of TTS_PARALLEL=2) on one long-lived loop. They prewarm when listening starts and fall back to edge_tts.Communicate on any error.
  (2) Two sentences are synthesized in parallel and played strictly in order.
  (3) The first chunk is cut at a clause after 40 chars, and run-ons are capped at 180 chars.
  (4) A new "voice" tier: tool-free spoken chat uses LLM_VOICE=qwen/qwen3.8-27b with reasoning_effort=none (about 0.2 s first token vs 0.5 s for gpt-oss; same free limits of 1000 RPD and 8k TPM). Override with JARVIS_LLM_VOICE.
  (5) The voice prompt allows up to 6 sentences when asked to explain.
  Result: from the agent call to the first audio bytes reaching the player is 0.47–0.65 s for short replies and about 1.1 s for long ones. Each clip was checked by speech-to-text (no stale audio). Groq's Orpheus TTS is faster but English-only and needs terms accepted in the Groq console; not used.
- P3b-1: Migrated to LangChain. ChatGroq per model (langchain-groq 1.1.3, langchain-core 1.7.0). groq was downgraded to 0.37.1, because langchain-groq needs groq<1; real Whisper verified working on it. Our retry/backoff and tier fallback are kept, with max_retries=0 on ChatGroq. A UsageLogger callback writes every attempt to SQLite. Tools are StructuredTools from our @tool decorator, with group and safety in metadata; bind_tools gets only the routed groups. Our own tool node goes through safety.py. Agent.warm() runs at startup (0.64 s). Prompt tokens: plain chat 180, tool round 225/264. RAM 77 MB. Bench (scripts/bench_latency.py) first audio: short en 0.51 s, long 1.2–1.4 s, ne 0.64–0.77 s.
- P3b-2: Multitasking. planner.py runs regex multi-intent detection (en/hi/ne) and calls the fast model's structured output only when flagged; single requests cost zero extra tokens. agent.py adds a plan node and a LangGraph Send fan-out. Quick tasks run concurrently, long tasks go to the JobManager (jobs.py, 2 workers, SQLite `jobs` table, cancel, notify-send plus a spoken announcement when idle). The join reply needs no LLM call. ratelimit.py keeps a per-model TPM/RPM bucket, reads Groq headers, and holds a 30% reserve for interactive calls. writer.py works outline → sections (≤1500 tokens each) on the "writer" chain (gpt-oss-120b only) and writes to data/outputs/. New tools: write_document, list_jobs, cancel_job, job_result, open_url. New router groups: browser and jobs; "job status" is a keyword, bare "status" is not. Quitting cancels jobs and keeps the partial file. A repo-scan job runs the agent with confirmations denied. Smoke: "300-word essay + open YouTube" replied in 1.8 s, and the essay (312 words, 1,087 tokens) finished 1.5 s later. The planner call cost 229+79 tokens. A 1000-line essay is ~12k words / ~16k tokens, about 3 min when paced. 98 tests.
- P4: Nine tools in jarvis/tools/interactive/: scaffold_project (confirm), env_doctor, find_files (fdfind/rg), git_status, git_log, git_diff_summary, git_commit (confirm; auto-message sends only --stat plus ≤1500 chars of diff), git_branch (confirm; create/switch only), run_tests (>30 s runs as a background job). _proc.py runs allowlisted subprocesses with a timeout, and its git runner refuses push, reset, clean, rebase, --force, --hard and -D. The "git" group (5 tools) was split from "dev" (3 tools) to save tokens: env_doctor prompt went 717→447 tokens, git_status 776→541. Peak RAM 127 MB in a 3-question run. 107 tests.
- P5a: Weather and world time use Open-Meteo geocoding plus forecast (free, no key, 10 min cache; _geo.py shared). open/close(confirm)/focus_app fuzzy-match .desktop files and launch with gtk-launch (gio fallback). remember/recall(all/last/search)/forget(confirm) use a SQLite `notes` table. fastpath.py answers clear commands from regex templates with 0 LLM tokens (time, weather, remember, recall, open app/site, plus P5b system commands) and is logged as method=fastpath. Trailing time words (tomorrow, bholi, आज…) are stripped from place names. An unknown place falls through to the LLM to fix spelling. HOME_PLACE is Kathmandu (env JARVIS_HOME_PLACE).
- P5b: 17 system tools in small groups: audio 3, media 1, display 1, screen 1, power 3 (lock safe, suspend confirm, power_off blocked), clipboard 3, speech 1, windows 2, apps 4 (includes launch_workspace with config.WORKSPACES). The startup greeting is a template (0 tokens) in a thread; the hotkey cuts it short. Brightness steps never go below 5% and never brighten on "down". Window snap uses the wmctrl work area with a 32 px GNOME top-bar fallback. Romanized Hindi/Nepali volume words (awaj, aawaj) route to audio. tests/conftest blocks any real system command in tests. Read-only smoke worked on the real machine. RAM 66 MB. 142 tests.

## Known issues
- P5: read_aloud speaks on its own channel and can overlap Jarvis's spoken reply in voice mode. Window snap on multiple monitors uses the whole desktop's work area.
- P2: Nepali auto-detect is unreliable (Whisper says Hindi). Workaround: JARVIS_STT_LANG=ne. Possible fix in P12: switch the hint by voice command ("speak Nepali").
- P2: Voice barge-in on laptop speakers needs echo cancellation (PipeWire module-echo-cancel) or headphones. Until then it's off and the hotkey interrupts.
- P1: The vision model's request settings have not been tried with a real call yet; verify in P10.
- (none yet)

## Human actions needed
- P3-STOP: run the end-to-end test with the real Groq key. In text, run `venv/bin/python -m jarvis`, ask "what time is it?", then say "delete the file /tmp/x" and answer n. In voice, run `venv/bin/python -m jarvis --voice`, press Ctrl+Alt+J and ask a question. Then say "continue".
