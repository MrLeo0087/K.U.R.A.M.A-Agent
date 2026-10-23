"""Central configuration. The ONLY place for model IDs, voices, paths and budgets.

Model IDs were verified against GET https://api.groq.com/openai/v1/models on 2026-10-23.
The Llama IDs named in CLAUDE.md (llama-3.3-70b-versatile, llama-3.1-8b-instant) and the
llama-4 vision models return 404 (retired), so the current Groq equivalents are used:
  smart  : openai/gpt-oss-120b   (replaces llama-3.3-70b-versatile)
  fast   : openai/gpt-oss-20b    (replaces llama-3.1-8b-instant)
  vision : qwen/qwen3.8-27b      (input_modalities: text + image)
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

# --- secrets (never print) ---
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# --- LLM models (Groq) ---
LLM_DEFAULT = "openai/gpt-oss-120b"  # "smart" tier: reasoning / multi-tool
LLM_FAST = "openai/gpt-oss-20b"  # "fast" tier: chat, routing, summaries
LLM_VISION = "qwen/qwen3.8-27b"  # screen / image tasks
# Spoken chat without tools: qwen with thinking off starts in ~0.2 s vs ~0.5 s for gpt-oss.
LLM_VOICE = os.getenv("JARVIS_LLM_VOICE", "qwen/qwen3.8-27b")

TIERS: dict[str, str] = {"smart": LLM_DEFAULT, "fast": LLM_FAST, "vision": LLM_VISION,
                         "voice": LLM_VOICE}
# Fallback chain per tier (first entry is preferred).
TIER_CHAIN: dict[str, list[str]] = {
    "smart": [LLM_DEFAULT, LLM_FAST],
    "fast": [LLM_FAST],
    "vision": [LLM_VISION],
    "voice": list(dict.fromkeys([LLM_VOICE, LLM_FAST])),
    # Background writer jobs: smart model only (never falls back onto the fast/voice models' TPM).
    "writer": [LLM_DEFAULT],
}
# Extra per-model request params. gpt-oss models are reasoning models: keep reasoning
# short and hidden so replies stay fast and token-cheap.
# with_structured_output method per model. gpt-oss supports strict json_schema (constrained
# decoding, never invalid JSON); others fall back to function calling.
STRUCTURED_METHOD: dict[str, str] = {
    LLM_DEFAULT: "json_schema",
    LLM_FAST: "json_schema",
}
MODEL_PARAMS: dict[str, dict] = {
    LLM_DEFAULT: {"reasoning_effort": "low", "reasoning_format": "hidden"},
    LLM_FAST: {"reasoning_effort": "low", "reasoning_format": "hidden"},
    LLM_VISION: {"reasoning_effort": "none"},  # qwen3 thinking mode is slow; off by default
}

# --- STT (Groq Whisper) ---
STT_MODEL = "whisper-large-v3-turbo"
STT_FALLBACK = "whisper-large-v3"
STT_LANGUAGES = ("en", "ne", "hi")
# Whisper auto-detect mislabels Nepali as Hindi. Set JARVIS_STT_LANG=ne to pin it.
STT_LANGUAGE_HINT = os.getenv("JARVIS_STT_LANG") or None
STT_PREFER_FALLBACK_LANGS = ("ne",)  # use large-v3 first for these

# --- TTS (edge-tts) ---
VOICES: dict[str, str] = {
    "en": "en-GB-RyanNeural",
    "en_multi": "en-US-AvaMultilingualNeural",
    "hi": "hi-IN-MadhurNeural",
    "ne": "ne-NP-SagarNeural",
}

# --- paths ---
DATA_DIR = Path(os.getenv("JARVIS_DATA_DIR", str(ROOT / "data")))
DB_PATH = DATA_DIR / "jarvis.db"
LOG_DIR = DATA_DIR / "logs"

# --- daily token budgets (self-imposed, ~90% of Groq free-tier TPD) ---
DAILY_TOKEN_BUDGET: dict[str, int] = {
    LLM_DEFAULT: 180_000,
    LLM_FAST: 180_000,
    LLM_VISION: 90_000,
}
STT_DAILY_AUDIO_SECONDS = 25_000  # Groq free tier ~28,800 audio-seconds/day

# --- LLM call behaviour ---
LLM_TIMEOUT_S = 30.0
LLM_MAX_TOKENS = 1024
LLM_TEMPERATURE = 0.6
LLM_MAX_RETRIES = 3  # retries on the last model in a chain
LLM_RETRIES_BEFORE_FALLBACK = 1  # retries before falling back to the next model
LLM_BACKOFF_BASE_S = 1.0
LLM_MAX_WAIT_S = 20.0  # never sleep longer than this for one retry

# --- chat ---
HISTORY_TURNS = 6

# --- audio capture / VAD (P2) ---
AUDIO_SAMPLE_RATE = 16_000  # Hz, mono int16 (what webrtcvad and Whisper want)
AUDIO_INPUT_DEVICE: str | int | None = os.getenv("JARVIS_INPUT_DEVICE") or None  # None = default mic
VAD_AGGRESSIVENESS = 2  # webrtcvad 0..3 (3 = most aggressive at rejecting non-speech)
VAD_FRAME_MS = 30  # webrtcvad accepts 10/20/30 ms frames
VAD_SILENCE_MS = int(os.getenv("JARVIS_VAD_SILENCE_MS", "900"))  # end when this window is ~all quiet
VAD_END_SPEECH_RATIO = 0.2  # "quiet" = at most this share of the window is speech
VAD_MIN_RMS = float(os.getenv("JARVIS_VAD_MIN_RMS", "900"))  # absolute speech energy floor
VAD_NOISE_RATIO = 3.0  # speech must be this many times louder than the learned room floor
VAD_FLOOR_CAP = 800.0  # learned floor never exceeds this (talking right after the hotkey)
VAD_START_TIMEOUT_S = 8.0  # give up if nobody starts speaking within this time
VAD_MAX_UTTERANCE_S = 15.0  # hard cap on one utterance
VAD_MIN_SPEECH_MS = 250  # shorter voiced audio is discarded as noise

# --- barge-in (stop TTS when the user starts talking) ---
BARGE_IN = os.getenv("JARVIS_BARGE_IN", "0").lower() not in ("0", "false", "no", "off")
BARGE_IN_RMS = 1500  # int16 RMS a frame must exceed (keeps speaker echo from triggering)
BARGE_IN_FRAMES = 8  # consecutive loud+voiced 30 ms frames needed (~240 ms)
BARGE_IN_GRACE_S = 0.4  # ignore the mic right after playback starts

# --- playback / TTS ---
AUDIO_PLAYERS = ("ffplay", "mpv", "paplay")  # first one found by `which` is used
TTS_RATE = "+0%"  # edge-tts speaking rate
TTS_PARALLEL = 2  # edge-tts requests in flight (prefetch the next sentence while one plays)
TTS_WARM_SOCKETS = os.getenv("JARVIS_TTS_WARM", "1").lower() not in ("0", "false", "no", "off")
TTS_WS_MAX_IDLE_S = 90.0  # drop pooled edge sockets idle longer than this
TTS_FIRST_CHUNK_CHARS = 40  # cut the first chunk at a clause after this many chars (speak sooner)
TTS_MAX_CHUNK_CHARS = 180  # split run-on sentences at a clause/space beyond this
TTS_DEFAULT_LANG = "en"

# --- voice loop ---
HOTKEY_PTT = os.getenv("JARVIS_HOTKEY", "<ctrl>+<alt>+j")  # press to talk (toggle)
VOICE_MAX_TOKENS = 200

# --- agent (P3) ---
TOOL_PACKAGES = ("interactive", "general", "external")  # jarvis/tools/<pkg>/<one file per tool>
TOOL_OUTPUT_MAX_CHARS = 800  # tool results are truncated to this before going back to the LLM
AGENT_MAX_TOOL_ROUNDS = 4  # llm -> tools loops per request, then the model must answer
AGENT_MAX_TOKENS = 400
AGENT_SUMMARY_BATCH_TURNS = 3  # fold this many old turns into the rolling summary at once
CONFIRM_TIMEOUT_S = 20.0  # unanswered confirmations are denied
ROUTER_MAX_GROUPS = 3
ROUTER_URL_GROUP = "browser"  # group for messages containing a URL/domain
ROUTER_SITE_OVER_APPS = True  # "open youtube": a known site/URL drops the apps group (browser wins)
FASTPATH = os.getenv("JARVIS_FASTPATH", "1").lower() not in ("0", "false", "no", "off")  # regex intents, 0 tokens
HOME_PLACE = os.getenv("JARVIS_HOME_PLACE", "Kathmandu")  # default for weather
HTTP_TIMEOUT_S = 5.0
WEATHER_CACHE_S = 600  # weather results are reused for 10 min
GEO_CACHE_S = 86_400  # geocoder results are reused for a day
# Keyword rules: group -> words/phrases (matched on word boundaries, case-insensitive).
ROUTER_RULES: dict[str, tuple[str, ...]] = {
    "general": ("time", "date", "day is it", "clock", "what day", "o'clock", "baje",
                "kitne baje", "kati bajyo", "bajyo", "samay", "समय", "बजे", "बज्यो", "तारीख", "मिति",
                "time in", "time of"),
    "weather": ("weather", "temperature", "forecast", "rain", "raining", "hot", "cold", "humid",
                "mausam", "मौसम", "barsat", "पानी पर्छ", "बारिश"),
    "files": ("file", "files", "folder", "folders", "directory", "delete", "remove", "rename",
              "move file", "copy file", "trash", "locate", "named", "grep", "ripgrep", "where is",
              "which file", "codebase", "code base", "in my code", "containing", "फाइल", "मिटाओ", "मेटाउ"),
    "system": ("volume", "mute", "unmute", "brightness", "battery", "cpu", "ram", "wifi",
               "bluetooth", "lock", "sleep", "shutdown", "reboot", "screenshot", "clipboard",
               "night light", "dark mode", "wallpaper", "do not disturb"),
    "apps": ("open", "close", "launch", "focus", "window", "app", "application", "snap",
             "workspace", "kill", "minimize", "maximize", "browser", "terminal"),
    "media": ("play", "pause", "resume", "music", "song", "next track", "previous track",
              "playlist", "youtube", "spotify", "गाना"),
    "git": ("git", "commit", "branch", "repo", "repository", "git status", "git log", "diff",
            "staged", "checkout", "changes", "uncommitted"),
    "dev": ("pytest", "run tests", "test suite", "scaffold", "venv", "pip", "requirements", "lint",
            "dependency", "dependencies", "notebook", "tests", "unit tests", "failing tests",
            "doctor", "env doctor", "environment doctor", "environment check", "my environment",
            "dev environment", "python version", "virtualenv", "project", "new project", "fastapi",
            "langgraph", "data science"),
    "web": ("search", "news", "google", "look up", "lookup", "browse", "website"),
    "memory": ("remember", "recall", "note", "notes", "last time", "yesterday", "remind",
               "what did i tell you", "forget", "yaad", "याद", "सम्झ"),
    "browser": ("url", "link", "website", "web site", "site", "youtube", "gmail", "github",
                "chatgpt", "open google", "www", "http", "https"),
    "jobs": ("job", "jobs", "background", "working on", "progress", "job status", "cancel",
             "stop writing", "essay status", "essay", "article", "story", "report", "write a",
             "लेख", "निबंध"),
}
# Descriptions offered to the fast classifier when no rule matched.
TOOL_GROUP_DESCRIPTIONS: dict[str, str] = {
    "general": "time and date (any city or country), simple utilities",
    "weather": "current weather and up to 3-day forecast for any place",
    "files": "find files by name or content; delete, move or rename files and folders",
    "system": "volume, brightness, battery, power, screenshots, clipboard",
    "apps": "open, close, focus or arrange apps and windows",
    "media": "music and video playback",
    "git": "git status, log, diff, commit and branches",
    "dev": "tests, new projects, Python environment checks",
    "web": "web search, news",
    "memory": "remember, recall or forget short notes the user dictates",
    "browser": "open a website or URL in the browser",
    "jobs": "long writing jobs (essays, articles, reports) and background job status/cancel",
}
# Words that suggest multi-step reasoning (router asks for the smart tier).
REASONING_KEYWORDS = ("explain why", "compare", "analyze", "analyse", "step by step", "debug",
                      "figure out", "plan my", "pros and cons")
# Imperative openers: a message with no rule match that starts like this goes to the classifier.
COMMAND_VERBS = ("open", "close", "start", "stop", "run", "show", "set", "turn", "make", "create",
                 "delete", "remove", "check", "find", "play", "pause", "take", "give", "launch",
                 "kill", "install", "send", "search", "list", "move", "copy", "rename", "switch",
                 "increase", "decrease", "lower", "raise", "enable", "disable", "save", "get",
                 "fetch", "read", "write", "lock", "mute", "change", "go")
# Binaries a future shell tool may run (anything else is refused). sudo is never allowed.
SHELL_ALLOWLIST = ("ls", "cat", "head", "tail", "wc", "grep", "rg", "fdfind", "find", "git", "df",
                   "du", "free", "uptime", "whoami", "date", "echo", "pwd", "which", "python3",
                   "pytest", "pip", "xdotool", "wmctrl", "xrandr", "xclip", "pactl", "amixer",
                   "brightnessctl", "upower", "gsettings", "loginctl", "notify-send")

# --- Multitasking (P3b-2): planner, background jobs, rate limiter ---
PLANNER_MAX_TASKS = 4
PLANNER_MAX_TOKENS = 300
LONG_JOB_MIN_WORDS = 150  # writing requests at least this long run as background jobs
WORDS_PER_LINE = 12  # "a 1000-line essay" ~ 12 words per line
WRITER_DEFAULT_WORDS = 600  # essay/article/report without an explicit length
WRITER_MAX_WORDS = 12_000
WRITER_WORDS_PER_SECTION = 500
WRITER_SECTION_MAX_TOKENS = 1500
WRITER_TIER = "writer"
OUTPUTS_DIR = Path(os.getenv("JARVIS_OUTPUTS_DIR", str(DATA_DIR / "outputs")))
JOBS_MAX_WORKERS = int(os.getenv("JARVIS_JOBS_MAX_WORKERS", "2"))
JOBS_NOTIFY = os.getenv("JARVIS_JOBS_NOTIFY", "1").lower() not in ("0", "false", "no", "off")
# Groq free tier per model. Per-model overrides: MODEL_LIMITS[model] = {"tpm": ..., "rpm": ...}.
MODEL_TPM = int(os.getenv("JARVIS_MODEL_TPM", "8000"))
MODEL_RPM = int(os.getenv("JARVIS_MODEL_RPM", "30"))
MODEL_LIMITS: dict[str, dict[str, int]] = {}
RATE_BACKGROUND_RESERVE = 0.3  # share of TPM/RPM background jobs must leave free for interactive
RATE_INTERACTIVE_MAX_WAIT_S = 3.0  # interactive calls wait at most this long, then go anyway
