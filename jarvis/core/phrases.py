"""Many ways to say hello, thanks and goodbye (0 tokens), picked at random so KURAMA never sounds the same twice."""
from __future__ import annotations

import random
from datetime import datetime

OPEN = {
    "morning": ("Good morning", "Morning", "Good morning, sir", "Rise and shine", "Hello, good morning", "Top of the morning",
                "Good morning! Hope you slept well", "Morning, boss", "A fresh morning", "Good morning, nice to see you"),
    "afternoon": ("Good afternoon", "Afternoon", "Good afternoon, sir", "Hey, good afternoon", "Hello there",
                  "Afternoon, boss", "Good to see you this afternoon", "Hi, hope the day is going well"),
    "evening": ("Good evening", "Evening", "Good evening, sir", "Hey, good evening", "Welcome back this evening",
                "Evening, boss", "Hello, nice evening", "Good evening! Long day?"),
    "night": ("Hello", "Working late?", "Hey, night owl", "Still up?", "Hello, sir", "Late night session",
              "Hi there, burning the midnight oil?"),
}
ASK = ("what are we working on?", "what's the plan today?", "how can I help?", "what should we do first?",
       "I'm ready when you are.", "what's on your mind?", "shall we get started?", "what do you need?",
       "anything I can take off your plate?", "where do we begin?", "what are we building today?",
       "tell me what you need.", "how's it going?", "need a hand with something?", "let's make it a good one.",
       "what's next?", "what are we learning today?", "want your day's plan? Say 'morning brief'.",
       "type / to see every command.", "I'm all ears.")
HELLO = {"en": ("Hi! What can I do for you?", "Hey! What do you need?", "Hello! How can I help?", "Hi there, tell me.",
                "Hey, I'm here. What's up?", "Hello! Ready when you are.", "Hi! What are we doing?", "Namaste! What can I do?"),
         "hi": ("नमस्ते! बताइए, क्या करूँ?", "हाँ जी, बोलिए!", "नमस्ते! क्या मदद करूँ?", "हैलो! क्या करना है?"),
         "ne": ("नमस्ते! भन्नुहोस्, के गरूँ?", "हजुर, भन्नुहोस्!", "नमस्ते! के सहयोग गरूँ?", "हेलो! के गर्ने?")}
HOWRU = {"en": ("I'm good and ready. What should I do?", "All good here! What's up?", "Doing great, thanks for asking. You?",
                "Running smoothly. What can I do for you?", "I'm well! Ready for the next task.", "Fresh and ready. What's the plan?"),
         "hi": ("मैं ठीक हूँ, बताइए क्या करना है?", "बढ़िया हूँ! आप बताइए?", "सब ठीक है, क्या करूँ?"),
         "ne": ("म ठिक छु, के गर्नु पर्छ भन्नुहोस्।", "सन्चै छु! तपाईंलाई कस्तो छ?", "एकदम ठिक, के गरौं?")}
THANKS = {"en": ("You're welcome.", "Anytime!", "Happy to help.", "No problem.", "Glad I could help.", "Sure thing!",
                 "My pleasure."),
          "hi": ("कोई बात नहीं।", "आपका स्वागत है।", "खुशी हुई।"),
          "ne": ("स्वागत छ।", "केही छैन।", "खुसी लाग्यो।")}
BYE = {"en": ("Bye! Call me when you need me.", "See you soon!", "Take care! I'll be here.", "Goodbye! Have a good one.",
              "Catch you later!", "Bye for now. Just say KURAMA when you need me.", "See you! Don't work too hard.",
              "Take care, talk soon.", "Bye! Good luck with everything.", "Later! I'll keep an eye on things."),
       "hi": ("ठीक है, ज़रूरत हो तो बुलाइए।", "फिर मिलेंगे!", "अपना ख्याल रखिए!", "अलविदा, जल्दी मिलते हैं।"),
       "ne": ("हुन्छ, चाहिँदा बोलाउनुहोस्।", "फेरि भेटौंला!", "आफ्नो ख्याल राख्नुहोस्!", "बाई, छिट्टै भेटौं।")}
NIGHT_BYE = ("Good night! Sleep well.", "Good night, rest well.", "Sweet dreams! See you tomorrow.",
             "Good night. Tomorrow is a new day.")


def _part(hour: int) -> str:
    return "morning" if 5 <= hour < 12 else "afternoon" if hour < 17 else "evening" if hour < 22 else "night"


def greeting(now: datetime | None = None, rng: random.Random | None = None) -> str:
    rng = rng or random.Random()
    h = (now or datetime.now()).hour
    opener = rng.choice(OPEN[_part(h)])
    ask = rng.choice(ASK)
    sep = " " if opener.endswith(("?", "!", ".")) else ", "
    return f"{opener}{sep}{ask[0].upper() + ask[1:] if sep == ' ' else ask}"


def pick(table: dict, rng: random.Random | None = None) -> dict:
    """{'en': one of them, 'hi': ..., 'ne': ...} for a _say intent."""
    rng = rng or random.Random()
    return {k: rng.choice(v) for k, v in table.items()}


def bye(text: str = "", now: datetime | None = None, rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    out = pick(BYE, rng)
    h = (now or datetime.now()).hour
    if "night" in text.lower() or h >= 22 or h < 4:
        out["en"] = rng.choice(NIGHT_BYE)
    return out
