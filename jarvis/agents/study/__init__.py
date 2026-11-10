"""Study mode (plan 11-09 phase 6; phase 7 makes it the best at reading and writing). While on: your answers are
short, plain and exam-minded (one example each), about what you are reading; its own chat window in KURAMA.
Everything else (volume, music, open YouTube, Telegram) still works at 0 tokens. Off: "back to normal", /normal,
or AGENT_IDLE_OFF_S without use. It brings no tool groups of its own yet (the study / selection tools stay
routed as usual), so turning it on costs no RAM.
"""
from __future__ import annotations

from jarvis.agents import AgentSpec

SPEC = AgentSpec(
    name="study", title="Study mode", groups=(),
    prompt=("Study mode ON: the user is a CSIT student studying (exam soon; AI/ML). Answer like a good tutor: plain "
            "words, short (3-6 lines), one small example, the key term in bold; about the selected text / page when "
            "there is one. Offer 'more' for the long version. Nepali or Hindi when asked."),
    aliases=("study", "studying", "learn", "learning", "reading", "read"),
    welcome=lambda: ("Study mode on. Select text anywhere and ask: 'explain this', 'simpler', 'in nepali', "
                     "'summarize this page', 'quiz me'. Say 'back to normal' to leave."),
)
