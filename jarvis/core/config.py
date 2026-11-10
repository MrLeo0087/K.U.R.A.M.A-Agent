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
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")  # optional: Gemini answers when Groq's limits are used up
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_MAX_AGE_S = 120  # ignore Telegram messages sent more than this long before the bot started

# --- LLM models (Groq) ---
LLM_DEFAULT = "openai/gpt-oss-120b"  # "smart" tier: reasoning / multi-tool
LLM_FAST = "openai/gpt-oss-20b"  # "fast" tier: chat, routing, summaries
LLM_VISION = "qwen/qwen3.8-27b"  # screen / image tasks
# Spoken chat without tools: qwen with thinking off starts in ~0.2 s vs ~0.5 s for gpt-oss.
LLM_VOICE = os.getenv("JARVIS_LLM_VOICE", "qwen/qwen3.8-27b")
# coding-agent work asked in General mode -> "say yes to switch the coding agent on" (agent.coding_job, by meaning);
# "general" = coding help that stays in General mode (the selected code: explain / upgrade / replace; how to run)
CODING_JOBS: dict[str, tuple[str, ...]] = {
    "project": ("create a rock paper scissors game in html css and javascript", "make a new react project",
                "build a pygame snake game", "make a rock paper scissors game in python with a ui", "create a fastapi project for a todo app", "make a new project here",
                "create a calculator app with a nice ui in this folder", "build me a website for my portfolio",
                "set up a flask app with login", "create a new python project that scrapes news"),
    "file": ("create a new file calculator.py with a simple calculator", "make a new file app.js with the game logic",
             "create a file named utils.py in this folder and write helper functions"),
    "requirements": ("generate the requirements file", "make requirements.txt for this project",
                     "create a requirements file for my project"),
    "diagram": ("make a diagram of this project", "draw the architecture of my project", "call graph of this file"),
    "general": ("explain the selected code", "upgrade the selected code", "replace the selected code with a better one",
                "what does this function do", "how can i run this code", "explain this error",
                "make this selected code more advanced", "add comments to the selected code"),
}
CODING_JOB_MIN = 0.75
OCR_TRANSLATE_CHARS = 2500  # a read's translation done at once (more: "translate all of it")
OCR_THIS_S = 600  # "what does this mean?" this long after a read means the read text (not the selection)
MODEL_MAX_OUTPUT = {"qwen/qwen3.8-27b": 900}  # Groq's output-tokens-per-minute limit for it is 1000: never ask more

# Gemini (Google, free tier): the fallback AFTER Groq's gpt-oss models and BEFORE qwen (qwen claimed actions it never
# did on 11-01 when both gpt-oss hit their daily limit). Only with GEMINI_API_KEY in .env. Free tier: ~10 requests/min.
LLM_GEMINI = os.getenv("KURAMA_LLM_GEMINI", "gemini-2.5-flash")
LLM_GEMINI_LITE = os.getenv("KURAMA_LLM_GEMINI_LITE", "gemini-flash-lite-latest")  # its own quota, more requests/day
_GEM = [LLM_GEMINI, LLM_GEMINI_LITE] if GEMINI_API_KEY else []

TIERS: dict[str, str] = {"smart": LLM_DEFAULT, "fast": LLM_FAST, "vision": LLM_VISION,
                         "voice": LLM_VOICE}
# Fallback chain per tier (first entry is preferred).
TIER_CHAIN: dict[str, list[str]] = {
    "smart": [LLM_DEFAULT, LLM_FAST, *_GEM, LLM_VISION],  # qwen last: when both gpt-oss models hit their daily limit (200k
    #                                                tokens each, 11-01) KURAMA keeps answering instead of "busy"
    "fast": [LLM_FAST, LLM_DEFAULT, *_GEM, LLM_VISION],  # rate-limited: the smart one, then qwen (its own daily quota)
    "vision": [LLM_VISION, LLM_DEFAULT, *_GEM[:1]],
    # a second, stronger read when the first one couldn't read the text (handwriting, Tamil, a dark photo): Gemini
    # reads handwriting and non-Latin scripts much better; it is only used when the first read failed
    "vision_strong": [*_GEM[:1], LLM_VISION],  # second vision model; the text fallback still answers non-image asks
    "voice": list(dict.fromkeys([LLM_VOICE, LLM_FAST, *_GEM])),
    # Background writer jobs: smart model only (never falls back onto the fast/voice models' TPM).
    "writer": [LLM_DEFAULT, *_GEM[:1]],
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
    LLM_GEMINI: {"thinking_budget": 0},  # no hidden thinking: ~1.5 s replies, fewer tokens
}

# --- STT (Groq Whisper) ---
# the most accurate free model first; turbo (faster, a little less accurate) only when it fails / hits a limit (11-07)
STT_MODEL = "whisper-large-v3"
STT_FALLBACK = "whisper-large-v3-turbo"
STT_LANGUAGES = ("en", "ne", "hi")
# Whisper auto-detect mislabels Nepali as Hindi. Set JARVIS_STT_LANG=ne to pin it.
STT_LANGUAGE_HINT = os.getenv("JARVIS_STT_LANG") or None
STT_PREFER_FALLBACK_LANGS: tuple[str, ...] = ()  # languages that try STT_FALLBACK first (none: large-v3 is best)
# Run a Nepali-forced large-v3 pass in parallel with auto-detect and pick the trustworthy one
# (Whisper mislabels Nepali as English/Slovak/Hindi). Doubles STT calls, adds no latency.
STT_DUAL = os.getenv("JARVIS_STT_DUAL", "1").lower() not in ("0", "false", "no", "off")
STT_EN_MIN_LOGPROB = -0.6  # auto "English" below this confidence is treated as suspicious
# Whisper vocabulary hint (biases spelling of names/apps; tested not to break hi/ne detection).
STT_NO_SPEECH_MAX = 0.6  # Whisper's no_speech_prob above this...
STT_GARBAGE_LOGPROB = -1.0  # a short transcript (<= 4 words) below this confidence = noise ('The', 'RUN', 'E aí')
STT_FOREIGN_MAX_LOGPROB = -0.6  # Whisper says a language we don't speak AND confidence is below this = noise
STT_UNSURE_LANE_MIN = 0.66  # unsure speech (foreign label, low confidence) below this for every lane = ask again
STT_NOISE_MAX_LOGPROB = -0.8  # ...and confidence below this: background noise, not a command
# The owner's own names and places, so speech-to-text spells them right (dictation + voice chat). Add more in .env:
# JARVIS_MY_WORDS="Darshan Chaulagain, Nepalgunj, ..."
MY_WORDS = os.getenv("JARVIS_MY_WORDS", "Darshan Chaulagain, Nepalgunj, Kathmandu, Pokhara")
MY_WORDS_NE = os.getenv("JARVIS_MY_WORDS_NE", "दर्शन चौलागाईं, नेपालगञ्ज, काठमाडौं, पोखरा")
STT_PROMPT = os.getenv("JARVIS_STT_PROMPT", MY_WORDS + ", "
                       "Kurama, KURAMA, VS Code, Bluetooth, Brave, YouTube, Spotify, Instagram, Telegram, Wi-Fi, gesture control, "
                       "GitHub, Colab, QR code, read later, workspace.")
# Common mishearings fixed after transcription (regex, case-insensitive, word-bounded).
# Typing slips seen in the real chat log, fixed before matching (word-level, case-insensitive)
TYPO_FIXES: dict[str, str] = {
    "repalce": "replace", "replce": "replace", "reaplce": "replace", "relpace": "replace", "iamge": "image", "imgae": "image", "imaeg": "image", "imgage": "image", "volumn": "volume", "volum": "volume", "valume": "volume", "volumne": "volume", "voulme": "volume",
    "alram": "alarm", "alaram": "alarm", "allarm": "alarm", "remainder": "reminder", "remiander": "reminder",
    "traning": "training", "trainig": "training", "usuage": "usage", "useage": "usage", "staus": "status",
    "statsu": "status", "thsi": "this", "niw": "now", "insdie": "inside", "insde": "inside", "plz": "please",
    "pls": "please", "wht": "what", "whta": "what", "teh": "the", "laptop.doctor": "laptop doctor",
    "scrrenshot": "screenshot", "screnshot": "screenshot", "brigthness": "brightness",
    "telgram": "telegram", "telegarm": "telegram", "downlaod": "download", "donwload": "download",
    "foler": "folder", "fodler": "folder", "folde": "folder", "summarise": "summarize",
}
STT_FIXES: dict[str, str] = {
    r"\b(?:b\.?\s?s\.?|bee\s?s|be\s?s)\s+code\b": "vs code",  # owner 11-01: "VS Code" heard as "BS code"
    r"^\W*p\.?\s?s\.?\s+(?=(?:the\s+)?(?:super|ctrl|control|alt|shift|enter|escape|tab|f\d)\b)": "press ",  # "P.S. Super Key" (09:35)
    r"\b(?:stobas|stopbus|stop\s+was|stop\s+watts?|stopwach)\b": "stopwatch",
    r"\b(?:set|shat|shot|sut)\s+down\s+(?:the\s+)?(?:letter|ladder|laptop|leptop)\b": "shut down the laptop",
    r"\b(better|good|more|clean|simple|clear)\s+(?:end|an|in)\s+detail(?:ed)?\b": r"\1 and detailed",
    r"\b(this|the|my|better|python|selected|selective|that|whole|most|mouse|simple|clean|detail|detailed|good|new|"
    r"improved)\s+coat\b": r"\1 code",
    r"\bselective\b": "selected",
    # 'this word' heard as 'this wood / road / ward' when asking for a meaning or translation (owner's log)
    r"\b(this|that|the)\s+(?:wood|road|ward|world)\b(?=.*\b(?:mean|meaning|nepali|hindi|english|translat|convert)\w*)": r"\1 word",
    # Whisper hears 'task' as 'tax' / 'tags' (owner): only real tax words stay tax
    r"(?<!income )(?<!sales )(?<!road )(?<!vat )(?<!pay )(?<!property )\btaxes\b(?!\s+(?:return|rate|refund|office|bill))": "tasks",
    r"(?<!income )(?<!sales )(?<!road )(?<!vat )(?<!pay )(?<!property )\btax\b(?!\s+(?:return|rate|refund|office|bill|free))": "task",
    r"\b(my|recent|todo|to-do|long|daily|today'?s|current|the)\s+tags\b": r"\1 tasks",
    r"\b(?:q\.?\s?mar|qmar|key\s?mark|q\.?\s?are|queue\s+are|cue\s+are|kyu\s?ar|q\.?\s?r\.?)\s+(?:code|word|cord|coat)s?\b": "QR code",
    r"\b(this|the|that|a|selected|highlighted)\s+(?:o\.?\s?auth|oauth|wordt|ward)\b": r"\1 word",  # "this word" misheard
    r"\bselect(?:ed)?\s+output\b": "selected word",
    r"\bread\s+letters?\b(?=\s+(?:link|links|list|page|pages|article|articles|item|items)\b)": "read later",
    r"\b(for|to|in|my)\s+read\s+letters?\b": r"\1 read later",
    r"\b(?:return|written|britain|ridden)\s+(in|on)\s+(?=(?:the\s+)?(?:selected|this|that|my)\s)": r"written \1 ",  # "written in"
    r"\b(?:space|speak|speec|speach|spich)\s+(?:to|2)\s+text\b": "speech to text",
    r"\b(?:b\.?\s?s\.?|be\s?as|versus|vs\.?|v\.\s?s\.)\s+(?:code|cold|cord|court|coat)\b": "VS Code",
    r"\bvisual\s+studio(?:\s+code)?\b": "VS Code",
    r"\bbear\s+skull\b": "VS Code",
    r"\b(?:karama|kurma|corama|kurrama)\b": "Kurama",
    r"\bkura\s+(?:may|ma|mah)\b": "Kurama",  # "the Kura may sleep"
    r"\bzarvis\b": "Jarvis",
    r"^\s*(?:wariyo|warriyo|huarion|hu\s?ar\s?yu|who\s?r\s?u)\s*[?.!]*\s*$": "Who are you?",
    r"\bslip\b(?=\s+(?:my|the|this|now|mode|kurama|laptop|computer)\b|\s*[.!?]*$)": "sleep",  # "slip my laptop"
    r"^\s*hut\s+down\b": "shut down",
    r"^\s*(?:done|mark)\s+(?:too|to)\s*[.!]*$": "done 2",  # Whisper writes 'done 2' as 'Done too.'
    r"^(mark\s+\d{1,2})\s+is\s+(done|complete(?:d)?|finished)": r"\1 as \2",
    r"\bsit\b(?=\s+(?:the\s+|my\s+|a\s+)?(?:brightness|volume|timer|alarm|reminder|wallpaper)\b)": "set",  # "sit the brightness"
    r"\b(start|stop|reset|pause)\s+(?:or|our|a|uh)\s+stopwatch\b": r"\1 the stopwatch",
    r"\b(?:remiander|remainder|reminer|remindar)\b(?!\s+of\b)": "reminder",
    # "turn off/on" as Whisper often hears it with an accent: "tone of", "tron off", "torn of", "pon up"
    r"\b(?:tone|tron|torn|tan|tun|ton|tum)\s+(?:of+|op)\b": "turn off",
    r"\b(?:tone|tron|torn|tan|tun|ton|tum|pon)\s+(?:on|up)\b": "turn on",
}
SOUNDS = os.getenv("KURAMA_SOUNDS", "1").lower() not in ("0", "false", "no", "off")  # alarm/timer/reminder sounds
ALARM_RINGS = 6  # how many times an alarm rings

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
STT_LOG = DATA_DIR / "logs" / "stt.log"  # one line per recognition (what was heard, confidence)
LOG_DIR = DATA_DIR / "logs"
# Request traces for improving KURAMA (MONITORING.md): one row per request; kept when KURAMA is reset
TRACING = os.getenv("KURAMA_TRACING", "1").lower() not in ("0", "false", "no", "off")
TRACE_DB = Path(os.getenv("KURAMA_TRACE_DB", str(DATA_DIR / "traces.db")))
TRACE_KEEP_DAYS = int(os.getenv("KURAMA_TRACE_KEEP_DAYS", "90"))

# --- daily token budgets (self-imposed, ~90% of Groq free-tier TPD) ---
DAILY_TOKEN_BUDGET: dict[str, int] = {
    LLM_DEFAULT: 180_000,
    LLM_FAST: 180_000,
    LLM_VISION: 90_000,
}
STT_DAILY_AUDIO_SECONDS = 25_000  # Groq free tier ~28,800 audio-seconds/day

# --- LLM call behaviour ---
LLM_TIMEOUT_S = 30.0
AGENT_TIMEOUT_S = 15.0  # interactive turns (text, Telegram): a stuck call is retried instead of waiting 30 s
VOICE_TIMEOUT_S = 10.0  # spoken chat: give up sooner (then retry/fall back) instead of 30 s of silence
LLM_MAX_TOKENS = 1024
LLM_TEMPERATURE = 0.6
LLM_MAX_RETRIES = 3  # retries on the last model in a chain
LLM_RETRIES_BEFORE_FALLBACK = 1  # retries before falling back to the next model
LLM_BACKOFF_BASE_S = 1.0
LLM_COOLDOWN_S = 120.0  # a model that answered 429 beyond the wait limit is skipped this long (its Retry-After if longer)
LLM_MAX_WAIT_S = 20.0  # never sleep longer than this for one retry

# --- chat ---
HISTORY_TURNS = 6
HISTORY_MSG_MAX_CHARS = 420  # each remembered message is cut to this for the LLM history (full text stays in the DB)

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

# --- wake ---
# "Hey KURAMA" wake word (P12): webrtcvad + noise gate find short bursts; only those are sent to the
# free Google Web Speech recognizer (SpeechRecognition, no key), Groq Whisper if Google fails.
WAKE_ENABLED = os.getenv("JARVIS_WAKE", "1").lower() not in ("0", "false", "no", "off")
WAKE_ENGINE = os.getenv("JARVIS_WAKE_ENGINE", "groq")  # groq (Whisper: hears "KURAMA" right) | google
WAKE_GOOGLE_LANG = os.getenv("JARVIS_WAKE_LANG", "en-IN")
WAKE_GOOGLE_TIMEOUT_S = 4.0
WAKE_GOOGLE_RETRY_S = 60.0  # after a Google failure (offline), use Groq for this long
WAKE_MAX_CHECKS_PER_MIN = int(os.getenv("JARVIS_WAKE_CHECKS_PER_MIN", "12"))
# Wake bursts must be this loud (room noise sent 11 bursts/min to Google at the turn-VAD level of 900).
WAKE_MIN_RMS = float(os.getenv("JARVIS_WAKE_MIN_RMS", "900"))  # lower = hears a quieter/farther "KURAMA"
WAKE_MATCH_RATIO = 0.7  # difflib ratio for wake-name tokens (lower = more forgiving of mishearings)
WAKE_PHRASES = ("start system", "start the system", "system start", "start kurama system")  # wake without the name
WAKE_UP_ALONE = os.getenv("JARVIS_WAKE_UP_ALONE", "1").lower() not in ("0", "false", "no", "off")  # "wake up" wakes
WAKE_NAME_ALONE = os.getenv("JARVIS_WAKE_NAME_ALONE", "1").lower() not in ("0", "false", "no", "off")
WAKE_BURST_MIN_S = 0.4  # speech bursts outside this range are never recognized
WAKE_BURST_MAX_S = 3.0
WAKE_LONG_BURSTS = True  # 2.5-6 s bursts: check the first WAKE_LONG_HEAD_S ("hey jarvis what's the time")
WAKE_LONG_MAX_S = 6.0
WAKE_LONG_HEAD_S = 2.0
WAKE_GAP_MS = 450  # this much quiet ends a burst
WAKE_IDLE_S = float(os.getenv("JARVIS_WAKE_IDLE_S", "45"))  # awake -> sleeping after this long without speech
WAKE_ACK = os.getenv("JARVIS_WAKE_ACK", "beep")  # beep (instant, local) | voice ("Yes?") | none
WAKE_STOP_WORD = True  # in wake mode, saying "stop" while KURAMA speaks interrupts playback
WAKE_STOP_RMS = 1500.0  # the "stop" burst must be this loud (speaker echo is filtered by length)
WAKE_DEBUG = os.getenv("JARVIS_WAKE_DEBUG", "0").lower() not in ("0", "false", "no", "off")

