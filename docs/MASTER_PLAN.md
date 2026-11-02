# KURAMA master plan (2026-11-02): trace-report fixes + lanes from Version_4, in one order

Inputs: the trace report of 11-02 (281 requests, 11-01 07:48 -> 11-02 07:52; problems P1-P10 below, with trace ids)
and the review of the old KURAMA Version_4 (/media/leo/Project1/Project/Gen_AI/Big_project/02_K.U.R.A.M.A/Version_4).
Owner's rule for Version_4: don't copy it; take its advantages and make them better for this system.

Work rules: one phase at a time, stop after each for the owner to test. Prove the cause, then one general fix per
class, by meaning (no new word rules). Each phase: tests with 3+ real phrasings, the full suite + scorecard once
(>= 65% instant / 100% right / 98% router), one live check, idle RSS measured (< 600 MB), PROGRESS.md + MONITORING.md
Fix history, commit + push (branch linux). Never commit COMMAND.md or jarvis/core/diagram.py.

Baseline to beat (11-02 report): 57% of requests at 0 tokens, 2,038 tokens per AI request, 80k tokens/day.

## The problems (11-02 trace report)
| # | Class | Proof | Proven cause |
|---|---|---|---|
| P1 | Gemini fallback fails / wastes calls | 73a5f773, 99ccd1f4, f9eec047, a8ae2840, 51ff16b4 | agent.py:533 rebuilds the AI message and drops Gemini's thought_signature (400 on every call after a tool); a used-up Gemini quota (429, no Retry-After) is retried, then skipped only 120 s; the voice chain has no flash-lite |
| P2 | "That's taking a while" for 3-8 s actions | e44b388b, aed4356f, b11a0269, 22e7ed2c, de45a456; jobs #23, #45-47 | one fixed TOOL_BACKGROUND_AFTER_S = 3 for every tool |
| P3 | Garbled / misheard speech goes to the AI | stt.log 246-290; d45d01b9, fa375151, 68fa2b41, 51ff16b4 | stt.not_ours keeps forced-pass text down to -1.0 (real speech scores -0.62..-0.93): confidence alone can't separate; misheard command words ("Open sitting", "Upon SofaScore", "Nepal guns") |
| P4 | Wrong folder / file opened | 1c3814a8, c4a1679c, 4499672c, 5712fe4c, 7d83160e | the closest fuzzy name wins even when weak or tied; shortcut patterns swallow "from this", "to telegram in a .py" into the name |
| P5 | Small talk costs tokens | ba46a065 vs 6bfd16d9, d70762b1, a11bc93f, 595cc3e2, 2c38a6f7 | templates.small_talk gives up when the sentence splits into parts; no Roman Hindi / Nepali examples |
| P6 | "here" weather = France; unknown place -> web search | 73a5f773, 99ccd1f4 | weather.py treats only an EMPTY place as home; no nearest-known-place step |
| P7 | Fake "done" with no tool | c6123814 | meta.claims is a word pattern; misses "Here is X in your workspace" |
| P8 | "remove second" hits the wrong list | d31dfcbc | an ordinal goes to the to-do list by words, not to KURAMA's last numbered list |
| P9 | "make an image and send it to Telegram" not split | 04e9edfd (7,897 tok), 54045016 | planner.is_multi says no; the AI does both steps |
| P10 | Window: open-file leak, freezes, not restarted | wallpaper.log 07:54 "Too many open files"; hang.log 08:52 dump | leak source unproven (no "open files" line yet: no voice use since the guard); freeze inside GTK/WebKit C code; the 08:39/08:44 windows were not started through kurama-wallpaper.sh's restart loop |
| P11 | AI requests that should be 0 tokens | a80bd5a9, 664db124, 38e3b5a3, 04e60f8a, 3f7463ad | missing meaning actions: volume to N (also > 100), "more volume", close all tabs, list tabs, key combos |

## What we take from Version_4, made better
| Version_4 | KURAMA |
|---|---|
| A lane per task (general / search / create / auto), picked by an AI call every request | Lane by meaning (fastembed, 0 tokens) + learned corrections; the 8b classifier only when unclear |
| One simple executor per lane | Same, plus a contract per lane checked in code (below) |
| Tools found by meaning over one-line descriptions (FAISS, torch) | Tool index over real phrasings (scorecard cases, traces, corrections), the most-used tools always offered; same fastembed model, SQLite |
| An "is anything missing?" AI call before every request | Ask only when a tool can't decide (no match, two matches, no place): numbered choice, 0 tokens |
| A final-answer AI call always | The tool's own sentence; one short call only to combine several results |
Not taken: torch (HuggingFaceEmbeddings), MCP servers over npx, input() blocking, 3-6 AI calls per request.

