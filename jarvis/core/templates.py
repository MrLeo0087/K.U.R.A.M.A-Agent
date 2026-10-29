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

COLAB = """Google Colab notebook setup (paste these cells at the top):

```python
# 1. GPU check (Runtime -> Change runtime type -> T4 GPU first)
!nvidia-smi
import torch; print(torch.cuda.is_available())

# 2. Your Google Drive (keeps files after the session ends)
from google.colab import drive
drive.mount('/content/drive')
%cd /content/drive/MyDrive

# 3. Packages
!pip install -q transformers datasets accelerate

# 4. Secrets (left bar -> key icon -> add HF_TOKEN etc.)
from google.colab import userdata
# token = userdata.get('HF_TOKEN')
```
Tips: save checkpoints to Drive; a free session stops after ~12 h or when idle. Say "open colab" to open it."""

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
    (re.compile(_LEAD + r"(?:give\s+me|show\s+me|how\s+(?:do|can|to)\s+i)?\s*(?:a\s+|the\s+)?(?:google\s+)?colab\s+(?:notebook\s+)?(?:setup|set\s*up)"
                r"|(?:give\s+me\s+)?(?:the\s+)?(?:setup|set\s*up)\s+(?:for\s+)?(?:a\s+|the\s+)?(?:google\s+)?colab(?:\s+notebook)?", I), {"en": COLAB}),
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
    (("hello", "hi kurama", "hey there", "good morning", "namaste", "yo kurama", "hello kurama how are you"),
     {"en": "Hello! What can I do for you?", "hi": "नमस्ते! बताइए क्या करूँ?", "ne": "नमस्ते! के गरूँ?"}),
    (("how are you", "how are you doing", "are you okay", "how do you feel today", "kasto xa", "kaise ho"),
     {"en": "I'm doing great, thanks! What can I do for you?", "hi": "मैं बढ़िया हूँ, धन्यवाद! क्या करूँ?",
      "ne": "म ठिकै छु, धन्यवाद! के गरूँ?"}),
    (("what are you doing", "what's up", "what are you up to", "k gardai xau", "kya kar rahe ho"),
     {"en": "Just waiting for your next command. What should I do?", "hi": "बस आपके अगले काम का इंतज़ार। क्या करूँ?",
      "ne": "तपाईंको अर्को कामको पर्खाइमा छु। के गरूँ?"}),
    (("how is your day going", "how was your day", "how's it going", "how are things", "is your day good"),
     {"en": "It's going well, thanks for asking! What can I do for you?", "hi": "अच्छा चल रहा है, धन्यवाद! क्या करूँ?",
      "ne": "राम्रै चलिरहेको छ, धन्यवाद! के गरूँ?"}),
    (("thank you", "thanks a lot", "nice job", "great work", "good job kurama", "dhanyabad", "shukriya"),
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
    from jarvis.core import planner
    if len(planner.split_clauses(t)) > 1:  # "hello, what are you doing, and tell me the time": parts, each answered
        return None
    global _st
    try:
        if _st is None:
            rows = [(i, ex) for i, (exs, _) in enumerate(SMALL_TALK) for ex in exs]
            _st = ([i for i, _ in rows], semantic.embedder().embed([ex for _, ex in rows], query=True))
        idx, mat = _st
        sims = (mat @ semantic.embedder().embed([t], query=True)[0]).tolist()
    except Exception:  # noqa: BLE001 - the model failed: no shortcut, the AI answers
        return None
    best = max(range(len(sims)), key=sims.__getitem__)
    return SMALL_TALK[idx[best]][1] if sims[best] >= config.SMALL_TALK_SIM else None