# --- playback / TTS ---
AUDIO_PLAYERS = ("ffplay", "mpv", "paplay")  # first one found by `which` is used
TTS_RATE = os.getenv("JARVIS_TTS_RATE", "+15%")  # edge-tts speaking rate (a bit faster than default)
TTS_PARALLEL = 2  # edge-tts requests in flight (prefetch the next sentence while one plays)
TTS_WARM_SOCKETS = os.getenv("JARVIS_TTS_WARM", "1").lower() not in ("0", "false", "no", "off")
TTS_WS_MAX_IDLE_S = 90.0  # drop pooled edge sockets idle longer than this
TTS_FIRST_CHUNK_CHARS = 40  # cut the first chunk at a clause after this many chars (speak sooner)
TTS_MAX_CHUNK_CHARS = 180  # split run-on sentences at a clause/space beyond this
TTS_DEFAULT_LANG = "en"

# --- voice loop ---
HOTKEY_PTT = os.getenv("JARVIS_HOTKEY", "<ctrl>+<alt>+j")  # press to talk (toggle)
# Hold-to-talk anywhere (jarvis/core/ptt.py, in the API server): hold the key, speak, let go. pynput key name.
PTT_ENABLED = os.getenv("KURAMA_PTT", "1").lower() not in ("0", "false", "no", "off")
PTT_KEY = os.getenv("KURAMA_PTT_KEY", "alt")  # hold Alt alone, left or right (owner 11-01: Ctrl is busy with
#                                                 shortcuts); Alt+Tab / Alt+F4 never talk (another key = a shortcut)
PTT_DISMISS_KEY = os.getenv("KURAMA_PTT_DISMISS", "double:shift")  # double-tap Shift ("double" = the talk key, or super+x)
PTT_START_DELAY_S = 0.3  # one key alone (Alt): listen only after it is held alone this long (Alt+Tab never does)
PTT_DOUBLE_TAP_S = 0.4  # two quick taps within this = close the reply caption + stop speaking
PTT_DEBOUNCE_S = 0.15  # a held Space auto-repeats (release+press pairs): a release counts after this quiet gap
PTT_MIN_HOLD_S = 0.35  # shorter taps are ignored (0 tokens)
VOICE_MAX_TOKENS = 200

# --- agent (P3) ---
TOOL_PACKAGES = ("core", "interactive", "general", "external")  # jarvis/tools/<pkg>/<one file per tool>
# v2: the AI only sees the general tools in jarvis/tools/core (group "core"); the router still picks the old groups and
# each group is served by the general tool(s) covering it. Groups no general tool covers fall back to their old tools.
CORE_TOOLS = os.getenv("KURAMA_CORE_TOOLS", "1").lower() not in ("0", "false", "no", "off")
CORE_MAX_TOOLS = 3  # general tools sent per request (each ~200-300 tokens)
CORE_COVERS: dict[str, tuple[str, ...]] = {
    "apps": ("apps", "browser", "windows"),
    "laptop": ("audio", "display", "desktop", "power", "system", "screen"),
    "files": ("files", "filesearch", "daily"),
    "telegram": ("telegram",),
    "schedule": ("schedule", "clock"),
    "todo": ("todo",),
    "media": ("media",),
    "web": ("web", "browser"),
    "info": ("general", "weather", "daily", "memory", "system", "power"),
    "memory": ("memory", "knowledge", "links", "self"),
    "create": ("image", "jobs", "tracker"),
    "text": ("clipboard", "screen", "windows", "devutils"),
    "code": ("dev", "git", "codequality", "watch", "devutils"),
    "life": ("tracker", "study", "usage", "schedule"),
    "kurama": ("self", "usage", "jobs", "telegram", "toolsmith"),
    "run_command": ("dev", "toolsmith"),  # only for coding / a command you ask for (system questions have tools)
    "run_python": ("daily", "dev", "toolsmith"),
}
TOOL_OUTPUT_MAX_CHARS = 800  # tool results are truncated to this before going back to the LLM
# Workspace card: tool results with this many lines (or longer than TOOL_OUTPUT_MAX_CHARS) are shown there in full
# Simple actions answer themselves with the fast path's templates: no second LLM call just to say "done"
# (tool -> fast-path intent used to word the reply; None = fixed sentence below)
DIRECT_REPLY_TOOLS = {"open_url": "open", "open_app": "open", "audio": "audio", "brightness": "brightness",
                      "media_control": "media", "lock_screen": "lock",
                      "screenshot": "screenshot", "send_message_telegram": None, "get_time": "time",
                      # finishing actions: the tool's own words are the reply, so the AI can't claim what another
                      # tool did ('The second tab is now active' after only focusing Brave, trace 9a7787367d47)
                      "close_app": "said", "open_folder": "said", "open_path": "said", "app_control": "said",
                      "window": "said", "generate_image": "said", "write_document": "said"}  # a job STARTED is
#                     not "has been sent" (trace 54045016: the AI said the picture was sent while it was being made)
# Phase 3 token cut: these actions' own sentence ends a SHORT single request too (no second AI call, ~1,000 tokens
# each; 2.2 AI calls per AI turn on 10-29..11-01). Longer / multi-part requests still let the AI go on.
DIRECT_REPLY_SINGLE = ("make_folder", "set_timer", "set_alarm", "add_reminder", "youtube", "video_download", "music",
                       "write_file", "send_file_telegram", "move_path", "delete_to_trash", "saved_links",
                       "organize_files", "code_to_file")
# tools whose own sentence IS the answer: no second AI call just to repeat it (most AI requests made 2 calls,
# ~2,700 tokens, 11-04). An error / a question back still goes to the model.
DIRECT_REPLY_ANSWERS = ("expenses", "contacts", "schedules", "stopwatch", "laptop_toggle", "laptop_guard", "share_wifi",
                        "wifi_share", "battery_status", "internet_doctor", "weather", "get_date", "read_later",
                        "calculate", "lock_screen", "goals", "habits", "status_now", "disk_cleaner",
                        "backup", "find_files", "recall", "remember", "laptop_doctor", "convert_file",
                        "folder_lock", "do_not_disturb", "night_light", "set_theme", "focus_mode", "cleanup",
                        "location_history", "find_my_phone", "remote_desktop", "token_usage", "daily_digest",
                        "list_folder", "ask_ai")  # (11-10 the AI answered the question itself after sending
#                        it to ChatGPT; 11-06 the AI re-wrote a listing with folders that do not exist)
DIRECT_REPLY_TOOLS.update({k: "said" for k in DIRECT_REPLY_SINGLE + DIRECT_REPLY_ANSWERS})
DIRECT_REPLY_MAX_WORDS = 14
DIRECT_REPLY_STEPS = {"window": ("focus", "list"), "app_control": ("task", "enable"), "saved_links": ("list", "get"),
                      "music": ("playlists", "status", "now"), "organize_files": ("edit",)}  # these continue a task
CONTEXT_TOOL_SEL_MIN = 0.80  # the text tool joins an AI request (VS Code open) when its meaning is a selection action
CONTEXT_TOOL_MARGIN = 0.10  # ... or the text area is this close to the best area
# --- OCR (read_text): Tesseract first (0 tokens); the vision model only for handwriting / hard photos ---
OCR_LANGS = os.getenv("KURAMA_OCR_LANGS", "eng+nep")
OCR_MIN_CONF = float(os.getenv("KURAMA_OCR_MIN_CONF", "75"))  # Tesseract's mean word confidence below this = poor
OCR_MIN_ENGLISH = 0.85  # Tesseract's English must be this share of real dictionary words, else the AI reads it
OCR_MIN_DENSITY = 60.0  # screen capture: fewer words per megapixel = a photo/handwriting Tesseract can't see
OCR_VISION = os.getenv("KURAMA_OCR_VISION", "1").lower() not in ("0", "false", "no", "off")
# a dashboard answer longer than this goes to the workspace in full; the chat gets one short line
CHAT_MAX_CHARS = int(os.getenv("KURAMA_CHAT_MAX_CHARS", "380"))
CHAT_MAX_LINES = int(os.getenv("KURAMA_CHAT_MAX_LINES", "3"))
LIVE_CHAT_MAX_CHARS = 600  # live answers (scores, prices) up to this many chars stay in the chat
WORKSPACE_MIN_LINES = 40  # only big results go to the Workspace (simple answers stay in the chat)
WORKSPACE_MIN_CHARS = 4000
WORKSPACE_SHOW_ALL = ("list_folder", "training")  # results the user wants to see in full, to pick from
TOOL_OUTPUT_FULL_CHARS = 3500  # the user asked for everything ("the whole list"): the LLM gets this much
WORKSPACE_SKIP_TOOLS = ("read_webpage", "search_knowledge", "ask_knowledge", "recall_session", "jobs",
                        "about_me", "write_document", "skills", "find_capability",
                        "todo", "schedules", "read_later")  # lists with their own views never clutter the workspace
# A tool still running after this many seconds keeps going as a background job; the user can keep talking and
# is told when it's done (0 = off)
TOOL_BACKGROUND_AFTER_S = float(os.getenv("KURAMA_TOOL_BG_AFTER_S", "3"))
TOOL_BACKGROUND_MIN_S = {"music": 12.0, "media": 12.0, "web": 8.0, "web_search": 8.0, "wikipedia": 8.0}  # finding a song takes 2-6 s: music never "goes to the
# background" with a job number (11-03 f28ec8c6: 'Play some Hindi song' -> job #64 at 3.0 s); a web lookup is 3-6 s
# (11-03 6282db24: "Searching in the background" for a Wikipedia summary)
TOOL_BACKGROUND_MAX_S = 8.0
TELEGRAM_TOOL_WAIT_S = 25.0  # a Telegram request waits this long for its tool before it becomes a job  # a tool's own usual run time decides the wait (safety._wait_for), never longer than this
TOOL_NO_BACKGROUND = ("start_job", "generate_image", "write_document", "jobs", "make_tool",
                      "focus_mode", "gesture_control", "power_off", "suspend_computer",
                      "read_text", "scan_qr")  # these wait for the user to drag a box: never "still working"
TOOLSMITH_OFFER = True  # a refusal on a real task always offers to build a tool (asks first)
AGENT_MAX_TOOL_ROUNDS = 4  # llm -> tools loops per request, then the model must answer
AGENT_MAX_TOKENS = 400
AGENT_SUMMARY_BATCH_TURNS = 3  # fold this many old turns into the rolling summary at once
TURN_WAIT_S = 25.0  # a message waits this long for the one before it, then says "still working on it"
TURN_STUCK_S = 150.0  # a request running longer than this is left behind (its stacks logged) so KURAMA answers again
CONFIRM_TIMEOUT_S = 20.0  # unanswered confirmations are denied
ROUTER_MAX_GROUPS = 3
# Free phrasing for tools: paraphrases embedded by the semantic router (0 tokens), so "enable speech to text
# mode" finds dictate even though no keyword rule says so. Add a few lines here for any tool that gets missed.
TOOL_EXAMPLES: dict[str, tuple[str, ...]] = {
    "claude_code": ("watch my claude code", "what is claude code doing", "give me the claude code report",
                    "stop watching claude code"),
    "nepal_docs": ("what is the fee for nepal citizenship", "what is the overspeeding rule in nepal",
                   "what is the divorce process in nepal", "which is the largest district of nepal"),
    "open_path": ("open this folder in vs code", "open downloads in vs code", "open main.py in vscode",
                  "open the kurama project in code", "open /home/leo/Downloads/test in vs code", "open it in vs code"),
    "move_path": ("rename this folder to old_test", "rename the folder test to test2", "rename report.pdf to final",
                  "move this file to downloads", "change the folder name to projects"),
    "make_folder": ("create a new folder in downloads", "make a folder named test in documents", "create folder here",
                    "new folder called photos on the desktop"),
    "write_file": ("create a markdown file named notes", "make a new text file called todo", "create a new file notes.md",
                   "save this as a file in downloads", "write hello into a new file", "create an empty python file"),
    "open_url": ("open youtube", "youtube kholo", "google khol", "facebook kholdeu", "open github in the browser",
                 "go to gmail", "kholo chatgpt", "open the website of tribhuvan university"),
    "page_summary": ("what is this page about", "look at the screen and tell me what this website is about",
                     "summarize this web page", "what is this website showing"),
    "saved_links": ("save this link as facebook", "this is the link for claude code, save it", "give me the link of my "
                    "facebook", "what's my grok link", "open my github link", "show my saved links"),
    "goals": ("my exam is in 30 days, remind me every day", "I started a project that ends in 6 months, ask me daily "
              "what I did", "ask me every evening whether I studied", "how many days are left until my exam",
              "what did we do today in the project", "show my goals", "make the project report", "pause my exam goal"),
    "dictate": ("enable speech to text mode", "turn on speech to text", "voice typing on", "type with my voice",
                "write down what I speak", "start voice input", "let me speak instead of typing",
                "convert my speech into text in this box", "turn off speech to text", "stop voice typing",
                "speech to text", "transcribe what I say into the document"),
    "mute_alerts": ("don't send RAM warnings for 20 minutes", "mute all alerts for an hour", "pause the location "
                    "messages for 2 hours", "do not send this notification for 30 minutes", "unmute alerts",
                    "which alerts are muted", "stop the resource warnings for today"),
    "text_assist": ("what does this mean", "explain the highlighted sentence", "what is the meaning of this word in "
                    "nepali", "translate the selected paragraph into nepali", "explain this function",
                    "optimize the selected code", "write a calculator function here in vs code", "explain this file",
                    "fix this text", "correct the selected sentence", "make the highlighted text professional",
                     "improve my writing", "rephrase what I selected", "make this paragraph sound better",
                     "translate the selected text", "correct my english", "make my message polite",
                     "write this better", "fix the spelling mistakes in this"),
    "folder_lock": ("hide my folder with a password", "protect this folder", "put a password on my files",
                    "encrypt my photos folder", "keep this folder private", "secure my documents with a password",
                    "open the locked folder", "remove the password from my folder", "decrypt the file"),
    "share_wifi": ("give the wifi password to my friend", "how can my friend join my wifi",
                   "what is my wifi password", "show the wifi qr code", "connect my phone to this wifi",
                   "let a guest use the internet here"),
    "kaggle_train": ("use kaggle to train my model", "train it on a free gpu", "I don't have a gpu, run it in the cloud",
                     "did my kaggle job finish", "run my notebook on kaggle", "send training to the cloud gpu",
                     "check the kaggle training"),
    "organize_files": ("my downloads folder is a mess, fix it", "sort my files", "rename my photos properly",
                       "put my downloads in order", "clean up this messy folder", "arrange my files into folders",
                       "give my files proper names", "undo the organizing"),
    "video_download": ("save this youtube video", "get me the song as mp3", "download the movie in full hd",
                       "keep this video offline", "grab the audio from this video"),
    "convert_file": ("change this pdf to word", "turn the markdown into a pdf", "make a pdf from these images",
                     "I need this as a png", "export the notes as pdf", "extract text from this scanned pdf"),
    "install_app": ("get vlc on my laptop", "I need zoom installed", "remove spotify from my computer",
                    "update all my software", "download and set up obs"),
    "wifi_share": ("send this to my phone without internet", "transfer the folder to my mobile on the same network",
                   "share this big file over the local network"),
    "laptop_doctor": ("which process uses the most ram", "top 5 processes by memory", "what is eating my ram",
                      "list the apps using the most memory", "why is my laptop slow"),
    "send_message_telegram": ("send the link in my telegram", "send that download link to my telegram",
                              "send this text to my phone", "message me this on telegram"),
    "contacts": ("save my friend's number", "what is ram's number", "add a new contact", "find sita in my contacts"),
    "live_search": ("what happened in the match today", "latest price of petrol", "is it raining in pokhara now",
                    "current news about the election", "score of the game right now"),
    "make_tool": ("build me a tool that counts words in a pdf", "make a new tool for this", "create a skill that "
                  "does this every time", "write a tool to do it", "you don't have a tool for this, build one"),
    "app_control": ("click on the settings button", "go to the next tab", "press control s", "type my email here",
                    "turn on bluetooth from the settings app"),
}
# Semantic router (jarvis/core/semantic.py): tool groups by meaning, 0 LLM tokens. Used when no keyword rule
# matches (instead of the LLM classifier) and to add a strongly meant group the keywords missed.
SEMANTIC_ROUTER = os.getenv("KURAMA_SEMANTIC_ROUTER", "1").lower() not in ("0", "false", "no", "off")
SEMANTIC_MIN = 0.66  # best similarity needed to trust a group (bge-small cosine; calibrated on real phrasings)
SEMANTIC_MARGIN = 0.03  # runners-up this close to the best one are sent too
SEMANTIC_ADD_MIN = 0.76  # with keyword matches, a different group is added only when this sure
SEMANTIC_OVER_CHAT = 0.03  # a group must beat the best plain-chat example by this much
FILES_CONTEXT = os.getenv("KURAMA_FILES_CONTEXT", "1").lower() not in ("0", "false", "no", "off")  # Files app context
MEANING_GATE_MARGIN = 0.15  # a shortcut runs only if its area scores within this of the best area (by meaning)
# Shortcuts whose pattern takes ANY words as their subject (live search: "show <team> result") must also be (nearly)
# the best area by meaning: "show job 1 result" made "job 1" a sports team (web 0.72 vs jobs/schedule 0.75).
MEANING_GATE_STRICT = {"live": 0.02, "app": 0.03}  # app: "set up a fastapi skeleton" is a new project, not an install
# Selection first (Phase C): when text/code is highlighted (VS Code / browser / another app), a request whose MEANING
# is one of these actions is about the selection, whatever the words. Phrasings, never keywords.
SELECTION_EXAMPLES: dict[str, tuple[str, ...]] = {
    "explain": ("explain this", "what does this mean", "what is this code about", "what does this code do",
                "what does this function do", "explain the selected code", "tell me what this is", "what is this",
                "help me understand this", "how does this work", "what is going on here", "describe this code",
                "explain this paragraph", "what is it saying", "what is this about", "explain it simply",
                "what does this line do", "meaning of this word", "what is the meaning of this",
                "what is the main idea here"),
    "improve": ("make this better", "improve this", "fix this", "fix the grammar", "refactor this code",
                "optimize this code", "clean this up", "make it more readable", "rewrite this more formally",
                "fix the bug in this", "make this shorter", "correct this", "make it sound professional",
                "make this code faster", "format this code", "rewrite this", "polish this text",
                "format this paragraph", "format the selected paragraph", "format this text into markdown",
                "turn this paragraph into a structured markdown", "structure this text with headings and bullets",
                "make this paragraph into bullet points", "rewrite the selected paragraph", "fix this paragraph",
                "make this paragraph clearer", "format this paragraph into a markdown structure", "make it markdown",
                "put this in markdown", "fix the selected code", "fix selected code and replace it", "update this code",
                "update the selected code", "clean up the selected code", "improve the selected function"),
    "complete": ("complete this", "finish this function", "complete the code", "fill in the missing part",
                 "implement this todo", "finish writing this", "complete the selected function"),
    "translate": ("translate this", "translate this to nepali", "what is this in hindi", "say this in english",
                  "convert this to nepali", "translate the selected text", "translate this paragraph"),
    "summary": ("summarize this", "give me the gist", "what is the main point", "tl;dr", "summarize the selected paragraph",
                "in short what does it say", "short summary of this"),
    "use": ("how do i use this function", "how can i run this function", "give me an example of using this",
            "show me how to call this", "how to use this class"),
    "run": ("run this", "run the selected code", "execute this code", "what is the output of this", "run it"),
    "ask": ("write tests for this", "add docstrings to this", "add type hints to this", "convert this to javascript",
            "what is the time complexity of this", "find bugs in this code", "add comments to this code",
            "draw a flowchart of this", "what inputs break this function", "is this code correct",
            "write a unit test for the selected function", "rename the variables in this", "why is this slow",
            "what is wrong with this code"),
}
SELECTION_MIN = 0.78  # a request this close to a selection action is about the highlighted text...
SELECTION_MARGIN = 0.02  # ...unless another area (not the selection's own) is clearly closer
# A tool-less answer that MEANS "I did it" (meta.claims_by_meaning): retried with tools, never delivered as done.
CLAIM_MIN, CLAIM_MARGIN = 0.65, 0.12
CLAIM_EXAMPLES = ("I opened it for you", "done, I sent the message", "I created the file in your workspace",
                  "here is the image I made for you", "the volume is now at 80 percent", "I saved the link",
                  "playing the song now", "I made a new folder", "the folder has been deleted",
                  "I set a reminder for 5 pm", "your plan is ready in the workspace", "I closed the app",
                  "got it, I'll remember that", "okay, from now on I will open that one")  # 0c4641e3: promised, saved nothing
