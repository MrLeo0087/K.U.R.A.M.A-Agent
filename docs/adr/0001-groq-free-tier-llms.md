# 0001: Groq free tier for all LLM work

**Status:** Accepted (models updated 2026-10 when Groq retired Llama; Gemini fallback approved 2026-11-01)

**Context.** The laptop has no GPU and 8 GB RAM, so local models are too slow and too big. The project must cost nothing.

**Decision.** All LLM and speech-to-text calls go to Groq's free tier: a fast tier (gpt-oss-20b) for chat and
routing, a smart tier (gpt-oss-120b) only for reasoning and multi-tool work, qwen for voice and vision, Whisper for
STT. Gemini's free tier is the fallback after the gpt-oss models. Model IDs live only in `config.py`.

**Consequences.** + Fast, free, no local RAM. - Limited to about 8k tokens a minute per model, so every design
choice saves tokens (fast path, tool-group routing, short prompts, a shared rate limiter in `budget.py`). - Needs
the internet; edge-tts/piper cover speech offline.
