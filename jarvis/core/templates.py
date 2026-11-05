"""Ready-made answers (0 tokens) for questions that always get the same answer: small talk and the usual setup
guides. Long ones go to the workspace by the chat rule; the chat shows the first line."""
from __future__ import annotations

import re

I = re.I
_LEAD = r"(?:(?:hey|hi|hello|okay|ok|so|please|kurama|can\s+you|could\s+you|will\s+you)\W+)*"

PYTHON_PROJECT = """Python project setup (Ubuntu): a clean folder, its own virtual environment, git.

```bash
mkdir myproject && cd myproject
python3 -m venv .venv            # the project's own Python
source .venv/bin/activate        # every new terminal: activate first
python -m pip install --upgrade pip
pip install requests pytest      # what you need
pip freeze > requirements.txt    # pin versions
git init
printf ".venv/\\n__pycache__/\\n*.pyc\\n.env\\n" > .gitignore
mkdir -p src/myproject tests && touch src/myproject/__init__.py tests/test_basic.py
```

Layout:
```
myproject/
  .venv/            (not committed)
  src/myproject/    your code
  tests/            pytest tests
  requirements.txt
  .gitignore
  README.md
```

Next time: `cd myproject && source .venv/bin/activate`. Install from the list: `pip install -r requirements.txt`.
In VS Code: Ctrl+Shift+P -> "Python: Select Interpreter" -> .venv."""

VENV = """Virtual environment in Python:

```bash
python3 -m venv .venv
source .venv/bin/activate      # Linux/macOS (Windows: .venv\\Scripts\\activate)
pip install <package>
deactivate                     # leave it
```
If `venv` is missing: `sudo apt install python3-venv`."""

_RULES: list[tuple[re.Pattern, dict]] = [
    (re.compile(_LEAD + r"how(?:'s|\s+is|\s+was)\s+(?:your|ur)\s+day(?:\s+going)?(?:\s+so\s+far)?|how\s+are\s+things|how(?:'s|\s+is)\s+it\s+going", I),
     {"en": "It's going well, thanks for asking! What can I do for you?", "hi": "अच्छा चल रहा है, पूछने के लिए धन्यवाद! बताइए क्या करूँ?",
      "ne": "राम्रै चलिरहेको छ, सोध्नुभएकोमा धन्यवाद! के गरूँ?"}),
    (re.compile(_LEAD + r"what\s+(?:are|r)\s+(?:you|u)\s+doing(?:\s+(?:now|right\s+now))?|what\s+are\s+you\s+up\s+to", I),
     {"en": "Just waiting for your next command. What should I do?", "hi": "बस आपके अगले काम का इंतज़ार कर रहा हूँ। क्या करूँ?",
      "ne": "तपाईंको अर्को कामको पर्खाइमा छु। के गरूँ?"}),
    (re.compile(_LEAD + r"(?:give\s+me|show\s+me|tell\s+me|how\s+(?:do|can|to)\s+i|help\s+me)?\s*(?:a\s+|the\s+)?(?:whole\s+|full\s+|complete\s+)?"
                r"(?:set\s*up|setup|create|make|start)\s+(?:a\s+|the\s+|my\s+)?(?:new\s+)?(?:environment\s+for\s+(?:a\s+|my\s+|the\s+)?)?python\s+"
                r"(?:project|environment|env)(?:\s+setup)?(?:\s+environment)?"
                r"|(?:give\s+me\s+)?(?:a\s+|the\s+)?(?:whole\s+|full\s+)?python\s+(?:project\s+)?(?:setup|set\s*up)", I), {"en": PYTHON_PROJECT}),
    (re.compile(_LEAD + r"(?:how\s+(?:do|can|to)\s+i\s+|give\s+me\s+|help\s+me\s+)?(?:create|make|set\s*up|setup|activate)\s+(?:a\s+)?(?:python\s+)?"
                r"(?:virtual\s+environment|venv)(?:\s+in\s+python)?", I), {"en": VENV}),
]


def match(text: str) -> dict | None:
    """The ready answer ({'en': ..., 'hi': ..., 'ne': ...}) for this text, or None."""
    t = " ".join((text or "").split()).strip(" .!?")
    for rx, ans in _RULES:
        if rx.fullmatch(t):
            return ans
    return None


