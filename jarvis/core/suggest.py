"""Suggestions under the chat box and on the first screen: a big pool of things KURAMA can do (all answered by the
0-token fast path), picked at random so they change every time, weighted by what I'm doing now:
VS Code in front / coding talk -> more coding ones (not only), morning -> the day, evening -> money and habits,
plus a few made from my own data (a habit not done yet, today's spending).
"""
from __future__ import annotations

import random
import re
import time
from collections import deque
from datetime import datetime

POOL: dict[str, tuple[str, ...]] = {
    "code": (
        "Find this function", "Go to definition", "Where is this function defined?", "What arguments does this take?",
        "Is this correct syntax?", "Did I use this function correctly?", "Run this code", "Run the selected code",
        "Explain this code", "What does this function do?", "Give me code to test this function",
        "How can I use this function?", "Check this file",
        "Diagram of this code", "Make a diagram of this project", "Where was I?",
        "What is running on port 8000?", "Show my open ports", "Is port 3000 free?", "List my coding projects", "Explain my whole code", "Help me with this library", "/def", "/args", "/run",
        "/ports", "/callgraph", "/diagram", "Make a call graph of this file", "Decode this", "/code",
        "Explain this error", "What does this error mean?", "Explain this file", "Write a docstring for this function",
        "What inputs break this function?", "What is the time complexity of this code?",
        "Show an example of using this class", "Convert this function to JavaScript", "Add type hints to this function",
        "What edge cases does this function miss?", "What is using port 8080?", "Which ports are in use?",
        "Is port 5000 free?", "Where does this function come from?", "Show me the real code of this function",
        "Take me to this function", "What parameters does this function take?", "Is this the right way to use it?",
        "Pretty print this json", "Decode this base64", "What does this regex do?", "Give me unit tests for this class",
        "Find bugs in this function", "What changed today in my code?",
    ),
    "day": (
        "What's on today?", "Morning brief", "How does my day look?", "Show my to-do list", "Show my reminders",
        "What time is it?", "What is the date today?", "Which week is this?", "Weather", "Weather tomorrow",
        "Weather in Kathmandu", "Weather in Pokhara", "Show my long tasks",
        "Show my saved links", "Summarize my day", "Show my notes", "Show my timetable",
        "What time is it in Tokyo?", "What is the date today in AD?",
        "/today", "/todo", "/brief", "/weather", "/goals",
    ),
    "money": (
        "How much did I spend today?", "How much did I spend this week?", "How much did I spend this month?",
        "Spending breakdown by category", "Show me the whole budget and expense", "Where did my money go this month?",
        "How much did I spend on food this month?", "How much did I spend on education this month?",
        "How much did I spend in the last 7 days?", "Show my expenses", "Show my expenses this week",
        "Chart my expenses", "Pie chart of my spending this month", "Expense report for the year", "/money", "/spending", "/chart",
    ),
    "habits": (
        "My habits", "Show my habit streaks", "How are my habits going?", "/habits",
    ),
    "media": (
        "Play lofi music", "Play some music", "Play nepali songs", "Play relaxing piano music", "Play jazz music",
        "Play focus music", "Play arijit singh songs", "Listen to old hindi songs", "Pause", "Next song",
        "What song is this?", "Music volume down", "Stop the music", "Pause the video", "Continue the video",
        "Generate an image of a misty Himalayan sunrise", "Make 4 versions of a red fox in the snow",
        "Draw a cat astronaut", "Generate an image of a cozy tea shop in Kathmandu", "Make a short video about the Himalayas",
        "Make a reel about Nepali momo", "Make an audio of this", "Turn the last result into audio",
        "/music", "/image a dragon over Pokhara", "/yt", "/play", "/pause",
    ),
    "web": (
        "Latest news", "Latest news in Nepal", "Gold price today", "Dollar rate today", "Bitcoin price",
        "Football scores", "What is this page about?", "Summarize this page", "Save this link",
        "Search the web for python asyncio", "Translate this to Nepali",
        "Translate this to Hindi", "Meaning of this word", "What does serendipity mean?", "Summary of this paragraph",
        "Explain this", "/news", "/search", "/translate",
    ),
    "laptop": (
        "Status", "Battery", "Why is my laptop slow?", "Check my internet",
        "Take a screenshot", "Volume up", "Volume down", "Brightness up", "Brightness down",
        "Show the clipboard history", "Token usage", "Scan qr code", "Read the text on the screen",
        "Notification status", "Share wifi", "/status", "/battery", "/screenshot",
        "/where", "/notifications", "/list",
    ),
    "fun": (
        "Hi", "How are you?", "What can you do?", "How is your day going?", "What are you doing?",
        "Calculate 15% of 2400", "Calculate 1250 * 12", "Flowchart: wake up, brush teeth, drink water, study",
        "Make a diagram of this project",
    ),
}
CITIES = ("Kathmandu", "Pokhara", "Nepalgunj", "Biratnagar", "Chitwan", "Butwal", "Dharan", "Lalitpur", "Janakpur",
          "Delhi", "Mumbai", "Tokyo", "London", "New York", "Dubai", "Sydney", "Bangkok", "Lhasa")
PICTURES = ("a misty Himalayan sunrise", "a red panda in a bamboo forest", "a cozy tea shop in Kathmandu", "Phewa lake at dawn",
            "a cyberpunk Thamel street at night", "a fox reading a book", "a snow leopard on a cliff", "Boudhanath stupa at sunset",
            "a robot making momo", "a paper boat on a rainy street", "a lighthouse in a storm", "a dragon over Pokhara",
            "a cat astronaut", "a mountain village in autumn", "a minimal logo of a fox", "a tiger in the rain",
            "a desk setup with plants", "the Milky Way over Annapurna", "a vintage train in the hills", "a floating island")
