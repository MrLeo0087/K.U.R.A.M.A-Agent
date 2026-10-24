# JARVIS: voice assistant (100% free stack)

## Hardware and OS (hard constraints)
- Ubuntu on X11. NO GPU. 8 GB RAM shared with VS Code and Chrome. Never assume CUDA, nvidia-smi or pynvml.
- Jarvis runs ALL DAY on this laptop: idle RSS and idle CPU matter more than peak speed. Nothing heavy at import/startup; load on demand and unload when idle; measure idle RSS after every phase.
- Never install PyTorch or TensorFlow into Jarvis unless a tool absolutely needs it. Prefer ONNX runtime, APIs, or small CPU libraries. Heavy inference runs on Groq, not locally.
- RAM budget: Jarvis core idle under 600 MB, hard cap 1.5 GB including daemons. Lazy-import heavy modules (cv2, mediapipe, fastembed, playwright) only when their tool runs and release them after. Max ONE vision/camera feature running at a time.
- Daemons are tiny: plain Python plus psutil plus watchdog, poll interval at least 5 s, log rotation.
- X11 tools: xdotool, wmctrl, xrandr, xclip, pactl/amixer, brightnessctl, gsettings (detect desktop environment first), upower, loginctl, pynput, mss. Check each CLI with `which` and fail with a clear message if missing.

## Stack (do not change without asking)
- Python 3.11+. LangChain + LangGraph are the PRIMARY framework (user can read them): ChatGroq (langchain-groq) for LLM calls, langchain_core tools for tool definitions, LangGraph StateGraph for routing, tool loops and parallel fan-out (Send). Only drop to the raw Groq SDK where LangChain has no support (e.g. Whisper STT). Reuse my existing Flet UI and widget.
- LLM: Groq only. Model IDs live only in config.py. Groq retired the Llama models (2026-10), so: smart tier openai/gpt-oss-120b ("70b" below), fast tier openai/gpt-oss-20b ("8b" below), voice tier and vision qwen/qwen3.8-27b.
- STT: Groq whisper-large-v3-turbo (fallback whisper-large-v3). Languages: English, Nepali, Hindi.
- TTS: edge-tts. Voices in config: en en-GB-RyanNeural, en-US-AvaMultilingualNeural, hi hi-IN-MadhurNeural, ne ne-NP-SagarNeural. Offline fallback: piper.
- VAD: webrtcvad (no torch). Wake word: openwakeword.
- Memory/RAG: SQLite (FTS5) plus fastembed (small ONNX model) with FAISS-cpu or SQLite storage. No Chroma server, no Gemini, no paid APIs, no cloud DB.
- Secrets in .env only. Never commit, never print them.

## Architecture
jarvis/core/{config,llm,stt,tts,audio,wake,agent,memory,budget,safety}.py
jarvis/tools/{interactive,general,external}/<one file per tool>
jarvis/workers/<one file per daemon>
jarvis/ui/ (existing)   tests/   docs/roadmap.md   PROGRESS.md
Voice loop: hotkey or wake word -> VAD -> Groq STT -> LangGraph agent (stream) -> split into sentences -> edge-tts per sentence while the LLM keeps generating -> play. Barge-in stops playback.

## Runtime token and rate-limit rules (Groq free tier is limited)
- System prompt under 250 tokens. Voice replies: 1 to 2 short sentences unless asked for more.
- The router sends only the 1 to 3 relevant tool groups' schemas per request (keyword rules first, then the local semantic router (fastembed, 0 tokens), 8b classifier only if still unclear). Never send all tools.
- History: last 6 turns plus a rolling summary (8b). Truncate tool output to about 800 characters.
- Use 8b for chat and routing, 70b only for reasoning or multi-tool tasks. On 429 or 5xx: backoff, read retry headers, fall back 70b to 8b.
- Cache repeated results (weather, search) for a few minutes.
- Log tool-call counts, routing latency and token usage per call to SQLite from day one. No supervisor or multi-agent code until I ask.

## Multitasking (required)
- A request can contain several independent tasks ("write a 1000-line essay about Nepal and open YouTube"). Decompose it and run tasks concurrently: quick actions finish and are announced at once; long jobs (writing, code generation, scans) run as background jobs that never block the voice loop, save output under data/outputs/, and announce when done.
- Groq free tier is ~8k tokens/min per model: long jobs are chunked and paced by a shared per-model rate limiter, and spread across models. Never let a background job starve interactive replies.

## Tool contract
One tool = one file, registered via decorator, with a one-line description, JSON schema, safety level (safe / confirm / blocked) and one mocked test. `confirm` covers delete files, shell, sudo, install, send email, kill process, and needs my yes. Shell uses an allowlist. Every tool call is logged.

## Working rules for Claude Code
1. Read PROGRESS.md first; do only the current phase.
2. No big file dumps: use grep, head and line ranges. Do not re-read files you just wrote.
3. Write complete files in one go. Max 5 lines of summary after each step.
4. Run only tests for code you changed; show only failures. Do not paste logs or diffs.
5. Check every new dependency for torch or GPU baggage. Pin versions in requirements.txt.
6. Update PROGRESS.md at the end of each phase, then git commit.
7. If ambiguous, pick a sensible default, note it in PROGRESS.md, and ask only if blocked.
