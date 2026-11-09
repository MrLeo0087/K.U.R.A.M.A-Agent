# KURAMA plan 2026-11-09: fix what breaks daily use, then split KURAMA into a core + agents

Inputs: the trace report 11-03 → 11-09 (771 requests, 316 used the AI, 916k tokens = 131k/day; 👍 50 · 👎 67;
30 corrections), data/logs/stt.log, ptt.log, the audio devices, the code. The owner's notes of 11-09.
Work rules stay: prove the cause first, one general fix per class, tests, full suite + scorecard once, commit,
stop for the owner after each phase.

## A. Broken now: prove, then fix (each one a small step)

| # | Problem | Evidence so far | Cause | Fix |
|---|---|---|---|---|
| A1 | Hold Alt / talk mode: "I didn't catch that" | stt.log 11-09: 10 of 25 recognitions empty or a Whisper silence phrase ("ありがとうございました", "Press Alt to") from 09:13 on; 09:00-09:08 were fine. A 2.7 s hold sent 86 KB (the recording arrives). The internal mic gives signal (3 s: peak 4127) and the page's stream reads it at 100%; the mic itself is at 47% (KURAMA set 70% before) | Not proven: the recorded audio's level is not logged anywhere | 1) Log each recording's peak / loudness in stt.log and keep the last 5 failed WAVs. 2) One test hold with the owner. 3) Fix what it shows (mic gain, browser auto-gain on, or the source). A recording that is silence says "your mic is too quiet / muted" instead of "didn't catch" |
| A2 | "Use the top voice model" | Every 11-09 line already says `large-v3` (most accurate Groq Whisper, first since 11-07); turbo only on failure | Already the best free model; the failures are A1 (silence in), not the model | Nothing to swap. Keep large-v3; add the owner's words to its prompt |
| A3 | Alt command + reply not in the chat window | Hold-to-talk runs in the hidden ("ghost") mini page | To check: the ghost turn is not written to the chat history both windows show | Every hold-to-talk turn (question + reply) lands in the chat of the main and mini window |
| A4 | Music card: progress bar stuck, buttons do nothing | `/api/v1/music/state` + `/music/control` feed the card | To check live while a song plays (does position move? does control return an error?) | Fix the one that fails; test with a fake player |
| A5 | Phone: no notification, or no sound, when Claude Code finishes | Since 11-06 alerts are filed into the Telegram group's topics (tgtopics); phone sound for a group / topic follows the group's notification setting, the private chat rings | Group topics are muted or silent on the phone (to confirm on the phone) | Important alerts (Claude Code finished / waiting / asks, reminders, laptop guard) go to the private chat with sound, a silent copy in the topic |
| A6 | Claude Code "finished" while it only waits for a background task (video render) | claudewatch turns every `Stop` into "✅ finished" | A Stop with a background task still running is a pause, not the end | On Stop, look in the transcript for background tasks started and not yet reported: "⏳ Claude Code is waiting for <task>"; "✅ finished" only on a Stop with nothing running |
| A7 | Trace classes still open | 👎: closing several tabs (7), "search on Google for <selected word>" went to file search / wrong text (6), "send morning brief" sent the words, "set 2000 budget" → "tool 'expenses' not available" (the area wasn't routed), "open vs code" did not open (11-04, check if still true) | Per class, from the traces | Fixed by class in phase A, or by the split below (selection questions move to the study agent) |

## B. The new shape: KURAMA core + agents

Today one agent sees all 151 tools (through 17 general tools) and decides everything; the same selection
features exist in general mode AND coding mode (explain / improve / replace the selection). That is why it
mixes things up and why selection answers are weak. The new shape:

```
               ┌──────────── KURAMA core (always on, cheap) ────────────┐
 you ─ voice / │ time, date, apps, windows, volume, brightness, music,   │
 chat /        │ files + sharing, Telegram, reminders, notes, links,     │
 Telegram ────▶│ money, laptop health, Claude Code link, /commands       │
               └───────┬───────────────────────────┬────────────────────┘
                       │ hand-off (by meaning,      │
                       │ /code, /study, hotkey)     │
            ┌──────────▼─────────┐       ┌─────────▼──────────┐
            │ Coding agent       │       │ Study agent (new)  │
            │ coder/ (exists)    │       │ study/             │
            │ VS Code panel      │       │ reading + writing  │
            └────────────────────┘       └────────────────────┘
```

- **Core** keeps only quick laptop / phone tasks (about 60 tools behind ~10 general tools; fewer schemas per
  request = fewer tokens and fewer wrong picks). No code editing, no explaining text: those belong to agents.
- **One agent at a time decides.** Which one: an explicit switch (/code, /study, the mode button, the VS Code
  panel = code) > what is selected and where (selected code in VS Code = code, selected text anywhere else =
  study) > meaning of the request (the lanes of 11-02, extended with code / study). A switched-on agent stays
  until you leave it ("back to normal", /kurama) or 10 min idle; core commands (volume, open YouTube, time) still
  work inside any agent at 0 tokens.
- **Each agent = its own folder, prompt, tools, memory and chat thread**, sharing keys, models, the Groq rate
  limiter, your profile, Telegram and voice. Off = 0 RAM (started on use).
- **Removed duplicates:** general mode loses selection explain / improve / replace / complete (code → coding
  agent, text → study agent); "fix it" after an error → coding agent only.

## C. Study agent (new): understands the page you are reading

Why selection answers are weak today (traces): 46 text-assist requests answered from the selected words only,
on the fast small model (169-450 tokens: 'meaning of this word' with no page around it), so "what does this
mean" in the uv docs has no idea it is about Python packaging. Gemini did better because you pasted the whole
paragraph and it answered at length.

**How it works**
1. **Where am I?** When the agent opens (or the page changes): the app and window (browser tab URL + title via
   the KURAMA browser extension, VS Code file, PDF reader, other window by OCR). The page text is read once and
   summarized once ("uv docs → Installing Python versions; uv = a Python package and project manager"), cached
   per page: later questions cost no summary.
2. **What did you select?** The selection + the paragraph around it (±1,500 characters, from the extension; OCR
   of the window for apps without it).
3. **The answer:** one call to the strongest free model for long answers (gpt-oss-120b; Gemini 2.5 Flash when
   Groq is used up) with: page summary + section heading + the paragraph + your selection + your level and the
   task. Answer shape per task: meaning in THIS context, plain-words explanation, a small example (for code
   docs: a command / snippet you can run), how it connects to what the page is about. Voice says the first two
   sentences; the full answer is in the study panel.
4. **Tasks:** explain / meaning in context / summarize the section or page / "explain like I'm new" / write a
   paragraph or essay / revise my essay (changes shown, replace with a yes) / translate / quiz me / make notes
   + flashcards (saved to study notes, offline) / follow-up questions in the same thread ("and what about
   uv pip?").
5. **Memory:** one thread per document (URL / file), kept a week: come back tomorrow and it still knows the
   page and what you asked.
6. **Where you use it:** /study, the mode button in the mini chat (its own chat, like the coder), Telegram
   /study, and hold Alt while text is selected.

**Cost:** page summary once per page (~1.5k tokens), each question ~2-4k tokens in on the smart model. Built
in 3 steps: context (where am I + selection + paragraph, 0 tokens, tested on saved pages) → answers + panel +
voice → writing tasks (essay, revise, notes, quiz) + memory per document.

## D. Coding agent: measured, then fixed

Traces (7 days): 45 coding requests, 67.7k tokens; 6 over 5k (the rock-paper-scissors build 18k tokens / 98 s
/ 24 calls; "upgrade the calculator" 37.6k tokens / 39 calls in general mode before the split); one "fix it"
failed with every model; "I can't tell which file this error comes from". Step: run coder/evals on the owner's
real requests, list the failures by class (wrong file, loops, too many tokens, unfinished builds), fix by
class. Coding requests in general mode go to the agent (part of B).

## Order (one phase at a time, stop after each for you to test)

1. **A1 mic** (log + one test hold + fix) and **A3** chat window. Voice is the main way you use KURAMA.
2. **A5 + A6** Telegram notifications and Claude Code waiting vs finished.
3. **A4** music card + the **A7** trace classes.
4. **B** core + agent switch (selection duplicates removed; scorecard must hold).
5. **C** study agent, 3 steps.
6. **D** coding agent from its evals.
