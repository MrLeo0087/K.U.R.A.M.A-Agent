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
TELEGRAM_MAX_AGE_S = 120  # ignore Telegram messages sent more than this long before the bot started

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
    "fast": [LLM_FAST, LLM_DEFAULT],  # if the fast model errors/is rate-limited, fall back to the smart one
    "vision": [LLM_VISION, LLM_DEFAULT],  # second vision model; the text fallback still answers non-image asks
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
# Run a Nepali-forced large-v3 pass in parallel with auto-detect and pick the trustworthy one
# (Whisper mislabels Nepali as English/Slovak/Hindi). Doubles STT calls, adds no latency.
STT_DUAL = os.getenv("JARVIS_STT_DUAL", "1").lower() not in ("0", "false", "no", "off")
STT_EN_MIN_LOGPROB = -0.6  # auto "English" below this confidence is treated as suspicious
# Whisper vocabulary hint (biases spelling of names/apps; tested not to break hi/ne detection).
STT_NO_SPEECH_MAX = 0.6  # Whisper's no_speech_prob above this...
STT_GARBAGE_LOGPROB = -1.0  # a short transcript (<= 4 words) below this confidence = noise ('The', 'RUN', 'E aí')
STT_FOREIGN_MAX_LOGPROB = -0.6  # Whisper says a language we don't speak AND confidence is below this = noise
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
    "volumn": "volume", "volum": "volume", "valume": "volume", "volumne": "volume", "voulme": "volume",
    "alram": "alarm", "alaram": "alarm", "allarm": "alarm", "remainder": "reminder", "remiander": "reminder",
    "traning": "training", "trainig": "training", "usuage": "usage", "useage": "usage", "staus": "status",
    "statsu": "status", "thsi": "this", "niw": "now", "insdie": "inside", "insde": "inside", "plz": "please",
    "pls": "please", "wht": "what", "whta": "what", "teh": "the", "laptop.doctor": "laptop doctor",
    "scrrenshot": "screenshot", "screnshot": "screenshot", "brigthness": "brightness", "volumn": "volume",
    "telgram": "telegram", "telegarm": "telegram", "downlaod": "download", "donwload": "download",
    "foler": "folder", "fodler": "folder", "folde": "folder", "summarise": "summarize",
}
STT_FIXES: dict[str, str] = {
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
PTT_KEY = os.getenv("KURAMA_PTT_KEY", "super+z")  # hold Super+Z: free in GNOME, never reaches apps (Ctrl+Space = VS Code suggest)
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
    "memory": ("memory", "knowledge", "browser", "self"),
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
                      "screenshot": "screenshot", "send_message_telegram": None, "get_time": "time"}
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
TOOL_NO_BACKGROUND = ("start_job", "generate_image", "write_document", "jobs", "make_tool",
                      "focus_mode", "gesture_control", "power_off", "suspend_computer",
                      "read_text", "scan_qr")  # these wait for the user to drag a box: never "still working"