NOT_CLAIM_EXAMPLES = ("the sky is blue because of light scattering", "hello, how can I help you today",
                      "I'm sorry you're feeling low", "here are some tips to be happy", "a good name would be shadow",
                      "I don't know what you mean", "could you say that again", "here is a quick explanation",
                      "gravity is the force that pulls things together", "I'm doing great, thanks",
                      "you could try opening the settings app", "which folder do you mean?")
# Lanes (master plan phase 1, docs/MASTER_PLAN.md): what KIND of request it is, by meaning (jarvis/core/lanes.py).
# A confident "general" = no tools, the small fast model, one call (owner 11-02: general must answer very quickly).
LANE_MIN = 0.80  # below this for every lane = unclear (garbled speech, or something new: the old routing decides)
LANE_GENERAL_MARGIN = 0.03  # general must beat every other lane by this much to skip the tools
LANE_EXAMPLES: dict[str, tuple[str, ...]] = {
    # Nepal's laws, legal processes, government services, fees and Nepal general knowledge: the Nepal documents
    # service (core/nepaldocs.py). Not live data (news, prices, scores today): that is "search".
    "nepal": ("what is the fee for nepal citizenship", "how do i make a citizenship certificate in nepal",
              "what is the overspeeding rule in nepal", "what is the fine for drunk driving in nepal",
              "what is the marriage registration process in nepal", "how does divorce work in nepal",
              "when was the constitution of nepal made", "which is the largest district of nepal",
              "which is the smallest district of nepal", "how to get a passport in nepal",
              "what documents are needed for a driving license in nepal", "what is the punishment for theft in nepal law",
              "how to register land in nepal", "what is the tax on land sale in nepal", "how many provinces does nepal have",
              "what are the fundamental rights in the nepal constitution", "how to register a company in nepal",
              "what is the legal age of marriage in nepal", "what is the process for a birth certificate in nepal",
              "how to file a case in a nepal court", "what does the nepal labour act say about leave",
              "who appoints the chief justice of nepal", "what is the inheritance law in nepal",
              "explain the citizenship law", "what does the law say about divorce", "tell me about nepal traffic rules",
              "what is the process to get a national id card", "what is the penalty for not wearing a helmet"),
    "general": (
        "how are you", "hello bro how are you", "what's going on with you", "kya ho raha hai", "k xa khabar",
        "tell me a joke", "i am sad today", "i feel tired", "i am bored", "i am happy today", "thank you so much",
        "what is gravity", "explain machine learning simply", "who was isaac newton", "why is the sky blue",
        "what does photosynthesis mean", "what is the difference between ram and storage", "how does a car engine work",
        "do you think ai is dangerous", "what is your opinion on this", "give me advice to stay motivated",
        "how can i be happy", "suggest a name for a black cat", "say hi in three words", "what is the capital of japan",
        "how many legs does a spider have", "who are you", "what can you do", "are you a robot", "you are funny",
        "good morning how was your night", "let's chat for a bit", "okay go on", "tell me something interesting",
        "translate thank you into nepali", "how do i learn python fast",
    ),
    "search": (
        "what is the latest news", "who won the match today", "what is the score of barcelona", "price of gold today",
        "bitcoin price now", "what is the weather today", "will it rain tomorrow in kathmandu", "latest result of chelsea",
        "what happened in nepal today", "current dollar rate", "search the web for new laptops", "news about ai this week",
        "when is the next football match", "stock price of tesla",
    ),
    "create": (
        "write an essay about nepal", "write a poem about rain", "make python code for a calculator", "generate an image of a dog",
        "create a report on black holes", "draw a picture of a house", "write a story for kids", "make a diagram of my project",
        "write an email to my teacher", "generate a logo", "make a chart of my spending", "compose a song lyric",
        "create a presentation about climate", "write a cover letter",
    ),
    "auto": (
        "open youtube", "open vs code in this folder", "close the browser", "play some music", "pause music", "next song",
        "set the volume to 50", "increase the volume", "make the screen brighter", "turn on bluetooth", "take a screenshot",
        "send hello to telegram", "send this file to telegram", "create a new folder in downloads", "delete this file",
        "find my resume file", "remind me at 5 pm", "set a timer for 10 minutes", "add milk to my to-do list",
        "save this link", "show my link store", "what time is it", "what is the date today", "shut down the laptop",
        "lock the screen", "free ram", "organize this folder", "copy the path of this folder", "switch to the second tab",
        "scroll down", "press enter", "what is open on my screen", "read the text on screen", "show git status",
        "start the job list", "how much battery is left", "what is using my cpu", "open settings", "run this command",
    ),
}
SMALL_TALK_SIM = 0.86  # the whole request this close to a small-talk example = its ready answer (0 tokens)
LEARN = os.getenv("KURAMA_LEARN", "1").lower() not in ("0", "false", "no", "off")  # learn areas from corrections
LEARN_WINDOW_S = 120  # a correction counts within this long after the request it corrects
LEARN_CORRECTION_MARGIN = 0.05  # ...and not closer (by more than this) to a plain next request (learn.NOT_CORRECTIONS)
LEARN_CORRECTION_SIM = 0.80  # similarity to an example correction ("no, I meant...") to count as one
LEARN_WORKED_MAX_CORR = 0.65  # "it worked" is learned only if the next message is not even close to a correction
LEARN_LATE_DAYS = 3  # a complaint after the 2 min window looks for the reply it talks about this far back...
LEARN_LATE_SIM = 0.72  # ...it must be this close in meaning to one of them...
LEARN_LATE_MARGIN = 0.05  # ...and clearly closer than to the next one, else nothing happens
FEEDBACK_MIN_LOGPROB = -0.60  # spoken praise / complaint counts only when speech recognition was this sure
# (garbled lines like 'Okay, go on.' -0.89, 'Maximal Zabolom' -0.68 came out of noise; real speech is ~-0.1..-0.5)
LEARN_PRAISE_SIM = 0.80  # "perfect, that's right" after a reply = a spoken 👍 (learn.praise_score)
LEARN_SILENT = os.getenv("KURAMA_LEARN_SILENT", "0").lower() in ("1", "true", "yes", "on")  # owner 11-03: silence
# teaches nothing; on = the old "an AI request that worked is learned for routing" without any word from the owner
LEARN_VETO_SIM = 0.92  # a corrected wording this similar never runs that shortcut again
LEARN_MAX = 3000  # learned wordings kept (newest)
# Learned shortcuts + kept answers from 👍 / 👎 and uncorrected turns (jarvis/core/recipes.py, data/recipes.json):
# an AI request done with ONE safe tool becomes a 0-token shortcut when the owner approves it (👍 / praise) or teaches it.
RECIPES = os.getenv("KURAMA_RECIPES", "1").lower() not in ("0", "false", "no", "off")
RECIPE_GROUPS = ("apps", "audio", "browser", "display", "desktop", "filesearch", "general", "git", "links", "media",
                 "power", "system", "usage", "weather", "web", "windows", "knowledge")  # reads, opening, controls only
RECIPE_SIM = 0.92  # a shortcut with no slot: this close in meaning, and no new content word
RECIPE_SLOT_SIM = 0.60  # a slot shortcut must fit its wording template ('play song X') and be at least this close
RECIPE_MAX = 400
STYLE_MAX = 6  # the owner's standing reply rules (style.py), kept until changed...
STYLE_MAX_CHARS = 320  # ...added to every AI reply within this (~80 tokens)
STYLE_RULE_MAX_CHARS = 120
STYLE_MIN = 0.80  # closeness to a style example to save it as a rule
STYLE_EXAMPLES = ("from now on keep your answers short", "always reply to me in nepali", "never ask me the same thing twice",
                  "always call me boss", "don't use emojis in your replies", "from now on speak simply, no big words",
                  "always give me the answer first and the details after", "never say sorry so much",
                  "always answer in one line unless I ask for more")
NOT_STYLE_EXAMPLES = ("always open youtube at 9 am", "remind me every day at 7", "never mind", "from now on I am busy",
                      "always lock the screen when I leave", "never download videos in 4k", "play lofi always",
                      "from now on I live in pokhara", "always be here for me", "never stop the music")
RECIPE_MAX_FAILS = 2  # a learned shortcut whose tool failed this many times in a row is switched off
ANSWER_CACHE = os.getenv("KURAMA_ANSWER_CACHE", "1").lower() not in ("0", "false", "no", "off")
ANSWER_CACHE_SIM = 0.95  # a 👍 answer is reused only for a nearly identical question
ANSWER_CACHE_DAYS = 30
# Plain conversation (no tools): a group has to look more like the request than these do.
ROUTER_CHAT_EXAMPLES: tuple[str, ...] = (
    "hi there", "how are you doing", "thank you so much", "good morning", "good night, see you",
    "tell me a joke", "I feel bored", "I am sad today", "motivate me", "give me some advice about life",
    "what should I eat", "write a poem", "tell me a story", "translate this sentence",
    "explain how neural networks learn", "what is machine learning", "difference between a list and a tuple",
    "why is the sky blue", "explain recursion with an example", "what is 2 plus 2", "who invented the telephone",
    "help me understand this concept", "how does attention work in transformers", "what is the capital of japan",
)
# A few natural ways people ask, per group (what keywords can't list). Short and different from each other.
ROUTER_EXAMPLES: dict[str, tuple[str, ...]] = {
    "nepal": ("what is the fee for nepal citizenship", "how do i make a citizenship certificate in nepal",
              "what is the overspeeding rule in nepal", "what is the fine for drunk driving in nepal",
              "what is the marriage registration process in nepal", "how does divorce work in nepal",
              "when was the constitution of nepal made", "which is the largest district of nepal",
              "which is the smallest district of nepal", "how to get a passport in nepal",
              "what documents are needed for a driving license in nepal", "what is the punishment for theft in nepal law",
              "how to register land in nepal", "what is the tax on land sale in nepal", "how many provinces does nepal have",
              "what are the fundamental rights in the nepal constitution", "how to register a company in nepal",
              "what is the legal age of marriage in nepal", "what is the process for a birth certificate in nepal",
              "how to file a case in a nepal court", "what does the nepal labour act say about leave",
              "who appoints the chief justice of nepal", "what is the inheritance law in nepal",
              "explain the citizenship law", "what does the law say about divorce", "tell me about nepal traffic rules",
              "what is the process to get a national id card", "what is the penalty for not wearing a helmet"),
    "tracker": ("spent 500 on food", "how much did I spend this month", "set my food budget to 8000",
                "check in my exercise habit", "show my habit streaks", "add a habit to read 20 pages a day"),
    "system": ("done for today", "start my day", "end my work day", "my laptop feels slow and laggy", "what is eating my memory", "check cpu and ram usage",
               "what is using port 8000", "free up some memory", "my laptop is getting hot",
               "the internet is not working", "websites are not loading", "how fast is my connection",
               "turn wifi off", "is bluetooth on", "airplane mode", "switch to power saver"),
    "audio": ("it is too quiet, I can barely hear", "the sound is way too loud", "make it a little louder",
              "mute my mic"),
    "display": ("the screen hurts my eyes", "make the screen dimmer", "use the dark theme"),
    "desktop": ("change my desktop picture", "silence notifications for a while", "start a study session",
                "warm the screen colors at night"),
    "weather": ("do I need an umbrella today", "how hot is it outside", "forecast for the weekend"),
    "general": ("what day is it", "what time is it in london"),
    "git": ("did my changes get committed", "what branch is this", "commit my work", "show recent commits",
            "what did I change since it was working", "give me my file as it was two hours ago",
            "undo my changes to this file", "where was I", "what was I working on", "resume my project"),
    "dev": ("run the test suite", "start a new python project", "check my python setup and venv",
            "run this command in the terminal", "execute ls -la in my home folder", "run a shell command",
            "what does this error mean", "fix this traceback", "why does my code crash with this exception",
            "I fixed that error by", "check my dataset for problems before training", "is my data balanced",
            # writing code (11-03 after the reset: 'make a python script that renames my photos' went to the
            # file organizer): the code tool writes it
            "make a python script that renames my photos", "write a program that sorts a list", "build me a flask "
            "app with login", "code a snake game in python", "write a bash script to back up my folder",
            "write a script to scrape a website", "create a react app for notes", "make me a website with html and css",
            "write code for a calculator", "program a discord bot in python", "generate a python function that "
            "checks prime numbers"),
    "codequality": ("review my code changes", "scan the repo for leaked passwords", "check my dependencies"),
    "filesearch": ("where is that pdf I downloaded", "find my file named report", "what is inside this folder"),
    "files": ("create a folder", "move this file to documents", "delete this file", "rename the file"),
    "telegram": ("send it to my phone", "message me on telegram", "share this file to my mobile"),
    "schedule": ("remind me later to call mom", "what reminders do I have", "cancel that reminder"),
    "clock": ("set an alarm for the morning", "start a countdown", "start the stopwatch"),
    "clipboard": ("what is on my clipboard", "copy that text", "what did I copy before"),
    "windows": ("move this window to the left half", "maximize the window", "switch to the browser window",
                "click the wifi button in settings", "turn on dark mode in the settings app"),
    "apps": ("install app", "install the app", "uninstall", "update all apps", "update everything", "open the calculator app", "close spotify", "the app froze, kill it"),
    "media": ("pause the music", "next track please", "play my playlist", "summarize this youtube video",
              "what is this video about"),
    "screen": ("capture my screen", "screenshot of this window"),
    "power": ("how much charge is left", "lock the screen", "shut down the computer", "put it to sleep",
              "guard my laptop while I am away", "where is my laptop", "anti theft"),
    "image": ("make an image of a cat in space", "create a picture of mountains", "draw a logo",
              "generate a random image and send it to telegram", "make any picture for me"),
    "web": ("ask gemini what this means", "ask chatgpt to explain this code", "send this to claude", "search online for", "look this up on the internet", "who won the match yesterday",
            "latest news about technology", "tell me when this website changes", "watch the exam results page",
            "let me know when the notice board page updates"),
    "memory": ("remember that my wifi password is", "what did I tell you about", "what did we discuss last time"),
    "knowledge": ("how does my code handle this", "find where my project loads the config", "explain my repo"),
    "usage": ("how many tokens did I use", "give me a summary of today"),
    "jobs": ("write a detailed report in the background", "how is my background job going", "cancel the job",
             "add a job for later: write an essay about Nepal", "show my job list", "start working on my jobs",
             "change job 3 to research black holes"),
    "watch": ("tell me when the training is done", "notify me when this process exits", "watch this log file",
              "how is my model training going", "start training and keep an eye on it", "connect my colab notebook",
              "is the training still running"),
    "daily": ("calculate this for me", "convert dollars to rupees", "how much disk space is used"),
    "devutils": ("turn the notebook into a script", "make requirements.txt from imports", "what changed in my config"),
    "self": ("what can you do", "what are your features", "how do I use you"),
    "toolsmith": ("make a new tool for this", "build a small script tool that does it"),
    "automation": ("download this dataset tonight", "clean up my downloads folder", "back up my projects",
                   "keep my server running"),
    "study": ("note this down for my physics class", "show my DSA notes from this week", "record today's class",
              "transcribe the lecture", "summarize the lecture", "what did the teacher say today",
              "what classes do I have tomorrow", "when is my next class", "test me on what I studied"),
}
# 2026-11-01 router misses (scorecard): areas with no example of these KINDS of wording (romanized Hindi / Nepali,
# short questions, typos). Worded differently from the test cases on purpose.
for _g, _ex in {
    "clock": ("mujhe subah 7 baje jaga dena", "bholi bihana 5 baje uthau", "wake me up at 6 tomorrow"),
    "media": ("gaana chalao", "song bajau na", "koi gaana lagao", "play some songs",
              "how far is the video download", "did the youtube download complete", "show the download progress"),
    "watch": ("is any training running right now", "is my model still training"),
    "tracker": ("I drank 2 liters of water today", "finished 3 litres of water", "done 30 pushups today"),
    "links": ("show my read later list", "what's in my reading list", "remove it from read later",
              "delete that saved link", "remove this link from my links", "forget the link I saved",
              "list every link I have saved", "empty my saved links", "delete the 3rd bookmark",
              "keep the address of the page I'm on under a name", "bookmark this site as my bank",
              "rename one of my saved links", "open a link I bookmarked earlier",
              "keep this youtube video link in my links under a name"),
    "daily": ("what is 12 times 8", "how much is 250 minus 75"),
    # the to-do list had NO examples (it lived on learned wordings; after the 11-03 reset 'what is my todo list'
    # went to the highlighted-text helper): every spelling people type
    "todo": ("what is my todo list", "show my to-do list", "what's on my todo", "list my tasks", "what do I have to do",
             "add buy milk to my todo list", "put call mom on my to do list", "mark the first task done",
             "remove task 2 from my todos", "what tasks are due today", "clear my todo list",
             "mero todo list dekhau", "aaj ke kaam baki hai"),
    "screen": ("read what's on my screen", "what does my screen say"),
    "image": ("make an audio of this text", "turn this paragraph into speech"),
}.items():
    ROUTER_EXAMPLES[_g] = ROUTER_EXAMPLES.get(_g, ()) + _ex