GENRES = ("lofi", "nepali", "old hindi", "relaxing piano", "jazz", "focus", "rain sounds", "classical", "bhajan", "ghazal",
          "chill hip hop", "arijit singh", "narayan gopal", "sufi", "acoustic guitar", "study")
NEWS = ("Nepal", "technology", "AI", "cricket", "football", "business", "science", "world")
WORDS = ("serendipity", "ephemeral", "ubiquitous", "resilient", "meticulous", "pragmatic", "eloquent", "candid", "diligent",
         "ambiguous", "inevitable", "nostalgia", "paradigm", "empathy", "lucid", "tenacious", "frugal", "benevolent",
         "verbose", "concise", "latency", "algorithm", "heuristic", "recursion", "abstraction", "idempotent")
MONEY_CATS = ("food", "groceries", "transport", "bills", "education", "clothes", "health", "shopping", "fun")
MONEY_TIMES = ("today", "this week", "this month", "this year", "in the last 7 days", "last month")


_CONTROLS = {"Pause", "Next song", "Music volume down", "Stop the music", "Pause the video", "Continue the video",
             "What song is this?"}  # only make sense while something plays


def _tidy() -> None:
    """Chips are plain sentences: no '/commands' (the '/' list has its own suggestions), no player controls."""
    for k, v in POOL.items():
        POOL[k] = tuple(x for x in v if not x.startswith("/") and x not in _CONTROLS)


def _grow() -> None:
    """Hundreds more from templates (every one still a 0-token fast-path phrase)."""
    extra = {
        "day": [f"Weather in {c}" for c in CITIES] + [f"What time is it in {c}?" for c in CITIES[9:]]
               + [f"Weather in {c} tomorrow" for c in CITIES[:8]],
        "media": [f"Generate an image of {p}" for p in PICTURES] + [f"Play {g} music" for g in GENRES]
                 + [f"Make 4 versions of {p}" for p in PICTURES[:6]] + [f"Make a short video about {t}" for t in
                                                                         ("Mount Everest", "Nepali tea", "black holes", "the monsoon", "Lumbini")],
        "web": [f"Latest news about {t}" for t in NEWS] + [f"What does {w} mean?" for w in WORDS]
               + [f"Meaning of {w}" for w in WORDS[:10]],
        "fun": [f"Calculate {e}" for e in ("15% of 2400", "1250 * 12", "2^10", "sqrt(144)", "45000 / 12", "18% of 5600",
                                             "(250 + 375) * 4", "99 * 99")],
        "money": [f"How much did I spend on {c} {t}?" for c in MONEY_CATS for t in MONEY_TIMES[:3]]
                 + [f"How much did I spend {t}?" for t in MONEY_TIMES],
    }
    for k, v in extra.items():
        POOL[k] = tuple(dict.fromkeys(POOL[k] + tuple(v)))


_grow()
_tidy()
_recent: deque[str] = deque(maxlen=40)  # not the same chips again for a while


def _coding_now() -> bool:
    """VS Code is the window in front, or the last messages were about code."""
    try:
        import subprocess
        title = subprocess.run(["xdotool", "getactivewindow", "getwindowname"], capture_output=True, text=True,
                               timeout=2).stdout
        if "Visual Studio Code" in title:
            return True
    except (OSError, Exception):
        pass
    try:
        from jarvis.core import store
        with store.connect() as c:
            rows = c.execute("SELECT text FROM messages WHERE role='user' ORDER BY id DESC LIMIT 8").fetchall()
        talk = " ".join(r[0] for r in rows).lower()
        return len(re.findall(r"\b(?:code|function|python|bug|error|test|vs code|class|script|git|port)\b", talk)) >= 3
    except Exception:
        return False


def _mine(now: datetime) -> list[str]:
    """A few made from my own data."""
    out = []
    try:
        from jarvis.core import habits
        for h in habits.overview(now):
            if not h["done"]:
                out.append(f"{h['name'][:1].upper()}{h['name'][1:]} done")
    except Exception:
        pass
    return out[:2]


def weights(now: datetime, coding: bool) -> dict[str, float]:
    h = now.hour
    w = {k: 1.0 for k in POOL}
    if coding:
        w["code"] = 4.0  # more coding, not only coding
    if 5 <= h < 11:
        w["day"] += 1.5
    elif 17 <= h < 23:
        w["money"] += 1.0
        w["habits"] += 1.0
        w["media"] += 0.5
    elif h >= 23 or h < 5:
        w["media"] += 1.0
    return w


def pick(n: int = 4, now: datetime | None = None, coding: bool | None = None, rng: random.Random | None = None) -> list[str]:
    """n different suggestions, weighted by context, not repeating the recent ones."""
    now = now or datetime.now()
    rng = rng or random.Random(time.time_ns())
    coding = _coding_now() if coding is None else coding
    w = weights(now, coding)
    out: list[str] = []
    mine = [x for x in _mine(now) if x not in _recent]
    if mine and rng.random() < 0.5:
        out.append(rng.choice(mine))
    cats = list(POOL)
    tries = 0
    while len(out) < n and tries < 200:
        tries += 1
        cat = rng.choices(cats, weights=[w[c] for c in cats])[0]
        s = rng.choice(POOL[cat])
        if s in out or s in _recent:
            continue
        if sum(1 for x in out if x in POOL[cat]) >= max(1, n // 2) and cat != "code":
            continue  # a mix: at most half from one group (coding may take more)
        out.append(s)
    _recent.extend(out)
    return out


def total() -> int:
    return sum(len(v) for v in POOL.values())
