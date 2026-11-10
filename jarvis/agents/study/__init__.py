"""Study mode (plan 11-09 phase 6; phase 7 makes it the best at reading and writing). While on: your answers are
short, plain and exam-minded (one example each), about what you are reading; its own chat window in KURAMA.
Everything else (volume, music, open YouTube, Telegram) still works at 0 tokens. Off: "back to normal", /normal,
or AGENT_IDLE_OFF_S without use. Its one tool (study, group study_mode) answers about the highlighted text in its page's
context (core/studymode.py); requests are understood by meaning (EXAMPLES, 0 tokens).
"""
from __future__ import annotations

from jarvis.agents import AgentSpec

EXAMPLES: dict[str, tuple[str, ...]] = {
    "explain": ("explain this", "explain the selected text", "what is this about", "help me understand this",
                "explain this paragraph", "i don't understand this part"),
    "meaning": ("what does this mean", "what does this word mean here", "meaning of this", "define this term",
                "what is the meaning of this sentence"),
    "simpler": ("simpler", "explain it simpler", "make it easier", "i still don't get it", "explain like i'm a beginner"),
    "nepali": ("explain in nepali", "nepali ma bujhau", "in nepali", "tell me this in nepali"),
    "hindi": ("explain in hindi", "hindi mein samjhao", "in hindi"),
    "summary": ("summarize this", "summarize this section", "short summary of this part", "key points of this"),
    "page_summary": ("summarize this page", "what is this page about", "summary of the whole page",
                     "give me the main points of this article"),
    "quiz": ("quiz me", "quiz me on this", "test me on this page", "ask me questions about this"),
    "more": ("more", "tell me more", "explain in detail", "give me the long version", "more detail"),
    "translate": ("translate this", "translate this to english", "what does this say in english"),
    "write": ("write a paragraph about this", "write a short essay from this page", "write notes on this topic"),
    "notes": ("show my study notes", "my notes today", "what did i study today"),
    "glossary": ("show my glossary", "words i asked about", "my glossary"),
}

SPEC = AgentSpec(
    name="study", title="Study mode", groups=("study_mode",), examples=EXAMPLES,
    prompt=("Study mode ON: the user is a CSIT student studying (exam soon; AI/ML). Answer like a good tutor: plain "
            "words, short (3-6 lines), one small example, the key term in bold. For anything about the highlighted "
            "text or the page, use the tool `study` (it has the page's context)."),
    aliases=("study", "studying", "learn", "learning", "reading", "read"),
    welcome=lambda: ("Study mode on. Select text anywhere and ask: 'explain this', 'simpler', 'in nepali', "
                     "'summarize this page', 'quiz me'. Say 'back to normal' to leave."),
)