ROUTER_URL_GROUP = "browser"  # group for messages containing a URL/domain
# while the meaning model is not loaded (first request after 10 min idle: 17 of 87 AI requests 10-31..11-01) the word
# rules decide; an area split out of another keeps riding along with it so its tools are still offered
ROUTER_RULE_NEIGHBORS = {"browser": "links"}
# areas that hold the user's own saved things: an answer there with no tool can only come from old replies (traces
# 59989bc5f78f, f8d5f6b7c2d4 listed links that no longer existed / never did), so it is retried with the tools
DATA_AREAS = ("links", "todo", "schedule", "jobs", "tracker")
ROUTER_SITE_OVER_APPS = True  # "open youtube": a known site/URL drops the apps group (browser wins)
FASTPATH = os.getenv("JARVIS_FASTPATH", "1").lower() not in ("0", "false", "no", "off")  # regex intents, 0 tokens
ASSISTANT_NAME = os.getenv("KURAMA_NAME", "KURAMA")  # default name; the user can change it (core/identity.py)
# Owner password for protected self-information (architecture, storage, security). Only a salted hash is kept;
# change it with KURAMA_PASSWORD_HASH=sha256(SELF_PASSWORD_SALT + lowercase password).
SELF_PASSWORD_SALT = "kurama-self-v1:"
SELF_PASSWORD_HASH = os.getenv("KURAMA_PASSWORD_HASH", "")  # .env only (the repo is public); empty = never unlocks
# other spellings of the password that count as it, e.g. how speech-to-text writes it in Devanagari: "दर्शन=darshan"
SELF_PASSWORD_ALIASES = os.getenv("KURAMA_PASSWORD_ALIASES", "")
SELF_UNLOCK_S = 600  # protected answers stay unlocked this long after the right password
SELF_PENDING_S = 180  # how long a "say the password" question waits for the answer
ASSISTANT_NAMES = ("kurama", "kurema", "kuruma", "korama", "curama", "kuramma", "kurmaa", "udama", "kudama", "gurama")  # + how speech-to-text mishears it
HOME_PLACE = os.getenv("JARVIS_HOME_PLACE", "Nepalgunj, Nepal")  # default for weather
HTTP_TIMEOUT_S = 5.0
# Hand-gesture media/YouTube control: the user's module, run in its own venv (OpenCV + MediaPipe stay out of KURAMA).
GESTURE_DIR = Path(os.getenv("KURAMA_GESTURE_DIR", "/media/leo/Project1/Project/Gen_AI/Big_project/02_K.U.R.A.M.A/"
                                                   "Version_4/Extra_tools_file/Youtube_vision_control"))
