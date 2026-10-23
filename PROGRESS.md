# JARVIS build progress

Status legend: [ ] todo · [~] in progress · [x] done · [h] done, needs human test · [b] blocked

## Phases
- [x] P0 Bootstrap: git, .gitignore, .env.example, CLAUDE.md, PROGRESS.md
- [x] P1 Core: config.py (model IDs + voices, verify Groq models endpoint), Groq client (streaming, retry/backoff 429/5xx, 70b→8b fallback, token budget), SQLite logging (tool calls, tokens, routing latency), terminal text chat loop
- [h] P2 Voice I/O: mic capture, webrtcvad, Groq Whisper STT (turbo → large-v3, auto lang), edge-tts sentence streaming (<~1 s first sentence), barge-in, push-to-talk hotkey (pynput, X11), `python -m jarvis.core.tts "text"`
- [ ] P3 Agent: LangGraph router + tool registry (decorator, auto JSON schema, one file per tool), tool-group router, safety levels (safe/confirm/blocked), confirmation flow, SQLite action log
- [ ] P3-STOP: human end-to-end test with real Groq key (text chat + one voice reply)
- [ ] P4 Interactive core: Project Scaffolder, Environment Doctor (CPU-only), Smart File Search (rg/fd), Git Assistant, Test Runner
- [ ] P5 General core (X11): Volume, Media, Mic Mute, Brightness, Open/Close/Focus App, Window Snap, Workspace Launcher, Sleep/Lock, Screenshot, Clipboard, TTS Replies, Startup Greeting
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

## Known issues
- P2: Nepali auto-detect is unreliable (Whisper says Hindi). Workaround: JARVIS_STT_LANG=ne. Possible fix in P12: switch the hint by voice command ("speak Nepali").
- P2: Needs a human test of the live mic, the pynput hotkey and barge-in echo (BARGE_IN_RMS may need tuning).
- P1: The vision model's request settings have not been tried with a real call yet; verify in P10.
- (none yet)

## Human actions needed
- (none yet)