TOOLSMITH_OFFER = True  # a refusal on a real task always offers to build a tool (asks first)
AGENT_MAX_TOOL_ROUNDS = 4  # llm -> tools loops per request, then the model must answer
AGENT_MAX_TOKENS = 400
AGENT_SUMMARY_BATCH_TURNS = 3  # fold this many old turns into the rolling summary at once
CONFIRM_TIMEOUT_S = 20.0  # unanswered confirmations are denied
ROUTER_MAX_GROUPS = 3
# Free phrasing for tools: paraphrases embedded by the semantic router (0 tokens), so "enable speech to text
# mode" finds dictate even though no keyword rule says so. Add a few lines here for any tool that gets missed.
TOOL_EXAMPLES: dict[str, tuple[str, ...]] = {
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
MEANING_GATE_MARGIN = 0.15  # a shortcut runs only if its area scores within this of the best area (by meaning)
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
SMALL_TALK_SIM = 0.86  # the whole request this close to a small-talk example = its ready answer (0 tokens)
LEARN = os.getenv("KURAMA_LEARN", "1").lower() not in ("0", "false", "no", "off")  # learn areas from corrections
LEARN_WINDOW_S = 120  # a correction counts within this long after the request it corrects
LEARN_CORRECTION_SIM = 0.80  # similarity to an example correction ("no, I meant...") to count as one
LEARN_WORKED_MAX_CORR = 0.65  # "it worked" is learned only if the next message is not even close to a correction
LEARN_VETO_SIM = 0.92  # a corrected wording this similar never runs that shortcut again
LEARN_MAX = 3000  # learned wordings kept (newest)
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
    "tracker": ("spent 500 on food", "how much did I spend this month", "set my food budget to 8000",
                "check in my exercise habit", "show my habit streaks", "add a habit to read 20 pages a day"),
    "system": ("my laptop feels slow and laggy", "what is eating my memory", "check cpu and ram usage",
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
            "I fixed that error by", "check my dataset for problems before training", "is my data balanced"),
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
    "media": ("pause the music", "next track please", "play my playlist"),
    "screen": ("capture my screen", "screenshot of this window"),
    "power": ("how much charge is left", "lock the screen", "shut down the computer", "put it to sleep",
              "guard my laptop while I am away", "where is my laptop", "anti theft"),
    "image": ("make an image of a cat in space", "create a picture of mountains", "draw a logo"),
    "web": ("search online for", "look this up on the internet", "who won the match yesterday",
            "latest news about technology", "tell me when this website changes", "watch the exam results page",
            "let me know when the notice board page updates"),
    "memory": ("remember that my wifi password is", "what did I tell you about", "what did we discuss last time"),
    "knowledge": ("how does my code handle this", "find where my project loads the config", "explain my repo"),
    "usage": ("how many tokens did I use", "give me a summary of today"),
    "jobs": ("write a detailed report in the background", "how is my background job going", "cancel the job"),
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
ROUTER_URL_GROUP = "browser"  # group for messages containing a URL/domain
ROUTER_SITE_OVER_APPS = True  # "open youtube": a known site/URL drops the apps group (browser wins)
FASTPATH = os.getenv("JARVIS_FASTPATH", "1").lower() not in ("0", "false", "no", "off")  # regex intents, 0 tokens
ASSISTANT_NAME = os.getenv("KURAMA_NAME", "KURAMA")  # default name; the user can change it (core/identity.py)
# Owner password for protected self-information (architecture, storage, security). Only a salted hash is kept;
# change it with KURAMA_PASSWORD_HASH=sha256(SELF_PASSWORD_SALT + lowercase password).
SELF_PASSWORD_SALT = "kurama-self-v1:"
SELF_PASSWORD_HASH = os.getenv("KURAMA_PASSWORD_HASH", "8e1e9a607be9d9e165f378291be7324a139bd1f15e8e3c2e41a2e78ab95d2e6d")
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
    "tracker": "money spent/earned, budgets, bills; habit streaks",
    "general": "time and date (any city or country), simple utilities",
    "weather": "current weather and up to 3-day forecast for any place",
    "files": "create folders, write files, move/copy, move to trash",
    "filesearch": "find files by name or by text content; open a folder by name",
    "telegram": "send a file (by path or name) or a message to the user's Telegram (phone); mute alerts",
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
    "web": "search", "memory": "notes",
    "knowledge": "code", "usage": "tokens", "browser": "",
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
TELEGRAM_POLL_TIMEOUT_S = 6  # long-poll seconds (short so Ctrl+C stops the workers quickly)
TELEGRAM_CONFIRM_TIMEOUT_S = 60.0  # "Reply yes/no": no answer in time means no
TELEGRAM_ANSWER_TIMEOUT_S = 90.0  # a reply that takes longer than this is given up on (no "typing" forever)
TELEGRAM_MAX_REPLY_CHARS = 3500
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
MUSIC_VOLUME = int(os.getenv("KURAMA_MUSIC_VOLUME", "60"))  # mpv start volume for 'play lofi music'
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
LONG_JOB_DEFAULT_TOKENS = 4000  # token cap when the caller gives none (= AGENT_ASK_ABOVE_TOKENS)
LONG_JOB_DEFAULT_MINUTES = 60  # running-time cap when the caller gives none (paused time doesn't count)
LONG_JOB_PAUSE_FREE_MB = int(os.getenv("JARVIS_LONG_JOB_PAUSE_FREE_MB", "500"))  # pause below this free RAM
LONG_JOB_PAUSE_BATTERY = 30  # pause below this battery % while not charging
LONG_JOB_RECHECK_S = 15.0  # while paused: re-check every this many seconds
LONG_JOB_PROBE_S = 5.0  # RAM / battery / pause flag / tokens checked at most this often while running
LONG_JOB_AUTO_RESUME = os.getenv("JARVIS_LONG_JOB_AUTO_RESUME", "1").lower() not in ("0", "false", "no", "off")

# --- agents (jarvis/agents): off until the owner turns one on ---
AGENT_MARKER = Path(os.getenv("KURAMA_AGENT_MARKER", str(Path.home() / ".local" / "share" / "kurama" / "agent")))
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
AGENT_TOOL_MODULES = ("jarvis.agents.coding.tools",)
AGENT_GROUPS = ("coding_agent",)  # never routed to by the router; the active agent offers its own
AGENT_ASK_ABOVE_TOKENS = int(os.getenv('KURAMA_AGENT_ASK_TOKENS', '4000'))  # bigger agent jobs ask first (owner)
AGENT_PROJECT_TOKENS_PER_FILE = 700  # rough output per code file of a new project
EDITOR_EXT_MIN = 4  # the VS Code extension version that reports terminal crashes
AGENT_UNDO_MIN = 0.90  # undo puts code back: only a near-exact 'undo that'
AGENT_PROJECT_MIN = 0.74  # 'make a yolo object detection project' (still must beat every other area)
AGENT_OVER_SELECTION = 0.05  # an agent action must beat the closest editing action by this much