VISION_PYTHON = os.getenv("KURAMA_VISION_PYTHON", str(ROOT / "data" / "vision_venv" / "bin" / "python"))
IMAGE_TIMEOUT_S = 90  # per image service
# Image services tried in order (GET <url>?prompt=...; returns the picture). The user's Cloudflare workers first,
# then Pollinations (free, no key). Override with JARVIS_IMAGE_APIS="url1;url2".
IMAGE_APIS = tuple(u for u in os.getenv("JARVIS_IMAGE_APIS", ";".join((
    "https://broad-moon-2502.lifejorney1500.workers.dev/",
    "https://image-api.satorugojo0087.workers.dev/",
    "https://image-ai.iamleo0087.workers.dev/",
    "pollinations",
))).split(";") if u.strip())
# Added when the user names no style of their own.
IMAGE_DEFAULT_STYLE = "cinematic vector art, high contrast, bold clean shapes, dramatic lighting, rich colors"
WEATHER_CACHE_S = 600  # weather results are reused for 10 min
UI_WEATHER_PLACES = tuple(os.getenv("JARVIS_UI_WEATHER", "Nepalgunj, Nepal").split(";"))  # UI weather card
GEO_CACHE_S = 86_400  # geocoder results are reused for a day
# --- P5b desktop controls ---
VOLUME_STEP = 10  # "volume up" without a number
VOLUME_MAX = 100  # never above 100% (pactl allows boosting; it distorts)
BRIGHTNESS_STEP = 10
BRIGHTNESS_MIN = 5  # never dim below this: a black screen is hard to undo by voice
SNAP_PANEL_OFFSET = 32  # GNOME top bar height, used when wmctrl reports no usable work area
SCREENSHOT_DIR = Path(os.getenv("JARVIS_SCREENSHOT_DIR", str(Path.home() / "Pictures" / "Screenshots")))
SCREENSHOT_TOOLS = ("scrot", "gnome-screenshot")  # first one found (and working) is used; scrot ~0.1 s, gnome ~0.9 s
CLIPBOARD_READ_MAX = 500  # chars of clipboard text returned to the LLM
CLIPBOARD_HISTORY_MAX = 200  # copy history rows kept (what the user copies + what KURAMA copied)
CLIPBOARD_KEEP_H = float(os.getenv("KURAMA_CLIPBOARD_KEEP_H", "24"))  # copy history: forgotten after this long
CLIPBOARD_MAX_CHARS = 20000  # longer copies (whole files) are not kept
READ_ALOUD_MAX_CHARS = 3000
GREETING = os.getenv("JARVIS_GREETING", "1").lower() not in ("0", "false", "no", "off")
GREETING_WEATHER = True  # include a weather one-liner for HOME_PLACE (network, in a thread)
# Named sets of apps (spoken names, see tools/general/_apps.py) and sites/URLs to open together.
WORKSPACES: dict[str, dict[str, list[str]]] = {
    "coding": {"apps": ["vs code", "terminal"], "urls": ["github"]},
    "study": {"apps": ["text editor"], "urls": ["youtube", "wikipedia"]},
    "research": {"apps": [], "urls": ["google", "wikipedia", "chatgpt"]},
    "writing": {"apps": ["text editor"], "urls": ["claude"]},
}
# Keyword rules: group -> words/phrases (matched on word boundaries, case-insensitive).
ROUTER_RULES: dict[str, tuple[str, ...]] = {
    "tracker": ("spent", "expense", "expenses", "spending", "budget", "kharcha", "खर्च", "income", "salary",
                "habit", "habits", "streak", "streaks", "how much did i spend", "money report"),
    "self": ("yourself", "about you", "your name", "who are you", "what can you do", "what you can do",
             "do you have a tool", "do you have any tool", "can you help", "help me", "i'm stuck", "i am stuck",
             "stuck", "don't know how", "dont know how", "no idea", "guide me", "what should i do", "how do i",
             "how can i", "suggest", "your data", "you store", "you save", "your output", "your memory",
             "your limitation", "your limits", "how do you work", "your architecture", "how are you built",
             "change your name", "call yourself", "your password", "from workspace", "from the workspace",
             "in workspace", "in the workspace", "on the workspace", "workspace ma", "workspace me", "आफ्नो बारेमा", "तिम्रो नाम", "तुम्हारा नाम"),
    "study": ("note for", "study note", "my notes", "notes from", "record the lecture", "record this lecture",
              "record the class", "record this class", "lecture", "transcript", "stop the recording", "stop recording",
              "timetable", "time table", "class schedule", "next class", "my classes", "quiz", "flashcard", "revise"),
    "daily": ("organize", "organise", "messy", "mess", "cluttered", "clutter", "untidy", "sort my files", "in order", "rename my", "arrange my files",
              "convert file", "convert this", "convert it", "to pdf", "to markdown", "to png", "to jpg", "to mp3", "calculate", "calculator", "% of", "percent of", "convert currency", "convert money", " to miles", " to km", "square root",
              "currency", "exchange rate", "dollar", "rupee", "usd", "npr", "inr", "euro",
              "disk space", "free space", "cleanup", "clean up",
              "storage full", "what is using"),
    "image": ("generate image", "generate an image", "image of", "picture of", "photo of", "drawing of",
              "draw ", "illustration", "painting of", "तस्वीर", "चित्र"),
    "general": ("time", "date", "day is it", "clock", "what day", "o'clock", "baje",
                "kitne baje", "kati bajyo", "bajyo", "samay", "समय", "बजे", "बज्यो", "तारीख", "मिति",
                "time in", "time of", "टाइम", "कितने बजे", "कति बजे"),
    "weather": ("weather", "temperature", "forecast", "rain", "raining", "hot", "cold", "humid",
                "mausam", "mosam", "mousam", "मौसम", "मोसम", "वेदर", "barsat", "पानी पर्छ", "बारिश",
                "तापक्रम", "तापमान"),
    "files": ("file", "files", "folder", "folders", "directory", "delete", "remove", "rename", "mkdir",
              "move file", "copy file", "trash", "फाइल", "फोल्डर", "मिटाओ", "मेटाउ"),
    "filesearch": ("secret", "private folder", "nobody should open", "password protect", "locked folder", "find file", "find files", "find the file", "locate", "named", "grep", "ripgrep", "where is",
                   "files in", "list files", "list the files", "what's in", "what is in", "show files",
                   "list folder", "contents of", "inside the folder", "in the folder", "list of", "file in",
                   "list the folder", "show me the files", "folders in",
                   "which file", "containing", "search files", "search for files"),
    "telegram": ("over wifi", "via wifi", "wifi share", "telegram", "to my phone", "on my phone", "send it to my phone", "send me", "send it to me",
                 "and send", "from my laptop", "whole list", "full list", "complete list", "full result",
                 "टेलिग्राम", "फोनमा पठाउ",
                 "फोनमा", "फोन पर भेज", "फ़ोन पर भेज", "phone ma pathau", "phone pe bhej"),
    "toolsmith": ("make a tool", "make tool", "create a tool", "build a tool", "new tool", "skills", "skill",
                  "saved tools", "my tools"),
    "system": ("battery", "cpu", "ram", "system doing", "my system", "system status", "system health",
               "wifi", "wi-fi", "bluetooth", "airplane", "flight mode", "power saver", "battery saver",
               "performance mode", "balanced mode", "screen off", "turn off the screen",
               "resources", "resource usage", "memory usage", "ram usage", "disk", "disk space", "swap",
               "storage", "workers", "computer doing", "laptop doing", "सिस्टम", "रैम", "डिस्क", "मेमोरी"),
    "audio": ("volume", "mute", "unmute", "louder", "quieter", "sound", "speaker", "speakers", "mic",
              "microphone", "audio", "awaz", "awaaz", "awaj", "aawaj", "bolume", "आवाज", "आवाज़", "भोल्युम", "माइक"),
    "desktop": ("wifi password", "wi-fi password", "wifi qr", "share wifi", "share the wifi", "join my wifi",
                "connect to my wifi", "do not disturb", "dnd", "notifications", "notification", "night light", "night-light",
                "blue light", "wallpaper", "wallpapers", "background image", "desktop background",
                "focus mode", "focus session", "focus", "pomodoro", "deep work", "concentrate", "study session", "वालपेपर", "नाइट लाइट",
                "डिस्टर्ब", "फोकस मोड", "सूचना", "नोटिफिकेशन"),
    "display": ("brightness", "brighter", "dimmer", "dim the screen", "screen brightness", "backlight",
                "चमक", "ब्राइटनेस", "light mode", "dark mode", "light theme", "dark theme", "theme",
                "night mode", "day mode"),
    "screen": ("screenshot", "screenshots", "screen shot", "screen capture", "capture the screen",
               "capture screen", "स्क्रीनशॉट"),
    "power": ("battery", "charging", "charge left", "battery health", "बैटरी", "ब्याट्री", "बेट्री",
              "lock", "lock screen", "sleep", "suspend", "shutdown", "shut down", "reboot", "restart",
              "power off", "log out", "logout", "sign out", "लॉक"),
    "clock": ("timer", "alarm", "stopwatch", "stop watch", "wake me", "count down", "countdown", "lap"),
    "clipboard": ("simple english", "plain english", "in simple words", "selected text", "selected", "highlighted", "my writing", "grammar", "rephrase", "rewrite",
                  "spelling", "clipboard", "clip board", "copy", "copied", "paste", "क्लिपबोर्ड"),
    "windows": ("stt", "speech to text", "voice typing", "dictation", "dictate", "type with my voice", "what i speak",
                "click", "tap on", "double click", "press the", "new tab", "close tab", "tab", "tabs", "button",
                "on screen", "on the screen", "in the app", "dark mode in", "toggle", "in settings",
                "window", "windows", "snap", "minimize", "minimise", "maximize", "maximise",
                "left half", "right half", "tile", "restore window", "full screen", "fullscreen",
                "split", "side by side", "half screen", "big screen", "पूरा स्क्रीन", "what's open",
                "what is open", "things open", "currently open", "open right now", "running apps",
                "which apps", "open apps", "are open", "is open", "open on my", "open in my", "खुला", "खुले"),
    "apps": ("force quit", "force close", "not responding", "frozen", "hung", "end process", "terminate",
             "open", "close", "launch", "focus", "app", "application", "workspace", "kill", "browser",
             "terminal"),
    "media": ("download video", "download the video", "1080p", "720p", "mp3", "gesture", "hand control", "hand gesture", "vision control", "control with my hand", "on youtube", "youtube video", "youtube ma", "youtube pe", "youtube par", "यूट्यूब", "युट्युब",
              "next video", "playlists", "play", "pause", "resume", "unpause", "music", "song", "next track", "previous track",
              "next song", "previous song", "skip", "playing", "playlist", "गाना", "गीत"),
    "git": ("git", "commit", "branch", "repo", "repository", "git status", "git log", "diff",
            "staged", "checkout", "changes", "uncommitted", "time machine", "snapshot", "restore the file",
            "as it was", "since it worked", "where was i", "what was i working on", "resume my", "pick up where"),
    "dev": ("traceback", "exception", "this error", "the error", "error mean", "i fixed", "out of memory", "keyerror",
            "valueerror", "typeerror", "indexerror", "attributeerror", "importerror", "nameerror", "runtimeerror",
            "modulenotfounderror", "segmentation fault", "pytest", "run tests", "test suite", "scaffold", "venv", "pip", "tests", "unit tests", "failing tests",
            "doctor", "env doctor", "environment doctor", "environment check", "my environment",
            "dev environment", "python version", "virtualenv", "project", "new project", "fastapi",
            "langgraph", "data science"),
    "codequality": ("go to definition", "find this function", "where is this function defined", "where is this function", "this function", "function", "method", "class", "dependency", "dependencies", "dependency doctor", "dependency check", "outdated",
                    "outdated packages", "unpinned", "vulnerable", "vulnerability", "vulnerabilities", "cve",
                    "pip-audit", "secret scan", "scan for secrets", "secrets", "secret leak", "leaked key",
                    "leaked keys", "api key leak", "pre-commit", "precommit", "pre commit", "commit hook",
                    "lint", "linter", "linting", "ruff", "hygiene", "repo hygiene", "clean up the repo", "code review",
                    "review my code", "review the code", "review code", "review my diff", "review the diff",
                    "review my changes", "review the changes", "review my commit", "review the last commit",
                    "review last commit", "review this file", "review the file", "code quality",
                    "code review karo", "mera code review", "code check karo", "code herdeu", "कोड रिभ्यु",
                    "कोड रिव्यू", "कोड समीक्षा", "कोड जाँच", "कोड जाँच गर", "कोड हेर", "सिक्रेट", "डिपेन्डेन्सी",
                    "निर्भरता", "requirements", "requirements.txt", "requirements file", "check requirements"),
    "devutils": ("notebook", "notebooks", "jupyter", "ipynb", "notebook to script", "notebook to python",
                 "requirements generator", "generate requirements", "create requirements",
                 "config diff", "config changes", "config changed", "config change", "what changed in config",
                 "what changed in my config", "what changed in the config", "changes in config", "changes in my config",
                 "config snapshot", "snapshot config", "snapshot my config", "snapshot the config", "compare config",
                 "config drift", "नोटबुक", "नोटबुकलाई", "कन्फिग", "कॉन्फ़िग", "कॉन्फिग", "config me kya badla", "config ma ke pheriyo",
                 "config ma ke badliyo", "config मा के फेरियो", "config मा के बदलियो", "config में क्या बदला",
                 "कन्फिगमा के फेरियो", "type hint lagao", "docstring lekh", "docstring likho",
                 "results ki table", "benchmark table banao"),
    "web": ("search", "search for", "news", "google", "look up", "lookup", "browse", "website", "wikipedia",
            "wiki", "who is", "who was", "who are", "latest", "headlines", "search the web", "search online",
            "on the internet", "read this page", "read the page", "web page", "webpage", "खोज", "ढूंढ"),
    "memory": ("contact", "contacts", "phone number", "'s number", "remember", "recall", "note", "notes", "last time", "yesterday", "remind",
               "what did i tell you", "forget", "yaad", "याद", "सम्झ", "talk about", "talked about",
               "we discussed", "did we discuss", "our conversation", "about me", "know about me",
               "my profile", "my name", "who am i"),
    "knowledge": ("in my code", "my notes", "search my", "where did i", "how did i", "find in project",
                  "what does my code", "docs", "documentation", "codebase", "code base", "my codebase",
                  "codebase question", "in my project", "in the project", "in this repo", "in the repo",
                  "my repo", "index folder", "index my", "index the", "knowledge", "in the code",
                  "where is the code", "which function", "which module", "this project", "this repo", "this codebase",
                  "project about", "repo about", "what does this repo", "what does this project"),
    "usage": ("token", "tokens", "token usage", "api usage", "api cost", "groq usage", "how much did i spend",
              "cost", "budget", "digest", "daily digest", "daily summary", "summary of my day", "my day",
              "टोकन"),
    "browser": ("url", "link", "website", "web site", "site", "youtube", "gmail", "github",
                "chatgpt", "open google", "www", "http", "https"),
    "watch": ("kaggle", "free gpu", "cloud gpu", "on gpu", "watch", "watches", "watching", "monitor", "keep an eye", "tell me when", "notify me when",
              "alert me", "let me know when", "training run", "training", "log file", "tail the log",
              "finishes", "colab", "command alerts", "long command", "terminal command", "train my model", "train the model", "epoch", "loss curve", "nazar", "नजर", "निगरानी", "हेरिरहनु", "ध्यान राख"),
    "automation": ("automation", "watchdog", "auto restart", "download", "downloads folder", "tidy", "organize my",
                   "backup", "back up",
                   "auto-restart", "keep alive", "keep it running", "if it crashes", "crashed", "crashes",
                   "वर्कफ्लो", "स्वचालन"),
    "jobs": ("job", "jobs", "background", "working on", "progress", "job status", "cancel",
             "stop writing", "essay status", "essay", "article", "story", "report", "write a",
             "लेख", "निबंध"),
    "schedule": ("remind me", "reminder", "reminders", "schedule", "scheduled", "every day at", "every morning",
                 "every weekday", "alarm", "yaad dila", "yaad dilana", "सम्झाइदेउ", "याद दिला",
                 "my exam", "goal", "goals", "long task", "long term", "long-term", "days left", "check-in", "check in",
                 "ask me every day", "ask me daily", "project report", "postponed", "postpone"),
    "todo": ("to-do", "to do list", "todo", "todos", "to-dos", "my tasks", "task list", "tasks", "my task",
             "what's on today", "what do i have to do", "mark as done", "काम", "कार्य"),
}
# Descriptions offered to the fast classifier when no rule matched.
TOOL_GROUP_DESCRIPTIONS: dict[str, str] = {
    "nepal": "Nepal's laws, legal processes, government services and fees, and Nepal general knowledge (citizenship, "
             "passport, marriage, divorce, traffic rules and fines, land, tax, courts, the constitution, provinces and "
             "districts), answered from Nepal's official documents (not live news or prices)",
    "tracker": "money spent/earned, budgets, bills; habit streaks",
    "general": "time and date (any city or country), simple utilities",
    "weather": "current weather and up to 3-day forecast for any place",
    "files": "create folders, write files, move/copy, move to trash",
    "filesearch": "find files by name or by text content; open a folder by name",
    "telegram": "send a file (by path or name) or a message to the user's Telegram (phone); mute alerts",
    "links": "the user's link store (saved links by name: save this page's link, list, open, rename, remove) and read "
             "later list",
    "toolsmith": "no tool fits a real task: offer to build a small new tool; saved tools list/run/delete",
    "skills": "small tools KURAMA built earlier (saved skills)",
    "system": "laptop doctor (why it is slow: RAM, CPU, heat, disk; free RAM, ports, stop a process), internet "
              "doctor (why the internet is slow/down, speed test, reconnect, tell me when it is back) and laptop "
              "switches: Wi-Fi, Bluetooth, airplane, power mode, screen off",
    "watch": "Training Guard: start/watch ML training runs (local or Google Colab), progress, crash, NaN, stuck, "
             "finished alerts; watch any process or log",
    "automation": "crash watchdog for dev servers; download manager (big files now or tonight, resumes); tidy the "
                  "Downloads folder; backups to another drive",
    "audio": "speaker volume, mute, microphone mute",
    "display": "screen brightness, light/dark mode",
    "desktop": "do not disturb, night light, wallpaper, focus (pomodoro) session",
    "screen": "take a screenshot (full screen, window or area)",
    "power": "battery status, lock the screen, sleep/suspend, shut down, restart, log out; laptop guard (anti-theft "
             "photo + location) and where the laptop is",
    "clock": "timers, alarms (with sound) and a stopwatch",
    "clipboard": "read or write the clipboard, clipboard history",
    "windows": "snap, maximize, minimize, restore or list windows; control the app on screen (tabs, keys, typing, clicking buttons, free-form tasks inside apps)",
    "apps": "open, close, focus, force-kill, install/uninstall/update apps; launch a named workspace of apps and sites",
    "media": "music and video playback (play, pause, next, previous, what's playing), YouTube, playlists, hand-gesture media control (camera)",
    "git": "git status, log, diff, commit and branches; code time machine (automatic snapshots: what changed since "
           "a time, restore a file); where was I (resume a project)",
    "dev": "tests, new projects, Python environment check and installing a missing module into the right venv, "
           "explain an error/traceback and remember the fix, "
           "check a dataset (CSV/images) before training",
    "codequality": "dependency doctor (unpinned/outdated/vulnerable/unused), secrets scan, pre-commit gate, "
                   "repo hygiene, AI code review of a diff/file/commit, go to a function's definition",
    "devutils": "notebook (.ipynb) to .py script, generate requirements.txt from imports, config file snapshots/diff",
    "web": "search the web (DuckDuckGo/SearXNG) incl. latest news, Wikipedia summaries, read a web page, watch a "
           "page and say when it changes",
    "memory": "notes the user dictates, facts about the user (profile), past conversations/sessions",
    "knowledge": "search or ask questions about the user's own code, docs and notes (RAG); index a folder",
    "usage": "LLM token usage, budget and API cost; daily digest of the day's activity",
    "browser": "open a website or URL in the browser",
    "jobs": "long writing jobs (essays, articles, reports) and background job status/cancel/resume",
    "todo": "the to-do list: tasks to do with due date, priority, tag (add, list, today, done, delete, edit); no alarm",
    "schedule": "reminders and scheduled commands at a time or repeating; list or cancel them; long goals (exam "
                "countdown, project check-ins, progress, report)",
    "image": "make pictures, charts from data, diagrams, audio (MP3) and short videos",
    "study": "study notes by subject, lecture recorder (record a class, transcript, summary), class timetable "
             "(today, tomorrow, next class, reminders), quiz from my notes with spaced repetition",
    "daily": "file format conversion (pdf, md, images, audio/video, tables), calculator, unit and currency conversion, disk space cleaner (ML caches, old checkpoints, old venvs, "
             "duplicates, trash)",
    "self": "about the assistant itself (abilities, outputs/data locations, limits, how it works), which tool "
            "fits a task, guidance when the user is stuck, change the assistant's name, read the workspace",
}
# Tiny glosses for the request_tools meta-tool (sent on every unmatched turn, so each word costs):
# "" = the group name says it all.
TOOL_GROUP_GLOSS: dict[str, str] = {
    "tracker": "money",
    "general": "time", "weather": "", "files": "folders", "filesearch": "",
    "telegram": "phone", "toolsmith": "", "skills": "", "system": "wifi",
    "watch": "training", "automation": "backup", "audio": "volume", "display": "brightness",
    "screen": "screenshot", "power": "battery", "clipboard": "", "windows": "",
    "apps": "", "media": "music", "desktop": "wallpaper", "git": "", "dev": "tests", "codequality": "review",
    "devutils": "notebooks", "study": "lectures",
    "web": "search", "memory": "notes", "nepal": "",
    "knowledge": "code", "usage": "tokens", "browser": "", "links": "",
    "jobs": "writing",
    "schedule": "remind",
    "todo": "",
    "clock": "",
    "image": "",
    "daily": "math",
    "self": "",
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
                   "brightnessctl", "upower", "gsettings", "loginctl", "notify-send",
                   "n8n", "uvicorn",  # P6: dev servers the crash watchdog may keep alive
                   "ruff", "pip-audit")  # P8a: optional linters for the codequality tools

# --- Background core (P6): python -m jarvis.workers ---
WORKERS_ENABLED: tuple[str, ...] = tuple(
    w.strip() for w in os.getenv("JARVIS_WORKERS", "process_watch,resource_guard,crash_watchdog,"
                                 "telegram_bot,daily_digest,brief,scheduler,timemachine,guard,"
                                 "location_tracker,clipboard_watch").split(",") if w.strip())
# run them inside the server process (one Python instead of two, ~55 MB less); 0 = the separate supervisor process
WORKERS_IN_SERVER = os.getenv("JARVIS_WORKERS_IN_SERVER", "1").lower() not in ("0", "false", "no", "off")
WORKER_MIN_INTERVAL_S = 5.0  # no daemon polls faster than this
WORKER_MAX_BACKOFF_S = 300.0  # error backoff cap (interval * 2^errors)
WORKER_LOG_BYTES = 1_000_000  # rotating log per worker: ~1 MB x 3
WORKER_LOG_BACKUPS = 3
WORKERS_STATUS_PATH = DATA_DIR / "workers.json"  # PID + per-worker state, read by tools
# notify(): desktop + Telegram + SQLite alerts (spoken by the idle voice loop)
NOTIFY_DESKTOP = os.getenv("JARVIS_NOTIFY_DESKTOP", "1").lower() not in ("0", "false", "no", "off")
NOTIFY_DEDUPE_S = 60.0  # identical (title, text) within this window is sent once
NOTIFY_TELEGRAM_PER_MIN = 20  # Telegram rate limit (Bot API allows ~30/s; we stay polite)
# What reaches the phone on its own: every warning/error, plus info only from these sources (your reminders, the
# process/log watches you set, the daily digest). Everything else stays on the laptop (desktop + UI);
# things asked FROM Telegram are always answered there.
TELEGRAM_ALL = os.getenv("KURAMA_TELEGRAM_ALL", "1").lower() not in ("0", "false", "no", "off")  # every alert to the phone too
TELEGRAM_INFO_SOURCES = tuple(os.getenv("KURAMA_TELEGRAM_INFO", "scheduler,process_watch,daily_digest").split(","))
ALERT_ANNOUNCE_MAX_AGE_S = 3600.0  # older unannounced alerts are not spoken
ALERT_ANNOUNCE_CHECK_S = 5.0  # the voice loop looks for new alerts at most this often
ALERT_SPOKEN_LEVELS = ("info", "warning", "error")  # levels the idle voice loop speaks
# Process / training-run watcher
PROCESS_WATCH_INTERVAL_S = 5.0
LOG_WATCH_ERROR_PATTERN = (r"Traceback|Error|(?i:nan loss|loss[ :=]+nan)|CUDA|Killed|OOM|"
                           r"(?i:out of memory)")
