"""The owner's real sentences (traces 11-06 / 11-07) and where each must go. 0 tokens: only the local meaning
model and the rules run. A wrong route here was a real bug once; this list keeps it from coming back."""
from __future__ import annotations

# (sentence, the coding agent is on, what must happen: an action of the `coding` tool, or None = not the agent's)
CODING_MODE = [
    ("Okay, the project looks fine but the UI is not good. UI is very flat and only white color use. Can you make UI "
     "little better", "project"),                                   # 22:03 said "couldn't take a picture"
    ("make the Reserve a Table button text white so it is readable", "project"),  # cost ~6k through the AI
    ("move the score board to the right", "project"),
    ("add a dark mode to this project", "project"),
    ("run this project and tell me what it prints", "run_task"),
    ("what did you do", "log"),
    ("learn this project", "learn"),
    ("write tests for this project", "tests"),
    ("show me what you changed", "diffs"),
    ("explain the selected code", None),                            # the editing assistant's, not the agent's
    ("what is the capital of nepal", None),
    ("open youtube", None),
    ("update code", None),                                          # too vague (it once ran UNDO)
]