# Small talk by MEANING (0 tokens): the WHOLE request must be one of these (any phrasing close to the examples);
# "hello, what are you doing and tell me the time" is split into parts first, so the time is still told.
SMALL_TALK: list[tuple[tuple[str, ...], dict]] = [
    (("hello", "hi kurama", "hey there", "good morning", "namaste", "yo kurama", "hello kurama how are you", "hello bro",
      "k xa khabar", "k cha khabar", "sanchai", "hello k xa khabar", "hello kurama bro"),
     {"en": "Hello! What can I do for you?", "hi": "नमस्ते! बताइए क्या करूँ?", "ne": "नमस्ते! के गरूँ?"}),
    (("how are you", "how are you doing", "are you okay", "how do you feel today", "kasto xa", "kaise ho",
      "kya haal hai", "kya ho raha hai", "how are you bro", "kya hora hai", "kya chal raha hai"),
     {"en": "I'm doing great, thanks! What can I do for you?", "hi": "मैं बढ़िया हूँ, धन्यवाद! क्या करूँ?",
      "ne": "म ठिकै छु, धन्यवाद! के गरूँ?"}),
    (("what are you doing", "what's up", "what are you up to", "k gardai xau", "kya kar rahe ho"),
     {"en": "Just waiting for your next command. What should I do?", "hi": "बस आपके अगले काम का इंतज़ार। क्या करूँ?",
      "ne": "तपाईंको अर्को कामको पर्खाइमा छु। के गरूँ?"}),
    (("how is your day going", "how was your day", "how's it going", "how are things", "is your day good"),
     {"en": "It's going well, thanks for asking! What can I do for you?", "hi": "अच्छा चल रहा है, धन्यवाद! क्या करूँ?",
      "ne": "राम्रै चलिरहेको छ, धन्यवाद! के गरूँ?"}),
    (("thank you", "thanks", "thanks a lot", "nice job", "great work", "good job kurama", "dhanyabad", "shukriya",
      "perfect, that's exactly what I wanted", "well done", "excellent", "ramro garyau"),
     {"en": "Happy to help!", "hi": "खुशी हुई मदद करके!", "ne": "सहयोग गर्न पाउँदा खुसी लाग्यो!"}),
    (("good night", "bye", "see you later", "talk to you later", "i'm going to sleep"),
     {"en": "Good night! I'll be here when you need me.", "hi": "शुभ रात्रि! ज़रूरत हो तो मैं यहीं हूँ।",
      "ne": "शुभ रात्री! चाहिँदा म यहीँ छु।"}),
    (("ok", "okay", "alright", "cool", "hmm", "nice", "😆", "😂", "👍"),
     {"en": "👍", "hi": "👍", "ne": "👍"}),
]
_st: tuple | None = None


def small_talk(text: str) -> dict | None:
    """A ready answer when the whole request MEANS one of the SMALL_TALK examples (model loaded), else None."""
    from jarvis.core import config, semantic
    t = " ".join((text or "").split())
    if not t or len(t.split()) > 10 or not semantic.ready():
        return None
    if re.match(r"^\W*(?:type|write|say|send|search|open|text|message|play|find|google)\s+\S", t, re.I):
        return None  # 'type hello here' is typing, not a greeting (11-04)
    from jarvis.core import planner
    # "hello, what are you doing, and tell me the time": parts, each answered; but "Hello, bro. How are you?" /
    # "Thanks. Thanks." are small talk in every part (cost 500-700 tokens each on 11-01): the last part's answer.
    # Only one-word parts ('Hello, bro.'): the whole text first ('bro.' alone isn't small talk: 11-03 an AI call)
    clauses = planner.split_clauses(t)
    parts = [p for p in clauses if len(p.split()) > 1]
    global _st
    try:
        if _st is None:
            rows = [(i, ex) for i, (exs, _) in enumerate(SMALL_TALK) for ex in exs]
            _st = ([i for i, _ in rows], semantic.embedder().embed([ex for _, ex in rows], query=True))
        idx, mat = _st

        def pick(texts: list[str]) -> int | None:
            picks = []
            for v in semantic.embedder().embed(texts, query=True):
                sims = (mat @ v).tolist()
                best = max(range(len(sims)), key=sims.__getitem__)
                if sims[best] < config.SMALL_TALK_SIM:
                    return None
                picks.append(idx[best])
            return picks[-1]

        got = pick(parts) if len(parts) > 1 else pick([t])
        if got is None and not parts and len(clauses) > 1:
            got = pick(clauses)
    except Exception:  # noqa: BLE001 - the model failed (or a different model's cache): no shortcut, the AI answers
        return None
    return None if got is None else SMALL_TALK[got][1]