LOG_WATCH_EPOCH_PATTERN = r"(?i)\bepoch\b\s*[:=#]?\s*(\d+)"
LOG_WATCH_DONE_PATTERN = r"(?i)\b(done|finished|completed)\b"
LOG_WATCH_ALERT_COOLDOWN_S = 60.0  # one error alert per watch per minute (matches are summarized)
LOG_WATCH_READ_MAX = 256_000  # bytes read per tick per log
LOG_WATCH_TAIL_LINES = 8  # last lines included in alerts / list_watches
# Training Guard (jarvis/core/training.py)
TRAINING_KEEP_AWAKE = True  # block suspend while a local run is watched (systemd-inhibit)
TRAINING_STALL_MIN = 20  # no new output for this long while the process runs = "may be stuck" (0 = off)
TRAINING_BATTERY_WARN = 25  # % on battery during a run: tell the user to plug in
TRAINING_EXPLAIN = True  # a crash gets one short LLM line (cause + fix), cached per error
CMD_ALERTS = True  # report long terminal commands (needs the bash hook: "turn on command alerts")
CMD_ALERT_MIN = 2.0  # minutes: shorter commands are not reported
CMD_ALERT_PHONE = os.getenv("KURAMA_CMD_ALERT_PHONE", "away")  # Telegram too: always | away (screen locked) | never
TIMEMACHINE = True  # snapshot changed projects into private shadow git repos (data/timemachine)
TIMEMACHINE_EVERY_S = 600  # how often the timemachine worker looks for changed projects
TIMEMACHINE_MAX_MB = 1  # bigger files are never stored (only code and text are kept anyway)
WHERE_WAS_I_LLM = True  # "where was I?" turns the facts into 2-3 plain sentences (~400 tokens)
DOCTOR_RAM_WARN = 85  # % RAM used = a finding
DOCTOR_TEMP_WARN = 90  # °C CPU = a finding
DOCTOR_KERNEL_IDLE_MIN = 30  # a Jupyter kernel this old with ~0% CPU counts as idle
GUARD_INTERVAL_S = 5.0  # laptop guard checks (only while armed)
PHONE_INBOX = os.getenv("KURAMA_PHONE_INBOX", "~/Downloads/Phone")  # files sent from the phone land here
WEBWATCH_EVERY_MIN = 60  # website watcher: default check interval
WEBWATCH_MIN_EVERY_MIN = 10  # never more often (be polite to the site)
WEBWATCH_FAIL_ALERT = 5  # say so when a watched page fails this many times in a row
CHECKPOINT_AGE_DAYS = 30  # disk cleaner: older checkpoints (not the newest in a folder) can go
VENV_AGE_DAYS = 90  # disk cleaner: venvs of projects untouched this long
NOTES_DIR = os.getenv("KURAMA_NOTES_DIR", "~/Notes")  # study notes and lecture transcripts
NOTES_CLASSIFY = True  # a note without a subject: one tiny call picks one of your subjects (~120 tokens)
LECTURE_MAX_MIN = 180  # a recording stops by itself after this long
LECTURE_LANG = os.getenv("KURAMA_LECTURE_LANG", "")  # "" = auto; "en", "ne" or "hi" to force Whisper
TIMETABLE_LEAD_MIN = 10  # heads-up this long before each class
DOWNLOAD_DIR = "~/Downloads"  # download manager default folder
DOWNLOAD_NIGHT_HOUR = 1  # "tonight" downloads start at this hour
WIFI_SHARE_IDLE_MIN = 30  # a Wi-Fi share link stops after this many idle minutes
NUDGE_PER_DAY = int(os.getenv("KURAMA_NUDGE_PER_DAY", "2"))  # random 'still want to do this?' for undated list items
NUDGE_HOURS = (10, 21)  # only between these hours
TASK_OVERDUE_S = float(os.getenv("KURAMA_TASK_OVERDUE_S", str(60 * 60)))  # due to-do still open this long after -> 'not done yet'
SELECTION_MEMORY_S = float(os.getenv("KURAMA_SELECTION_MEMORY_S", "600"))  # a highlight outside KURAMA counts this long
# the "KURAMA editor link" VS Code extension (vscode_ext/) keeps one small JSON per window here: open file, selection
CODE_REUSE_MAX_AGE_S = 1800  # "put it in the file" reuses a code job only this recent
VSCODE_STATE_DIR = Path(os.getenv("KURAMA_VSCODE_STATE_DIR", str(Path.home() / ".local" / "share" / "kurama" / "vscode")))
READ_LATER_FILE = os.getenv("KURAMA_READ_LATER", "~/Documents/KURAMA/read_later.xlsx")  # reading list (Excel)
PAGE_DETAIL_TTL_S = 180.0  # "Want a detailed overview?" waits this long for yes
LINKS_FILE = os.getenv("KURAMA_LINKS", "~/Documents/KURAMA/links.xlsx")  # named saved links (Excel)
LINK_NAME_TTL_S = 300.0  # 'what should I call this link?' waits this long for the name
GOALS_FILE = os.getenv("KURAMA_GOALS", "~/Documents/KURAMA/goals.xlsx")  # long goals (tabs Goals + Log)
GOALS_DIR = os.getenv("KURAMA_GOALS_DIR", "~/Documents/KURAMA/goals")  # one folder per project goal (log, daily, report)
GOAL_HOURS = (5, 22)  # goal messages only from 05:00 to 22:00 (owner's KURAMA working hours)
GOAL_LATE_S = 3600.0  # a goal message missed by more than this (laptop off) is skipped
GOAL_ASK_AGAIN_S = float(os.getenv("KURAMA_GOAL_ASK_AGAIN_S", "3600"))  # no answer this long -> asked once more
GOAL_ANSWER_S = 3 * 3600.0  # a plain 'today I did X' within this time after a check-in = its answer
GOAL_WEEKLY_AT = "21:30"  # Sunday: the weekly summary of each project goal
CONTACTS_FILE = os.getenv("KURAMA_CONTACTS", "~/Documents/KURAMA/contacts.xlsx")  # name/phone sheet (Excel)
EXPENSES_FILE = os.getenv("KURAMA_EXPENSES", "~/Documents/KURAMA/expenses.xlsx")  # money: Money / Budgets / Bills tabs
HABITS_FILE = os.getenv("KURAMA_HABITS", "~/Documents/KURAMA/habits.xlsx")  # habits: Habits / Log tabs
CURRENCY = os.getenv("KURAMA_CURRENCY", "Rs")
BRIEF = os.getenv("KURAMA_BRIEF", "1").lower() not in ("0", "false", "no", "off")  # morning brief on first use of the day
BRIEF_FROM_HOUR = 4  # an unlock before 04:00 is still 'last night'
BRIEF_INTERVAL_S = 15.0  # the brief worker's poll (only loginctl while today's brief is still due)
DICTATION_PAUSE_MS = 900  # a pause this long ends a dictated phrase (then it is typed)
DICTATION_DEVANAGARI_LANG = os.getenv("JARVIS_DICTATION_DEVANAGARI", "ne")  # auto mode: Nepali/Hindi speech -> this
DICTATION_IDLE_S = 180  # dictation stops after 3 min of silence
DICTATION_MAX_S = 3600  # ...or after 1 hour in total
ASSIST_MORE_TTL_S = 180.0  # "Want me to write the longer explanation?" waits this long for yes
ASSIST_PENDING_TTL_S = 300.0  # an improved code waits this long for 'yes' (then counts as no)
ORGANIZE_PLAN_TTL_S = float(os.getenv("KURAMA_PLAN_TTL_S", "120"))  # a waiting plan expires (= no)
ORGANIZE_MAX_FILES = 80  # files looked at per organize run (newest first)
ORGANIZE_MAX_IMAGES = 8  # pictures captioned by the vision model per run (~600 tokens each)
VIDEO_DIR = os.getenv("KURAMA_VIDEO_DIR", "~/Videos/KURAMA")  # video/audio downloads (yt-dlp)
BROWSER_TAB_TTL_S = 6 * 3600  # the browser extension's "open tab" counts this long (a closed browser says so itself)
CONTEXT = os.getenv("KURAMA_CONTEXT", "1").lower() not in ("0", "false", "no", "off")  # tell the AI what is open (VS Code file + selection, browser tab)
CODE_FILE_MAX_TOKENS = 4000  # one generated code file (a module with logging/tests fits)
EC_LINGER_S = 30  # the echo canceller stays this long after the mic is released (no flapping between turns)
VIDEO_COOKIES_BROWSER = os.getenv("KURAMA_COOKIES_BROWSER", "brave")  # YouTube "not a bot" check: retry once with this browser's cookies (read locally by yt-dlp; "" = never)
VIDEO_CONNECTIONS = 6  # parallel connections per video download (YouTube throttles each one)
VIDEO_DEFAULT_HEIGHT = 1080  # "download this video" and "best quality" = 1080p; "extra high" / "max" = the highest there is
BACKUP_EVERY_DAYS = 7  # automatic backup interval (also runs when the backup drive appears)
COLAB_POLL_S = 60.0  # how often KURAMA checks for Colab pings (only while a Colab run is active)
COLAB_FILES_DIR = "~/Downloads/Colab"  # checkpoints sent from Colab land in <this>/<run>/
COLAB_SILENT_MIN = 25  # no ping for this long = the Colab runtime probably disconnected
NOTEBOOK_COPY_DIR = Path.home() / "Downloads"  # the ready training notebook is also put here (easy to upload)
COLAB_PROGRESS_EVERY_S = 60  # the notebook sends within-epoch progress at most this often (epoch ends are forced)
# Crash watchdog: targets come ONLY from here plus data/watchdog_targets.json (add_watchdog_target,
# confirm-level, allowlist-checked). Example: {"name": "n8n", "command": "n8n start", "cwd": "~",
# "match": "n8n"}  ("match" = adopt an already-running process whose command line contains it).
WATCHDOG_TARGETS: list[dict[str, str]] = []
WATCHDOG_TARGETS_FILE = DATA_DIR / "watchdog_targets.json"
WATCHDOG_INTERVAL_S = 10.0
WATCHDOG_BACKOFF_BASE_S = 5.0  # restart delay 5, 10, 20, ... s
WATCHDOG_BACKOFF_MAX_S = 600.0
WATCHDOG_MAX_RESTARTS_PER_HOUR = 5
WATCHDOG_STABLE_S = 600.0  # running this long resets the backoff
# Resource guard (thresholds in percent unless noted)
RESOURCE_GUARD_INTERVAL_S = 15.0
RAM_ALERT_PCT = 90.0
SWAP_ALERT_PCT = 80.0
CPU_ALERT_PCT = 90.0  # 5-minute average
DISK_ALERT_PCT = 90.0  # "/" and the home filesystem
JARVIS_CORE_MAX_MB = 600.0  # CLAUDE.md caps
JARVIS_TOTAL_MAX_MB = 1500.0
RESOURCE_HYSTERESIS_PCT = 5.0  # must fall this far below a threshold to count as recovered
RESOURCE_REALERT_S = 1800.0  # still high: alert again after 30 min
RESOURCE_COOLDOWN_S = 2 * 3600.0  # after an alert, the SAME metric stays quiet this long even if it dips and comes back
RESOURCE_TRIM_AT = 0.75  # KURAMA core above this share of JARVIS_CORE_MAX_MB -> gc + malloc_trim (no process stopped)
RESOURCE_TRIM_EVERY_S = 300.0
FREE_RAM_MIN_MB = 150.0  # "free RAM": windowless idle apps at least this big are offered for closing (asks first)
# Alert mute ("don't send RAM warnings for 20 minutes"): word -> notify sources. 'all' never mutes reminders,
# timers or the anti-theft guard (things the user set up on purpose).
MUTE_KINDS: dict[str, tuple[str, ...]] = {
    "resource": ("resource_guard",), "location": ("location",), "jobs": ("jobs",), "downloads": ("downloads",),
    "watchdog": ("watchdog",), "web": ("webwatch",), "commands": ("cmdalerts", "process_watch"),
    "digest": ("daily_digest",), "backup": ("backup",), "kaggle": ("kaggle",), "internet": ("netdoctor",),
    "guard": ("guard",), "reminders": ("scheduler", "timer"), "todo": ("todo",), "goals": ("goals",),
    "money": ("money",), "habits": ("habits",), "brief": ("brief",)}
MUTE_ALL_KEEPS = ("scheduler", "timer", "guard", "goals")
MUTE_DEFAULT_MIN = 30.0  # 'mute alerts' without a time (owner: never mute for life)
MUTE_MAX_MIN = 24 * 60.0  # no mute lasts longer than a day
# Telegram remote control (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID from .env; skipped when empty)
TELEGRAM_PHOTO_KEEP_KB = 500  # photos bigger than this are resized to TELEGRAM_PHOTO_PX JPEG before the upload
TELEGRAM_PHOTO_TARGET_KB = 450  # a photo is re-saved at lower JPEG quality until it is about this small
TELEGRAM_PHOTO_PX = 1920  # a screenshot at full laptop width stays readable (1280 px q55 was blurry text); the
#                           real uplink to Telegram is 230-380 KB/s (11-06): ~450 KB = ~1.5 s. The old "slow uplink"
#                           was IPv6 connections hanging (TELEGRAM_IPV4), not the bandwidth
TELEGRAM_PHOTO_QUALITY = 85  # JPEG quality for screenshots / photos to the phone (lower only if still too big)
TELEGRAM_IPV4 = True  # talk to Telegram over IPv4 only (IPv6 to api.telegram.org hangs here 1 time in 4)
TELEGRAM_POLL_TIMEOUT_S = 6  # long-poll seconds (short so Ctrl+C stops the workers quickly)
TELEGRAM_CONFIRM_TIMEOUT_S = 60.0  # "Reply yes/no": no answer in time means no
TELEGRAM_ANSWER_TIMEOUT_S = 90.0  # a reply that takes longer than this is given up on (no "typing" forever)
TELEGRAM_MAX_REPLY_CHARS = 3500
# alerts that must ring on the phone: sent to the private chat (its own sound) even when sections (group topics) are
# on; the topic gets a silent copy. Warnings and errors always ring.
RING_SOURCES = frozenset({"claude_code", "scheduler", "timer", "todo", "guard", "jobs", "downloads", "kaggle",
                          "webwatch", "cmdalerts", "power", "backup", "brief"})
TELEGRAM_MAX_PARTS = 4  # a longer answer: its first 2 messages + the whole of it as a web page file
TELEGRAM_FOLD_CHARS = 700  # a longer reply shows its start; the rest folds behind "show more"
# --- Telegram security: a PIN for risky actions, and a /lock switch (PINs live in .env, change anytime) ---
TELEGRAM_RISKY_PIN = os.getenv("TELEGRAM_RISKY_PIN", "1500")  # needed to run risky actions from Telegram
TELEGRAM_LOCK_PIN = os.getenv("TELEGRAM_LOCK_PIN", "0087")    # /unlock <this> clears a /lock
REMOTE_PW_TTL_MIN = float(os.getenv("REMOTE_PW_TTL_MIN", "15"))  # RustDesk password stops working after this
UI_TIER = "fast"  # screen agent (free-form app control) LLM tier
UI_MAX_STEPS = 8  # a free-form screen task stops after this many steps
UI_MAX_ITEMS = 70  # on-screen items sent to the LLM per step (token cap)
REMOTE_HELPER = "/usr/local/sbin/kurama-rustdesk"  # root-owned helper (scripts/kurama-rustdesk.sh), run via sudo -n
TELEGRAM_PIN_WINDOW_S = float(os.getenv("TELEGRAM_PIN_WINDOW_S", "1800"))  # risky PIN is remembered this long (30 min)

# --- Multitasking (P3b-2): planner, background jobs, rate limiter ---
APP_VERIFY = True  # open_app checks a window really appeared (else tries another way, remembers what works)
PLANNER_MAX_TASKS = 15  # more are said back as not done (planner.Plan.dropped), never dropped in silence
# While KURAMA's music plays, a short request that MEANS one of these controls the player (fastpath.player_intent)
PLAYER_CONTROL_EXAMPLES = {
    "pause": ("pause", "pause music", "pause the song", "hold on stop for a second", "wait pause it"),
    "resume": ("continue", "continue playing", "continue play", "resume", "resume the music", "play again", "unpause",
               "continue music", "start it again"),
    "next": ("next", "next song", "skip", "skip this song", "play the next one", "change the song"),
    "previous": ("previous song", "play the previous one", "go back to the last song", "back one song"),
    "stop": ("stop music", "stop the song", "stop playing", "turn off the music", "music off"),
    "volume_up": ("louder", "volume up", "increase the volume", "turn it up", "more volume"),
    "volume_down": ("quieter", "volume down", "lower the volume", "turn it down", "less volume"),
    "volume_max": ("volume max", "full volume", "set the volume maximum", "maximum volume", "loudest"),
    "volume_low": ("volume very low", "minimum volume", "lowest volume"),
}
PLAYER_NOT_EXAMPLES = ("continue the code", "continue writing", "open youtube", "what time is it", "explain this",
                       "next tab", "close it", "stop the timer", "pause the download", "continue the essay",
                       "translate it", "next slide", "go back to the previous folder", "play a video on youtube")
PLAYER_CONTROL_MIN = 0.86
PLAYER_CONTROL_MAX_WORDS = 5
TASK_GRAPH = True  # Phase 2: planned requests run as a task graph (steps with real inputs/outputs); False = old chains
TASK_REPLAN = True  # a failed step gets one corrected try (one small fast-tier call)
TASK_REPLAN_MAX_TOKENS = 150
TASK_PLANS_KEEP = 60  # learned plans kept (data/learned_plans.json)
TASK_PLAN_MATCH = 0.93
# a part of a multi-task request that asks for nothing ("let's work .. create a folder X"): no step (by meaning)
FILLER_EXAMPLES = ("let's work", "let's start", "let's do this", "ok so", "so", "now then", "alright let's go",
                   "come on", "listen", "okay now", "bro", "ok bro", "yaar", "let's begin", "right", "well then")
NOT_FILLER_EXAMPLES = ("tell me a joke", "what is the capital of nepal", "open youtube", "create a folder",
                       "play some music", "send it to telegram", "what time is it", "how are you", "write a poem",
                       "work on my essay", "start the timer", "show my jobs")
FILLER_MIN = 0.86  # a request this close in meaning to a learned plan reuses it (0 tokens)
PLANNER_MAX_TOKENS = 1200  # gpt-oss thinks first: at 300 a 10-part plan came back with 6 parts (11-04)
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
MODEL_LIMITS: dict[str, dict[str, int]] = {LLM_GEMINI: {"tpm": 200_000, "rpm": 9},  # Gemini free tier (per minute)
                                           LLM_GEMINI_LITE: {"tpm": 200_000, "rpm": 14}}
RATE_BACKGROUND_RESERVE = 0.3  # share of TPM/RPM background jobs must leave free for interactive
RATE_INTERACTIVE_MAX_WAIT_S = 3.0  # interactive calls wait at most this long, then go anyway