Lane contracts:
- **general** (owner, 11-02: must answer very quickly): a known greeting = 0-token template; anything else general
  ("namaste, k xa?", "how is your day", "what is gravity") = exactly ONE call to the small model that labels and
  answers at once. No planner / router-classifier / summary call before it, no tool schemas, a short prompt, small
  max_tokens, the first sentence streamed to speech at once. Target: first word in under 1 s. If the meaning lane is
  unsure, that same one call either answers (general) or returns only a lane label (search / create / auto) and
  the request moves on: no extra call when it really was general. May never claim an action. Means nothing
  (garbled speech) -> "Sorry, say that again?" at 0 tokens.
- **search**: the live-search / weather / news tool runs directly; the AI only shortens a long result.
- **create**: always the Long Job Engine (data/outputs/, announced when done).
- **auto**: the agent with tools picked by meaning; it must call a tool or say what failed.

## Phases
**Phase 0 - Stable fallbacks (P1, P10 evidence).** No architecture change.
- Keep the model's own AI message (signature kept) when its tool calls are re-labelled.
- A 429 that says the quota is used up: no retry, skipped until the quota resets (Google's retryDelay / the
  message); flash-lite joins the voice chain. A 401 says "the AI key is wrong" instead of a raw error.
- The window always starts through the restart loop (power script, autostart, manual start).
- Owner uses hold-to-talk ~10 min; read the hang.log "open files" line -> the leak's file kind (fix in Phase 5).
- Done when: no "thought_signature" errors and at most one call per used-up model per reset, in traces.

**Phase 1 - Lanes by meaning (P3, P5).**
- config.LANE_EXAMPLES (general / search / create / auto / unclear) + learned corrections; the planner puts
  `lane` on every task; traces and the report show it. The lane REPLACES the part of routing it decides.
- unclear + foreign-labelled low-confidence speech -> 0-token "say that again" (P3).
- Small talk: the whole request counts when every part is small talk; Roman Hindi / Nepali examples (P5).
- General fast lane: one small-model call that labels and answers (contract above); time to first word logged
  in traces (target < 1 s; today's general replies took 0.5-2.8 s in total).
- Done when: scorecard holds; every trace has a lane; 3+ real phrasings per lane in tests/eval/cases.jsonl.

**Phase 2 - One executor per lane (P2, P7, P9).**
- general without tools (token cut measured); search runs its tool directly; create always a job; auto = agent.
- Contracts in code: a general / failed answer can't claim an action (P7, by meaning, not a word pattern).
- Each tool waits as long as its own past runs need (learned from traces, capped ~10 s) before going to the
  background (P2, for every tool, not only search).
- A request with several tasks gets one lane each: "make an image and send it to Telegram" = create -> auto with
  depends_on, 0 tokens when each step has a shortcut (P9).
- Done when: tokens per AI request below the 2,038 baseline; no tool-less "done" in a week of traces.

**Phase 3 - Tool index for the auto lane (P11).**
- Each tool indexed by real phrasings, not only its description; the most-used tools always offered.
- The 0-token candidates become meaning actions: volume to N (also > 100), "more volume", close all tabs, list tabs,
  key combos.
- Done when: router score holds (>= 98%), instant share up from 57%.

**Phase 4 - Resolve names, ask only when needed (P4, P6, P8, P3 mishearings).**
- Name -> path only when clearly the best and all its words fit; else a numbered choice or "not found: create it?".
- "this / that / here" go to the thing in use (Files, VS Code, home place), never into a name (P4, P6).
- An ordinal ("second", "2") picks from KURAMA's last numbered list of any kind (P8).
- Unknown words in a request are matched to KURAMA's own names by sound (apps, places, folders, command words):
  "Nepal guns" -> Nepalgunj, "sitting" -> Settings; replaces adding each mishearing to STT_FIXES.
- Done when: the P4 / P6 / P8 phrasings pass; no wrong open in the next report.

**Phase 5 - Window stability (P10).** Only with evidence: fix the leaking file kind found in Phase 0; for the GTK
freeze, log what the main loop was doing just before (last event / call), since its stack is in C code.

**After:** trace report round 3 (MONITORING.md), then the open items in docs/HANDOFF.md (Night Shift steps 2-3,
coding agent merge, offline /commands).