# --- Memory / RAG (P7) ---
# Embeddings: fastembed + ONNX Runtime (no torch). bge-small-en-v1.5 = 67 MB, 384-d, English/code.
# For Nepali/Hindi notes use "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
# (220 MB, 384-d, 50+ languages incl. hi/ne). Changing the model re-embeds the whole index.
EMBED_MODEL = os.getenv("JARVIS_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_CACHE_DIR = DATA_DIR / "models"
WORDNET_DB = DATA_DIR / "wordnet" / "wn.db"  # offline dictionary (an asset, like the models)
EMBED_THREADS = 2  # ONNX intra-op threads (leave cores for VS Code / Chrome)
EMBED_BATCH = 8  # measured on the repo: batch 8 peaks at ~475 MB vs ~680 MB for 16, and is faster on CPU
EMBED_NICE = 10  # the embedding process and the index job thread run at low CPU priority
EMBED_IN_SUBPROCESS = True  # model in a child process: unloading frees ALL its RAM (incl. imports)
EMBED_IDLE_UNLOAD_S = 120.0  # stop the embedding process after this idle time
SEMANTIC_MODE = os.getenv("KURAMA_SEMANTIC_MODE", "auto")  # always | auto | off (changeable in Settings -> Memory)
SEMANTIC_AUTO_IDLE_S = float(os.getenv("KURAMA_SEMANTIC_IDLE_S", "600"))  # auto: freed after 10 min unused
MEMORY_DB_PATH = DATA_DIR / "memory.db"  # chunks + FTS5 + float32 vectors (separate from jarvis.db)
MEMORY_ROOTS: list[Path] = [ROOT] + ([Path.home() / "notes"] if (Path.home() / "notes").is_dir() else [])
MEMORY_EXTS = (".py", ".md", ".txt", ".toml", ".yaml", ".yml", ".json", ".ipynb", ".js", ".jsx", ".ts",
               ".tsx", ".sh", ".bash", ".rst")
MEMORY_EXCLUDE_DIRS = ("data", "venv", ".venv", "env", "node_modules", "__pycache__", "site-packages",
                       "dist", "build", "target", "outputs", "checkpoints", "wandb", "mlruns")
MEMORY_EXCLUDE_FILES = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock")
MEMORY_MAX_FILE_BYTES = 1_000_000
CHUNK_CHARS = 800
CHUNK_OVERLAP = 150  # chars of the previous chunk repeated at the start of the next (non-boundary splits)
RRF_K = 60  # reciprocal rank fusion constant (BM25 rank + vector rank)
SEARCH_CANDIDATES = 40  # per retriever before fusion
KNOWLEDGE_K = 5
KNOWLEDGE_MAX_CHARS = 800  # search_knowledge output cap
KNOWLEDGE_SNIPPET_CHARS = 200
ASK_K = 4
ASK_CONTEXT_CHARS = 1500  # context sent to the fast tier by ask_knowledge
ASK_MAX_TOKENS = 400
OVERVIEW_DOCS = ("README.md", "CLAUDE.md", "PROGRESS.md")  # P7b: "what is this project about" context
ASK_CACHE = True  # normalized question -> answer, cleared whenever the index changes
# Sessions + tiered memory
SESSION_IDLE_S = 4 * 3600.0  # a turn after this much silence starts a new session (fresh context)
SESSION_RECALL_MAX_CHARS = 800
PROFILE_MAX = 50  # facts kept; the least used/oldest are pruned (name/home city are protected)
PROFILE_LLM_EXTRACT = True  # one fast-tier call per session END (never per turn) to extract facts
PROFILE_EXTRACT_MAX_TOKENS = 150
PROFILE_INJECT_MAX = 3  # facts injected into the system prompt on personal turns only
PROFILE_INJECT_MAX_CHARS = 240  # ~60 tokens
PROFILE_DECAY_DAYS = 30.0  # recency half-life-ish for fact ranking
# Usage / cost
FASTPATH_TOKENS_SAVED_EST = 300  # avg prompt+completion tokens an LLM round would have cost
# Optional paid-tier prices in USD per 1M tokens, e.g. {"openai/gpt-oss-20b": {"in": 0.1, "out": 0.5},
# "whisper-large-v3-turbo": {"audio_hour": 0.04}}. Empty = we do not guess.
MODEL_PRICES: dict[str, dict[str, float]] = {}
# Daily digest (worker daily_digest + tool daily_digest)
DIGEST_TIME = os.getenv("JARVIS_DIGEST_TIME", "22:00")  # owner: the day summary at 10 PM
DIGEST_USE_LLM = False  # True: one fast-tier call to polish the template
DIGEST_INTERVAL_S = 60.0


# --- P7b freedom + web ---
SEARXNG_URL = os.getenv("SEARXNG_URL", "").rstrip("/")  # e.g. http://localhost:8888 (JSON format enabled)
WEB_TIMEOUT_S = 6.0
WEB_CACHE_S = 600  # search / wikipedia results reused for 10 min
WEB_SEARCH_MAX_CHARS = 800
WEB_PAGE_MAX_BYTES = 2_000_000  # read_webpage stops downloading past this
WEB_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) KURAMA/1.0 (personal assistant)"
META_TOOLS = os.getenv("JARVIS_META_TOOLS", "1").lower() not in ("0", "false", "no", "off")  # request_tools
META_REFUSAL_RETRY = True  # a tool-less "I can't" answer is retried once with request_tools bound

# --- P7c toolsmith, file tools, Telegram sharing ---
SANDBOX_DIR = DATA_DIR / "sandbox"  # one throwaway folder per generated-tool run
SKILLS_DIR = DATA_DIR / "skills"  # saved reusable generated tools: <name>.py + <name>.json
SKILLS_MAX = 20  # LRU: the least recently used skill is deleted past this
TOOLSMITH_TIER = "fast"  # code generation tier (smart tier is the fallback)
TOOLSMITH_MAX_TOKENS = 1200
SANDBOX_TIMEOUT_S = 15.0  # wall clock
SANDBOX_CPU_S = 10  # RLIMIT_CPU
SANDBOX_MEM_MB = 256  # RLIMIT_AS
SANDBOX_NOFILE = 64
SANDBOX_STDOUT_MAX = 4096
SANDBOX_IMPORTS = ("math", "statistics", "datetime", "json", "re", "random", "string", "collections",
                   "itertools", "functools", "decimal", "fractions", "textwrap", "calendar", "zoneinfo",
                   "urllib.parse", "csv", "hashlib", "uuid", "base64", "difflib", "unicodedata", "secrets")
# SHELL_ALLOWLIST binaries a generated tool may still NOT run (interpreters, installers, git, servers).
TOOLSMITH_CMD_DENY = ("python3", "pip", "pytest", "git", "uvicorn", "n8n", "xdotool", "find", "ruff", "pip-audit")
# File tools: writes under these roots are "safe"; anywhere else asks first.
FILE_SAFE_ROOTS = tuple(Path(p).expanduser() for p in os.getenv(
    "JARVIS_FILE_ROOTS", "~/projects:/media/leo/Project1").split(":") if p)
# --- smart paths ---
# Where loose names are looked up ("tara folder") and spoken aliases ("project1" -> the project drive).
SEARCH_ROOTS = ("/media/leo/Project1", "~")
PATH_ALIASES = {
    "project1": "/media/leo/Project1", "projectone": "/media/leo/Project1", "projectdrive": "/media/leo/Project1",
    "home": "~", "downloads": "~/Downloads", "download": "~/Downloads", "desktop": "~/Desktop",
    "documents": "~/Documents", "pictures": "~/Pictures", "music": "~/Music", "videos": "~/Videos",
    "kurama": "/media/leo/Project1/New_project/KURAMA", "jarvis": "/media/leo/Project1/New_project/KURAMA",
}
FOCUS_TTL_H = 12.0  # the current folder (focus) is remembered this long
WORKMEM_PROMPT_AGE_S = 3600  # things made/touched this recently are listed in the AI's prompt (workmem.line)
WORKMEM_FRESH_S = 120  # a thing made/touched this recently is "it" even over the open Files folder
DID_TURNS = 2  # the last 2 replies in the AI's history keep their '[tools this turn: ...]' line
QUESTION_TTL_S = 600  # a question/offer KURAMA made this recently is what a short reply ('yes', 'the second') answers
PATH_MATCH_MIN = 0.72
SHARE_ROOTS = (Path.home(), Path("/media/leo/Project1"))  # send_file_telegram only sends files under these
TELEGRAM_FILE_MAX_MB = 50

# --- P9a --- desktop extras (DND, night light, wallpaper, auto theme, focus, YouTube, playlists)
WALLPAPER_DIRS = tuple(p for p in (Path.home() / "Pictures" / "Wallpapers", Path.home() / "Pictures",
                                   Path("/home/leo/WhiteSur-wallpapers")) if p.exists()) or (Path.home() / "Pictures",)
# Location history (lightweight): the laptop logs its position only this often (default 30 min); the worker
# wakes every LOCATION_TICK_S but does network work only when LOCATION_LOG_INTERVAL_S has passed (or lost mode).
LOCATION_HISTORY = os.getenv("KURAMA_LOCATION_HISTORY", "1").lower() not in ("0", "false", "no", "off")
LOCATION_TICK_S = 300.0  # the worker's heartbeat (cheap: usually just checks the clock)
LOCATION_LOG_INTERVAL_S = float(os.getenv("KURAMA_LOCATION_INTERVAL_S", str(30 * 60)))  # normal logging cadence
LOCATION_LOST_INTERVAL_S = 120.0  # while "lost mode" is on, log this often
LOCATION_LOST_MAX_H = float(os.getenv("KURAMA_LOST_MAX_H", "6"))  # lost mode switches itself off after this
LOCATION_MIN_MOVE_M = 120.0  # a fix closer than this to the last one is treated as the same spot (no new point)
LOCATION_KEEP_DAYS = 60.0  # older points are pruned, so the table stays tiny
FOCUS_CLOSE: tuple[str, ...] = ()  # apps focus_mode closes at start, e.g. ("discord", "telegram")
MUSIC_VOLUME = int(os.getenv("KURAMA_MUSIC_VOLUME", "100"))  # mpv start volume until the user sets one (kept):
# mpv's scale is cubic, 60 was ~-13 dB, far quieter than the same song in the browser (owner 11-03)
PLAYLISTS: dict[str, str] = {}  # spoken name -> URL or local music folder ('save this playlist as X' adds more)

# --- P9b --- reminders / scheduled commands, RAM-aware jobs, resume
SCHEDULER_INTERVAL_S = 15.0  # scheduler worker tick
SCHEDULE_MISSED_GRACE_S = 3600.0  # items later than this (laptop off) are marked missed, not run
REMINDER_LEAD_S = 60.0 * float(os.getenv("KURAMA_REMINDER_LEAD_MIN", "10"))  # heads-up this long before a reminder
NOTIFY_CONTEXT_S = 12 * 3600.0  # the agent knows the messages it sent the user in this window
CROSS_CHANNEL_S = 30 * 60.0  # laptop <-> Telegram: the other channel's chat from this window is shared
JOB_RESOURCE_GATE = os.getenv("JARVIS_JOB_GATE", "1").lower() not in ("0", "false", "no", "off")
JOB_MIN_FREE_MB = int(os.getenv("JARVIS_JOB_MIN_FREE_MB", "800"))  # queued jobs wait below this free RAM
JOB_MAX_LOAD_PER_CORE = 1.5  # ...or while the 1-min load average exceeds cores x this
JOB_RECHECK_S = 10.0
JOB_MAX_WAIT_S = 600.0  # then they start anyway (with a note)
# Long Job Engine (longjobs.py; Night Shift foundation): durable, checkpointed, resumed after a restart,
# per-job time/token caps, paused while RAM is short / battery is low / (needs_power) not charging.
LONG_JOBS_MAX_WORKERS = 2  # own threads; at most ONE CPU-heavy long job runs at a time (heavy=True)
# "keep this for later" vs "do it now" (planner.queue_meant, by meaning): a job-list add must never start the work
# 0-token shortcuts chosen by MEANING (fastpath.meaning_intent): the request is closest to one of these actions,
# and it names nothing the examples don't (a job number, another folder): else the AI does it. Seen in traces as
# frequent AI requests (10-29..11-01: 'copy the path of this folder' 7x, 'open this folder in vs code' 11x,
# 'start the jobs' 4x up to 8.5k tokens).
MEANING_SHORTCUTS: dict[str, tuple[str, ...]] = {
    "switch_tab": ("switch to the X tab", "go to the X tab in my browser", "show me the X tab", "open the X tab",
                   "switch to X tab of my brave browser", "take me to the X tab"),
    "list_tabs": ("what tabs are open", "list my browser tabs", "which tabs do i have open", "show all my tabs",
                  "give me the list of tabs open in my browser", "tell me the tabs open in my browser"),
    "close_tab": ("close the X tab", "close X tab in my browser", "shut the X tab"),
    "close_all_tabs": ("close all tabs", "close every tab in my browser", "close all the browser tabs",
                       "shut all my tabs"),
    "scroll_down": ("scroll down", "scroll down a bit", "scroll down a lot", "go down the page", "scroll down more", "scroll down a little",
                    "move the page down"),
    "scroll_up": ("scroll up", "scroll up a bit", "scroll up a lot", "go up the page", "scroll up more", "scroll up a little",
                  "move the page up"),
    "colab_setup": ("set up a colab notebook for training", "give me the colab cell to watch my training",
                    "connect my colab training to kurama", "colab setup code", "setup google colab notebook",
                    "give me the colab notebook", "how do i connect colab to you", "set up colab",
                    "setup colab notebook to watch out my training"),
    # KURAMA about itself: its own settings (a safe list, core/usersettings.py), explaining what it just did, help
    "settings_list": ("what settings can i change", "show my settings", "what can i change in you", "list your settings",
                      "show all kurama settings"),
    "setting_change": ("make the speed test X seconds", "set the X to X", "change the X to X", "increase the X to X",
                       "decrease the X to X", "make the X X minutes", "set X to X seconds", "make your replies longer X",
                       "change the setting X to X", "talk faster X", "speak slower X"),
    "setting_keep": ("make it permanent", "keep it always", "always use that", "save that setting", "make that the "
                     "default", "keep that setting", "use that every time"),
    "setting_undo": ("undo that setting", "undo the setting change", "put the setting back", "undo the last setting"),
    "settings_reset": ("reset all settings", "reset my settings to default", "put every setting back to default"),
    "help_me": ("help me use kurama", "how do i use you", "i am confused how to use you", "what commands can i use",
                "show me what you can do", "how do i use kurama"),
    # the Claude Code watch (core/claudewatch.py), in plain words; the same as /claude on|off|status|report
    "claude_on": ("watch my claude code", "start watching claude code", "turn on the claude code watch",
                  "keep an eye on claude code", "watch claude code for me", "now watch the claude code"),
    "claude_off": ("stop watching claude code", "turn off the claude code watch", "don't watch claude code anymore"),
    "claude_status": ("what is claude code doing", "claude code status", "how is claude code going",
                      "is claude code done", "what is happening in claude code", "how much has claude code done"),
    "claude_report": ("give me the claude code report", "claude code report", "what did claude code do",
                      "report of the claude code task"),
    "claude_go": ("open claude code", "open a new claude code chat", "start claude code here", "launch claude code",
                  "get claude code ready", "go to claude code", "switch to claude code", "take me to claude code",
                  "open claude code in vs code"),
    # 'ask gemini why this works': the question is free text (like tg_message), the site is read from the words
    "ask_ai": ("ask gemini why this works", "ask chatgpt what this means", "ask claude to explain this code",
               "send this to gemini", "ask gemini about the selected text", "ask chatgpt how to fix this",
               "ask it to explain simpler", "ask the ai about this", "ask claude why this fails", "ask claude about this",
               "ask gemini X", "ask chatgpt X"),
    "clear_chat": ("clear", "clear the chat", "clear chat", "new chat", "start a new chat", "fresh chat",
                   "forget this conversation", "clear this conversation"),
    "yt_summary": ("summarize this youtube video", "what is this video about", "summary of this youtube video",
                   "give me the main points of this video", "summarize the video i'm watching"),
    "git_push": ("push my work", "push my code to github", "commit and push my changes", "push this project",
                 "save my work to github"),
    "phone_screen": ("show my phone", "show my phone screen", "control my phone from the laptop", "mirror my phone",
                     "open my phone on the laptop"),
    "phone_pair": ("pair my phone", "connect my phone with kde connect", "pair kde connect", "link my phone over wifi"),
    "phone_close": ("close my phone", "stop showing my phone", "turn off the phone screen on the laptop",
                    "disconnect my phone", "close the phone window"),
    "phone_ring": ("ring my phone", "make my phone ring", "where is my phone ring it"),
    "explainer": ("make an explainer video about how transformers work", "make a reel about how ai works",
                  "make a video explaining neural networks", "create an educational video on backpropagation",
                  "make a youtube video about attention"),
    "find_content": ("find the pdf about attention i downloaded last week", "find my notes on backpropagation",
                     "which document talks about transformers", "the notebook where i trained the cnn",
                     "find the file that mentions gradient descent", "search inside my files for X"),
    "laptop_health": ("how is my laptop health", "check my battery health", "laptop health report",
                      "how healthy is my battery", "is my laptop healthy"),
    "day_start": ("start my day", "good morning let's start work", "open my work from yesterday",
                  "set up my work like yesterday", "begin my work day"),
    "day_done": ("done for today", "i'm done for the day", "end my day", "close my work for today",
                 "wrap up my day", "finish work for today"),
    "claude_stop": ("stop claude code", "interrupt claude code", "make claude code stop working", "cancel the claude code task"),
    "claude_usage": ("claude code usage", "how much claude code did i use today", "how many tokens did claude code use"),
    # your own commands ("when I say X, do Y" saves one): list them, forget one (X = its words)
    "my_commands": ("show my commands", "list my custom commands", "what are my own commands",
                    "show the words i taught you", "list my words", "what commands did i teach you",
                    "give me the list of rules i gave you", "what rules did i give you", "show my rules",
                    "what are the rules that i set", "give me the list of rules that i set", "which rules did i set",
                    "the commands i set", "what did i teach you to do when i say something",
                    "give me list of rules set by me", "list of commands made by me", "rules created by me"),
    "my_command_forget": ("forget my command X", "delete my custom command X", "remove my command X",
                          "forget when i say X"),
    "kaggle_setup": ("set up kaggle", "setup kaggle notebook for training", "give me the kaggle notebook",
                     "code to paste in my kaggle notebook so you can watch the training", "kaggle setup",
                     "connect my kaggle training to kurama", "how do i connect kaggle to you"),
    "new_folder": ("create a new folder here named X", "make a folder called X in this folder", "new folder here",
                   "create folder X here", "make a new folder in this folder", "create a new folder in here, name it X",
                   "create a new folder in X named X", "make a folder called X in X"),
    "show_desktop": ("go to the home screen", "show me the desktop", "minimize all windows", "hide every window",
                     "take me to the home screen"),
    # one window (X = the app, none = the window you were in): 0 tokens. 11-05: 'Minimize the window.' went to the
    # home screen (every window), 'Minimized Browser' cost 1.5k tokens
    "window_minimize": ("minimize the window", "minimize this window", "minimize X", "minimize the X window",
                        "minimise X", "hide the X window", "minimize the current window", "put X down"),
    "window_maximize": ("maximize the window", "maximize this window", "maximize X", "maximize the X window",
                        "make X full screen", "make this window full screen", "make X bigger"),
    "window_restore": ("restore the window", "restore X", "bring X back", "unminimize X", "show the X window again",
                       "bring back the X window"),
    "copy_path": ("copy the path of this folder", "copy this file's path", "put the path of the selected folder in "
                  "my clipboard", "copy the full path of the current folder", "copy the location of this file",
                  "path copy gara"),
    "open_vscode": ("open this folder in vs code", "open vs code in this folder", "open the selected folder in code",
                    "open this file with visual studio code", "open the current folder in my code editor",
                    "launch vscode here",
                    # a folder by name, also as a path in words (11-05: 'From the project1, then new project, there is
                    # the folder name Kurama, open this folder in VS Code.' cost 3.8k tokens and saved a link)
                    "open the X folder in vs code", "open X in vs code", "open the X folder from X in vs code",
                    "in X open the X folder with vs code", "from X there is a folder X, open it in vs code",
                    "open the X folder in the X project in vs code"),
    # X = the name the user gives: whatever words are left after the action's own words (none -> KURAMA asks)
    "save_link": ("save this link as X", "save this page as X", "store this website link as X", "bookmark this site "
                  "as X", "keep this page's link under the name X", "save this url with the name X",
                  "add this website to my link store as X", "this website is my X link, save it",
                  "save the link of this site for X", "put this page in my links named X", "save this video link as X"),
    "list_links": ("show me my link store", "list my saved links", "give me all my links", "what links did I save",
                   "show the link store list", "what is in my link store"),
    "read_later_add": ("save this page to read later", "add this article to my reading list",
                       "keep this link to read later", "read this later"),
    "clean_ram": ("free ram", "free up my memory", "clear the ram", "my laptop ram is full, clean it",
                  "release some memory", "optimize ram usage"),
    "clean_kurama": ("clear kurama cache", "clean your own cache", "clear the cache of kurama", "clean kurama storage",
                     "delete kurama's temp files and old logs", "clear kurama"),
    "clean_storage": ("free disk space", "clear the cache on my laptop", "clean my storage", "my disk is full, clean it",
                      "delete caches that rebuild themselves"),
    "jobs_start": ("start the jobs", "start working on my job list", "run all the waiting jobs", "do the jobs now",
                   "begin the queued jobs", "work on your job list now"),
    "jobs_list": ("show my job list", "what jobs are waiting", "list the jobs you have", "what is in your job list",
                  "show the queued jobs", "which jobs are pending"),
    # everyday one-tool questions the word patterns missed (11-03 traces: 'What is date today in Nepal?' 1.4k
    # tokens, 'What is the status of my battery?' 3k, 'show git status now' 3.2k, 'show me the daily summary bro' 2.7k)
    "time_now": ("what time is it", "what is the time now", "tell me the time", "what is the time in nepal right now",
                 "time kati bhayo", "time kya hua hai", "kitne baje hain", "what's the time today", "current time please"),
    "date_today": ("what is the date today", "what is today's date", "what is date today in nepal", "aaja kati gate",
                   "aaj kya tarikh hai", "which day is it today", "tell me today's date"),
    "battery": ("what is the status of my battery", "how much battery is left", "battery percentage", "check my battery",
                "is my laptop charging", "how is my battery health", "how much charge do I have"),
    "git_status": ("show git status", "show me the git status now", "git status of this project",
                   "what changed in git", "any uncommitted changes in this repo"),
    "daily_summary": ("show me the daily summary", "give me my daily digest", "summary of my day",
                      "what did I do on my laptop today", "my daily report please"),
    # a short text message to the owner's Telegram (the words after 'send' / 'saying' are the message): 0 tokens
    "tg_message": ("send X to telegram", "send X to my telegram", "message me on telegram saying X",
                   "send a message to my telegram saying X", "text X to my phone", "send X on telegram",
                   "telegram me X", "send me X on telegram"),
}
MEANING_SHORTCUT_AREAS = {"save_link": "links", "list_links": "links", "read_later_add": "links", "copy_path": "clipboard",
                          "open_vscode": "files", "jobs_start": "jobs", "jobs_list": "jobs",
                          "clean_ram": "system", "clean_kurama": "system", "clean_storage": "system", "show_desktop": "windows", "window_minimize": "windows", "window_maximize": "windows", "window_restore": "windows", "switch_tab": "windows",
                          "list_tabs": "windows", "close_tab": "windows", "close_all_tabs": "windows", "scroll_down": "windows", "scroll_up": "windows", "colab_setup": "watch", "kaggle_setup": "watch", "settings_list": "self", "new_folder": "files",
                          "tg_message": "telegram", "time_now": "general", "date_today": "general",
                          "battery": "power", "git_status": "git", "daily_summary": "usage"}  # the router offers it too
MEANING_SHORTCUT_MIN = 0.82
# actions that change everything on screen need more certainty ("show my screen" is not "go to the home screen": 0.86)
MEANING_SHORTCUT_MIN_BY = {"show_desktop": 0.90, "colab_setup": 0.90, "kaggle_setup": 0.90, "help_me": 0.90,
                           "explain_last": 0.86, "capability_ask": 0.89}  # "what is colab" is a question (0.87)
MEANING_FOLDER_MIN = 0.80  # 'open <a real folder named in words> in vs code': harmless, and the folder must exist
# the KIND of request, from how it starts (core/querykind.py): a question about using KURAMA is answered with the
# command to say, never done; a question about what KURAMA does is explained
QUERY_OPENINGS = {
    "help": ("how can i", "how do i", "how to", "how should i", "help me with", "help me to", "which command",
             "what command", "what should i say to", "tell me how to", "is there a way to", "show me how to"),
    "ability": ("do you have the ability to", "are you able to", "is it possible to", "is it possible for you to",
                "do you support", "do you know how to", "do you have a feature to", "do you have abality"),
    "command": ("can you", "could you", "would you", "will you", "please", "can u"),  # polite commands: done, not
    #                                                                                   explained ('can you open youtube')
    "explain": ("how did you", "how do you", "why did you", "what did you use", "where did you get", "how does kurama",
                "explain how you", "what method do you use", "how you", "how does that work"),
}
QUERY_OPENING_MIN = 0.90
SUGGEST_NEXT = True  # after an image / screenshot / document: "Say yes to send it to your Telegram" (core/nextstep.py)
HELP_TOOL_MIN = 0.68  # a help question is answered with a command only when a tool fits this well (else the AI)
MEANING_EXPLAIN_MIN = 0.80  # "how you measure that?" right after an answer that names it ('it / that / you')
MEANING_SETTING_MIN = 0.78  # 'set <a real setting> to <a valid value>': checked against the safe list and its range
# talk mode, speech long after KURAMA spoke: it is for KURAMA if it greets it or clearly MEANS an action (calibrated on
# stt.log 10-30..11-01: 'Hello, shut down the laptop.' power 0.88; room talk 0.65-0.72)
AMBIENT_ACTION_MIN = 0.80
AMBIENT_OVER_CHAT = 0.05  # this close to the action's examples (bge-small cosine) to run it without the AI
QUEUE_EXAMPLES: dict[str, tuple[str, ...]] = {
    "later": ("add a job: write an essay about Nepal", "keep this job for later", "put this in your job list",
              "add to my job list: research black holes and send it to telegram", "save this as a job, don't start it",
              "remember this job for later: make a presentation about AI", "add job write python code for a calculator",
              "note a job for you: summarize my lecture notes", "for later: clean up my desktop files",
              "queue this task, do it later: translate my notes to Nepali", "a job for you when I say start: back up my photos",
              "don't do it now, just add it: download the lecture playlist", "job for later, compare three laptops under 1 lakh",
              "add these to your jobs: email draft, budget sheet", "put on your to-do for later: fix the bug in main.py"),
    "now": ("write an essay about Nepal", "research black holes and send it to telegram", "make a presentation about AI",
            "generate an image of a dog", "write python code for a calculator", "start working on my jobs",
            "summarize my lecture notes", "list my jobs", "make a ppt about global warming", "clean up my desktop files",
            "translate my notes to Nepali", "back up my photos now", "download the lecture playlist",
            "compare three laptops under 1 lakh", "fix the bug in main.py", "create a budget sheet for this month",
            "organize my downloads folder", "show my job list", "remove job 2"),
}
READLATER_EXAMPLES = ("save this page for later", "read this later", "save this video for later",
                      "add this link to my reading list", "keep this tab to read later", "watch this later",
                      "save this article to read tonight", "put this website in my read later list")
QUEUE_NOW_MARGIN = 0.04  # clearly 'do it now' below this (planner.queue_meant)
SEND_FOLDER_ASK_MB = 100  # a folder bigger than this is sent only after a yes (zipping + uploading takes minutes)
SHARE_MAX_MB = int(os.getenv("KURAMA_SHARE_MAX_MB", "20000"))  # folders over Telegram's 50 MB: zip + link up to this
QUEUE_ASK_S = 120  # a job that needs your yes asks on Telegram and waits this long (no answer = no)
QUEUE_PARALLEL = 2  # while a job waits for your answer, the next one may run (at most this many at once)
QUEUE_RETRIES = 3  # a job in KURAMA's job list: tries when the failure looks temporary (network, AI limits)
QUEUE_MAX_TOKENS = 80000  # the whole job-list run's hard cap (each essay also has its own writer cap)
QUEUE_MAX_MINUTES = 240
WRITER_JOB_MAX_TOKENS = 60000  # an essay / report / code job's hard cap (a 3,000-word essay is ~10-15k)
LONG_JOB_DEFAULT_TOKENS = 4000  # token cap when the caller gives none (= AGENT_ASK_ABOVE_TOKENS)
LONG_JOB_DEFAULT_MINUTES = 60  # running-time cap when the caller gives none (paused time doesn't count)
LONG_JOB_PAUSE_FREE_MB = int(os.getenv("JARVIS_LONG_JOB_PAUSE_FREE_MB", "500"))  # pause below this free RAM
LONG_JOB_PAUSE_BATTERY = 30  # pause below this battery % while not charging
LONG_JOB_RECHECK_S = 15.0  # while paused: re-check every this many seconds
LONG_JOB_PROBE_S = 5.0  # RAM / battery / pause flag / tokens checked at most this often while running
LONG_JOB_AUTO_RESUME = os.getenv("JARVIS_LONG_JOB_AUTO_RESUME", "1").lower() not in ("0", "false", "no", "off")

# --- agents (jarvis/agents): off until the owner turns one on ---
AGENT_MARKER = Path(os.getenv("KURAMA_AGENT_MARKER", str(Path.home() / ".local" / "share" / "kurama" / "agent")))
CODING_OTHER_MAX = 0.78  # coding mode takes a plain-words change / bug report unless another area means it this much
STUDY_OTHER_MAX = 0.80  # ... and a question about the highlight goes to it unless another area means it this much
STUDY_CHAT_MAX_CHARS = 3500  # Study mode answers up to this stay whole in its chat (longer ones: the workspace)
STUDY_MIN = 0.78  # Study mode takes a request when its meaning is this close to one of its tasks
AGENT_IDLE_OFF_S = float(os.getenv("KURAMA_AGENT_IDLE_MIN", "45")) * 60  # an agent unused this long turns itself off
AGENT_PENDING_TTL_S = 900  # a shown change waits this long for its yes
AGENT_FAILURE_MAX_AGE_S = 1800  # "fix it" means a crash from the last 30 min
AGENT_OUTPUT_MAX = 6000  # characters of a failed command's output kept
AGENT_FIX_MAX_FILES = 2  # files of the traceback sent to the AI
AGENT_WHOLE_FILE_LINES = 250  # smaller files are sent whole, bigger ones around the crash
AGENT_FIX_MAX_TOKENS = 3000
AGENT_BRIDGE_FILE_CHARS = 12000  # per file in the ChatGPT/Gemini prompt
AGENT_PROJECTS_DIR = os.getenv("KURAMA_PROJECTS_DIR", "~/projects")
AGENT_PROJECT_MAX_FILES = 8
AGENT_PROJECT_MAX_TOKENS = 4500  # the code of the template's files, short
AGENT_PIP_TIMEOUT_S = 600
AGENT_FIRST_RUN_S = 8  # a first run still going after this long is a server that started fine
AGENT_MIN = 0.80  # meaning closeness for a coding-agent request (0-token routing while the agent is on)
AGENT_TOOL_MODULES: tuple[str, ...] = ()  # extra agent tool modules; jarvis/agents/<name>/tools.py is found by itself
AGENT_GROUPS = ("coding_agent", "study_mode")  # (+ every agent SPEC.groups, see agents.groups()) never routed to by the router; the active agent offers its own
AGENT_ASK_ABOVE_TOKENS = int(os.getenv('KURAMA_AGENT_ASK_TOKENS', '4000'))  # bigger agent jobs ask first (owner)
AGENT_PROJECT_TOKENS_PER_FILE = 700  # rough output per code file of a new project
EDITOR_EXT_MIN = 4  # the VS Code extension version that reports terminal crashes
AGENT_UNDO_MIN = 0.90  # undo puts code back: only a near-exact 'undo that'
AGENT_PROJECT_MIN = 0.74  # 'make a yolo object detection project' (still must beat every other area)
AGENT_OVER_SELECTION = 0.05  # an agent action must beat the closest editing action by this much

SPEEDTEST_SECONDS = 15  # the whole internet speed test (download ~55%, upload ~40%); the owner can change it

# --- the owner's own settings (jarvis/core/usersettings.py: a fixed safe list, changed by voice/text) ---
SETTING_DEFAULTS: dict = {}  # the values from this file for every setting the owner changed


def _apply_user_settings() -> None:
    import json
    import sys
    if "pytest" in sys.modules:  # tests always see this file's values
        return
    try:
        saved = json.loads((DATA_DIR / "user_settings.json").read_text(encoding="utf-8")).get("values") or {}
    except (OSError, ValueError, AttributeError):
        return
    g = globals()
    for k, v in saved.items():
        if k.isupper() and k in g and not callable(g[k]) and type(v) in (int, float, str):
            SETTING_DEFAULTS.setdefault(k, g[k])
            g[k] = v


_apply_user_settings()

# --- the Nepal documents service (core/nepaldocs.py; URL + key in .env: KURAMA_RAG_API_URL, KURAMA_RAG_API_KEY) ---
NEPAL_DOCS_TIMEOUT_S = 60.0  # it usually answers in 5-15 s
NEPAL_DOCS_CACHE_S = 6 * 3600  # the same question again within 6 h: the saved answer
NEPAL_LANE_MIN = 0.80  # the request is this close to a Nepal-documents example...
NEPAL_LANE_MARGIN = 0.02  # ...and closer than to every other lane (search, general, ...) by this much
# Nepali / Hindi in Devanagari (the meaning model reads English only): these words stand in for the meaning check
NEPAL_DEVANAGARI_WORDS = ("संविधान", "कानुन", "कानून", "ऐन", "नियमावली", "नियम", "नागरिकता", "राहदानी", "पासपोर्ट",
                          "जिल्ला", "प्रदेश", "विवाह", "बिहे", "सम्बन्ध विच्छेद", "पारपाचुके", "लाइसेन्स", "अनुमतिपत्र",
                          "मालपोत", "जग्गा", "अदालत", "मुद्दा", "सजाय", "जरिवाना", "दस्तुर", "शुल्क", "प्रक्रिया", "अंशबण्डा",
                          "नेपालको", "नेपाल")

# --- Claude Code watch (core/claudewatch.py; '/claude on|off|status|report|yes|no|say') ---
CLAUDE_ANSWER_WAIT_S = 600.0  # a permission question waits this long for your Telegram answer, then the laptop asks
CLAUDE_STUCK_S = 600.0  # a working task silent this long: one "⚠️ quiet" message
