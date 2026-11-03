# KURAMA learning and caching

How KURAMA remembers what you taught it, gets cheaper and more correct over time, and what you can say or press to
control it. Last updated 2026-11-03.

---

## 1. The idea in one minute

- KURAMA spends **tokens** (Groq free-tier budget) only when it asks the online AI. Everything else runs on your
  laptop for free (**0 tokens**).
- When the AI handles something well **and you say so**, KURAMA keeps that decision. Next time, a request with the
  same meaning runs straight away, without the AI.
- When a reply is bad **and you say so**, KURAMA throws away whatever produced it and won't answer that way again.
- **If you say nothing, nothing is learned.** You are always in control.
- KURAMA keeps **decisions**, never **results**. "What's my battery?" learned once still reads the battery live
  every time, so a learned shortcut can never give you an old answer.

---

## 2. Four kinds of memory

| Kind | What it keeps | How long | Example |
|---|---|---|---|
| **Learned shortcuts** | "this kind of sentence → this tool with these settings" | Until you remove it, it fails twice, or you complain | "tell me the wikipedia summary of X" → `wikipedia(topic=X)` |
| **Kept answers** | A plain AI answer you approved | 30 days | "why is the sky blue in one line" → the answer you liked |
| **Your words, names and rules** | What *you* said things mean | Forever, until you change them | "browser" = Brave; "good night" = lock the screen; "keep answers short" |
| **Result caches** | Fresh results of slow lookups | Minutes to hours | Weather for 10 min, song search for 12 h |

The first three are **learning**: they grow from what you tell KURAMA. The fourth is ordinary **caching**: it only
avoids repeating the same lookup within a short time.

---

## 3. What happens to every request, in order

```
Your message
   │
   ├─ 0. Your words: is the WHOLE message one of your phrases?  ("good night" → "lock the screen")
   │
   ├─ 1. Built-in shortcuts (time, open app, play song, volume …)        → 0 tokens
   ├─ 2. Meaning shortcuts (battery, date, git status, daily summary …)  → 0 tokens
   ├─ 3. LEARNED shortcuts and kept answers (from your 👍 / praise)      → 0 tokens
   │
   └─ 4. Nothing fits → the AI (Groq)                                    → costs tokens
         └─ your reply rules ("call me boss") are attached to the request
```

- Built-in shortcuts always come **before** learned ones. A learned shortcut can never take over something KURAMA
  already does correctly.
- The more you approve, the more requests stop at step 3 instead of step 4. That is how it gets cheaper day by day.

---

## 4. Everything you can do

### 4.1 Judge a reply

| You do | Meaning | What KURAMA does |
|---|---|---|
| Press **👍** under a reply | "Right tool, right answer" | Learns it as a shortcut, or keeps the answer |
| Say praise in your next message: "perfect, that's exactly what I wanted", "good job", "well done", "excellent", "ramro garyau", "bahut badhiya", "sahi kiya" | Same as 👍 | Same as 👍; replies "Happy to help!" for 0 tokens |
| Press **👎** under a reply | "Something was wrong" | Deletes what produced it and won't answer that way again; fills the box with "No, I meant " |
| Complain in your next message: "no, that's wrong", "not that", "galat", "hoina", "yo hoina", "you misunderstood me" | Same as 👎 | Same as 👎; your words are saved as the reason |
| Complain **and** say what to do: "no, play it in the music player", "you should use the music player for this" | "Wrong, do it like this" | 👎 the old reply; if the new attempt works, your **original** wording now means that tool, switched on at once |
| Nothing, or just "thanks" / "ok" / "next" | No verdict | **Nothing is learned** |

Notes:

- Praise and complaints count only within **2 minutes** of the reply they're about.
- Each channel judges only its own replies: a complaint on Telegram never affects the laptop's last reply.
- A complaint can be one part of a longer message: "that's wrong, anyway open YouTube" is a 👎 for the reply before
  it. "Open YouTube" is treated as a new task, not as the fix, so nothing wrong is learned from it.
- Spoken feedback counts only when speech recognition was **sure** of what it heard (section 9). Noise like
  "Okay, go on." never counts.
- If KURAMA asked you a question, a bare "no" is your answer to it, not a complaint.

### 4.2 Complain later

After the 2 minutes, a complaint still works **if it says what was wrong** (4 or more words):

> "Earlier you opened Firefox when I said open browser, that was wrong."

KURAMA looks through your replies from the last **3 days**. If one is clearly about that, it gets the 👎. If none is
clearly about it, nothing happens; KURAMA never guesses.

### 4.3 Teach your own words (kept forever)

| You say | What happens | Works where |
|---|---|---|
| "When I say **code**, open **VS Code**" | "code" means the VS Code app | Inside any sentence: "open code and youtube" |
| "If I say **browser**, open **Brave**, not Firefox" | "browser" means Brave | Inside any sentence |
| "When I say **good night**, lock the screen" | Saying just "good night" runs "lock the screen" | Only when it is your **whole** message |
| "Whenever I say **study time**, play lofi music" | "study time" → "play lofi music" | Whole message ("Study time, Kurama!" also works) |

- An app name needs the app to be **installed** and the name to be at most 3 words. Otherwise the words are kept
  for the whole command ("If I say music app, open Spotify" without Spotify installed → "music app" runs
  "open Spotify").
- **One meaning per word**: teaching the same word again replaces the old meaning.
- To change it, teach it again. To remove it, say "forget what good night means" (the AI works out which one).
- Without saying anything, "browser" already opens your **system's default browser** (Brave on this laptop).

### 4.4 Reply rules (how KURAMA should talk to you)

| You say | Saved rule |
|---|---|
| "From now on, keep your answers short" | keep your answers short |
| "Always reply to me in Nepali" | always reply to me in Nepali |
| "Never use emojis in your replies" | never use emojis in your replies |
| "Always call me boss" | always call me boss |

- Saved at **0 tokens**, **at most 6 rules** (the oldest is dropped, and KURAMA tells you so).
- A newer version of the same rule replaces the old one ("keep your answers very short" replaces "keep your answers
  short").
- The rules are attached to **every** AI request. Built-in and learned shortcuts don't use the AI, so they don't
  need them.
- **Not** saved as rules: "always open YouTube at 9" (a schedule), "never mind", "remind me every day at 7".
- **Remove one**: "forget the rule about calling me boss", "remove my rule to reply in Nepali" (0 tokens).
  **Remove all**: "clear all my rules".
- For 10 minutes after you remove a rule, KURAMA tells the AI it no longer applies. Without that, the AI kept
  copying it from its own recent replies.

### 4.5 Commands (type them; they cost 0 tokens)

| Command | What it shows / does |
|---|---|
| `/learned_shortcuts list` | Every learned shortcut and kept answer (numbered), plus your words, app names and rules |
| `/learned_shortcuts stats` | How many are on, tokens saved today and this week |
| `/learned_shortcuts forget 3` | Remove number 3 from the list |
| `/learned_shortcuts clear` | Remove all learned shortcuts and kept answers (your words and rules stay) |
| `/app_name list` | Your words, app names and reply rules |

`/learned_shortcuts` on its own only shows how to use it; add `list`.

---

## 5. How a learned shortcut is made

### 5.1 From a 👍 or praise

1. The AI handled your request with **one** tool, for example `wikipedia(topic="Mount Everest")` for "tell me the
   wikipedia summary of mount everest".
2. You pressed 👍 or praised it.
3. KURAMA checks the safety rules (section 6). If they pass, it saves the sentence, the tool and the settings.
4. **Changing words become slots.** Words of your sentence that also appear in a tool setting can change next time:

   ```
   saved sentence:  tell me the wikipedia summary of [mount everest]
   tool:            wikipedia(topic = [the slot])
   ─────────────────────────────────────────────────────────────────
   "tell me the wikipedia summary of kathmandu"  → wikipedia(topic="kathmandu")   0 tokens
   "tell me the wikipedia summary of pokhara"    → wikipedia(topic="pokhara")     0 tokens
   ```

   A slot can also be part of a longer setting: "play song **us mod se shuru kare**" with
   `query="us mod se shuru kare Hindi song"` makes "play song **kesariya**" → `query="kesariya Hindi song"`.
   Numbers work too: "set the brightness to **40** percent" → "…to **70** percent" → `level=70`.

5. **Settings with fixed choices never become slots.** In `action="play"`, "play" is one of the tool's fixed
   choices, so it stays "play" even though the word is in your sentence.
6. A saved sentence must keep at least one fixed word ("play", "summary", …). A sentence that is **only** the
   changing part (just a song title) matches only that same request again; it could never swallow everything else.

### 5.2 From a correction ("no, play it in the music player")

1. "bajau us mod se shurroo kare" → the AI searched the web (wrong).
2. You: "no, play it in the music player" → the AI played it in KURAMA's music player (right).
3. KURAMA checks the fix is **about the same thing**: its settings share words with your first request (the song
   title), or its tool's area is one of the two closest areas to that request by meaning.
4. If yes: your **first** wording now means the music player, switched on at once (you told it to). "bajau tum hi ho"
   then plays at 0 tokens.

### 5.3 Multi-step replies

A 👍 on a reply that did several tasks ("open youtube on my laptop and then play some lofi beats") keeps:

- **how the request was split** into tasks, so a similar request is split at 0 tokens next time (no planning call);
- **each step whose tool clearly did its task**: the tool's settings share words with that task and with no other.
  Here: "play some lofi beats" → music player, and "open youtube on my laptop" → open YouTube.

### 5.4 Kept answers

A 👍 or praise on a **plain** AI answer (no tool used) keeps that answer for **30 days**, but only if:

- the question has at least 3 words;
- it isn't about something that changes: today, now, latest, news, score, price, weather, tomorrow, yesterday,
  this week/month/year, aaja, aaj, abhi, ahile, kal, bholi;
- it doesn't point at the screen ("this", "that", …).

It is reused only for a **nearly identical** question (95% similar, no new important words). In voice mode only its
first two sentences are spoken.

---

## 6. What is NEVER learned (safety)

| Never | Why |
|---|---|
| Anything outside these areas: apps, audio, browser, display, desktop, file search, date/time, git (status/log), links, media, power (battery, lock), system checks, usage, weather, web, windows, knowledge search | No reminders, money, messages, file changes, jobs, coding, image making: those depend on more than the words |
| A tool that asks you yes/no (delete, shutdown, kill, install, run commands) | Those always need you |
| A request that points at the screen: this, that, these, those, it, here, there, selected, highlighted, current, same, previous, last, again (and yo, tyo, yaha, yeh, woh, isko, usko) | "Open this folder" means something different every time |
| A request that used more than one tool (except steps of a multi-step 👍, section 5.3) | Not one clear decision |
| A tool that failed ("error…", "I couldn't…", a question back to you, you said no) | It didn't work |
| A tool that was still running in the background, unless that job finished successfully | No proof it worked |
| A file path or file name setting as a slot | It may come from the screen, not your words |
| Requests longer than 160 characters, or without at least 2 meaningful words | Too vague or too specific |

---

## 7. How a learned shortcut runs at 0 tokens

1. **Meaning:** a small model on your laptop (fastembed, already loaded for routing) turns your sentence into
   numbers that represent its meaning. It takes about 10 ms and costs nothing.
2. **Compare:** those numbers are compared with every learned sentence.
3. **Match rules:**

   | Shortcut type | Must be | And |
   |---|---|---|
   | With slots | ≥ 60% similar in meaning | Your sentence fits the saved wording exactly, with the slot words changed |
   | Without slots | ≥ 92% similar | No new important word, and at most one word missing ("phone battery" ≠ "battery") |
   | Kept answer | ≥ 95% similar | No new important word, not about today/now, not older than 30 days |

4. **Run:** the tool runs directly with the filled-in settings. The reply is worded the same way as when the AI
   uses that tool.
5. **Count:** each successful use adds the tokens the AI had cost to "saved today" (`/learned_shortcuts stats`).

---

## 8. When a learned shortcut stops

| Event | Result |
|---|---|
| 👎 on a reply it gave | Deleted; that kind of request goes back to the AI |
| A complaint about a reply it gave (now or later) | Deleted |
| Its tool fails | That request goes to the AI instead (you get an answer, not an error) |
| Its tool fails **2 times in a row** | Switched off; `/learned_shortcuts list` shows "off: its tool failed 2 times in a row" |
| `/learned_shortcuts forget N` or `clear` | Deleted |
| More than 400 saved | The least used ones go first (switched-off before working ones) |

A 👎 on a **built-in** shortcut also stops it: that wording goes to the AI from then on. The block is stored in
`data/learned.json`, and very similar wordings (≥ 92%) are blocked too.

---

## 9. Spoken feedback and misheard speech

Speech-to-text sometimes turns noise into words. From the speech log (`data/logs/stt.log`):

| Heard | Confidence | Real? |
|---|---|---|
| "Okay, go on." | −0.89 | No, it came from noise |
| "Maximal Zabolom" | −0.68 | No |
| Normal speech | about −0.1 to −0.5 | Yes |

Spoken praise or complaints count only when confidence is **−0.60 or better** and the language heard was English,
Nepali or Hindi. Typed messages always count.

---

## 10. Result caches (short-term, automatic)

These are not learning. They just avoid doing the same slow lookup twice in a row.

| What | Kept for | Setting |
|---|---|---|
| Weather results | 10 min | `WEATHER_CACHE_S = 600` |
| Place lookups (city → coordinates) | 1 day | `GEO_CACHE_S = 86400` |
| Web search and Wikipedia results | 10 min | `WEB_CACHE_S = 600` |
| Song search results (music player) | 12 h | `music.CACHE_S` |
| Groq prompt cache | Groq's side | Only **measured**: `llm_calls.cached_tokens` and the trace report |

**Groq prompt cache:** Groq can reuse the start of a request when it is identical to a recent one. KURAMA records
how many input tokens were reused, so you can see whether it happens. KURAMA doesn't control it yet. If the report
keeps showing 0, the next step is to make the start of each AI request identical every time.

---

## 11. Watching it improve

| Where | What you see |
|---|---|
| `/learned_shortcuts stats` | Shortcuts on, kept answers, switched off, tokens saved today and this week |
| `/learned_shortcuts list` | Each learned item: its sentence, tool and settings, slots, on/off, times used, plus your words and rules |
| `venv/bin/python scripts/trace_report.py --days 3` | Section "Your feedback": every 👎 first (with your words as the reason), the learned-shortcut savings, and Groq prompt-cache reuse |
| The 👍 / 👎 chips | Under every reply in the laptop chat |

A good routine (see MONITORING.md): every 2–3 days, read the 👎 list in the report. Each line is a reply you said
was wrong, and that's where fixes should start.

---

## 12. Where the data is

| File | Holds | Safe to delete? |
|---|---|---|
| `data/recipes.json` | Learned shortcuts and kept answers | Yes (= `/learned_shortcuts clear`) |
| `data/app_names.json` | App names ("browser" → brave-browser) | Yes (you lose your app names) |
| `data/my_words.json` | Your phrases ("good night" → "lock the screen") | Yes (you lose your phrases) |
| `data/style.json` | Your reply rules | Yes (you lose your rules) |
| `data/learned.json` + `learned.npy` | Routing memory: which area a wording belongs to, and which shortcuts a correction blocked | Yes (routing starts fresh) |
| `data/learned_plans.json` | How approved multi-step requests were split | Yes |
| `data/traces.db`, table `feedback` | Every 👍 / 👎 / spoken verdict with your words | Keep it: it's the improvement record |
| `data/jarvis.db`, table `llm_calls`, column `cached_tokens` | Groq prompt-cache reuse per AI call | Keep it |

None of this leaves your laptop.

---

## 13. Settings (`jarvis/core/config.py`, or `.env` for those with a variable)

| Setting | Default | Meaning |
|---|---|---|
| `KURAMA_RECIPES` | on | Learned shortcuts on/off |
| `KURAMA_ANSWER_CACHE` | on | Kept answers on/off |
| `KURAMA_LEARN` | on | All learning on/off |
| `KURAMA_LEARN_SILENT` | **off** | On = the old "learn from silence" (not wanted) |
| `RECIPE_GROUPS` | see section 6 | Areas that may be learned |
| `RECIPE_SIM` / `RECIPE_SLOT_SIM` | 0.92 / 0.60 | Match strictness without / with slots |
| `RECIPE_MAX` / `RECIPE_MAX_FAILS` | 400 / 2 | Most kept; failures in a row before switching off |
| `ANSWER_CACHE_SIM` / `ANSWER_CACHE_DAYS` | 0.95 / 30 | Kept-answer strictness and age |
| `LEARN_WINDOW_S` | 120 | Seconds after a reply in which praise / complaints count |
| `LEARN_CORRECTION_SIM` / `LEARN_PRAISE_SIM` | 0.80 / 0.80 | How clearly a message must be a complaint / praise |
| `LEARN_LATE_DAYS` / `LEARN_LATE_SIM` / `LEARN_LATE_MARGIN` | 3 / 0.72 / 0.05 | Late complaints: how far back, how close, how clear |
| `FEEDBACK_MIN_LOGPROB` | −0.60 | Speech confidence needed for spoken feedback |
| `STYLE_MAX` / `STYLE_MAX_CHARS` / `STYLE_MIN` | 6 / 320 / 0.80 | Reply rules: count, total size, how clearly a message must be a rule |

---

## 14. Removing the 👍 / 👎 buttons later

After your 1–2 months of testing, delete this one line in `frontend/app.js` (in `BotBubble.done`):

```js
if (ev.trace && this.text) this.meta.append(rateButtons(ev.trace));
```

Everything else keeps working: spoken praise and complaints, corrections, late complaints, your words and rules,
and every shortcut already learned. The feedback API (`POST /api/v1/feedback`) can stay.

---

## 15. Questions

**I pressed 👍 but nothing was learned.** The reply probably broke a safety rule (section 6): two tools, a "this" in
the request, an area that's never learned, or a tool that failed. A plain answer about "today" or news is never
kept either. 👍 is still saved in the feedback record.

**A learned shortcut does the wrong thing.** Press 👎 or say "no, that's wrong", and it's deleted. Or use
`/learned_shortcuts list` and `forget N`.

**I want KURAMA to do X whenever I say Y.** "When I say Y, X." For an app: "when I say Y, open <app>".

**Does a learned shortcut ever give an old answer?** No. Only the decision is kept; the tool runs live every time.
Kept answers are plain explanations you approved, never anything about today, and they expire after 30 days.

**Does it learn from Telegram too?** Spoken or typed praise and complaints, yes, judged only against Telegram's own
replies. The 👍 / 👎 buttons exist only in the laptop chat.

**How do I start over?** `/learned_shortcuts clear` removes learned shortcuts and kept answers. "Clear all my
rules" removes the rules. Your words and app names stay until you forget them one by one, or delete
`data/my_words.json` / `data/app_names.json`.

---

## 16. Code map

| File | Does |
|---|---|
| `jarvis/core/recipes.py` | Learned shortcuts, kept answers, 👍 / 👎, late complaints, multi-step 👍, failure switch-off, stats |
| `jarvis/core/learn.py` | Judges each reply from your next message (complaint / praise, per channel, clear speech only); routing memory |
| `jarvis/core/mywords.py` | Your phrases for whole commands |
| `jarvis/tools/general/_apps.py` | App names, the default browser |
| `jarvis/core/style.py` | Reply rules |
| `jarvis/tools/general/app_name.py` | The tool that saves / forgets / lists words, app names and rules |
| `jarvis/tools/general/learned_shortcuts.py` | `/learned_shortcuts` |
| `jarvis/core/fastpath.py` | Order of checks (section 3); "when I say…", rule and forget-rule shortcuts; failure reporting |
| `jarvis/core/stt.py` | `heard_well`: speech confidence for spoken feedback |
| `jarvis/core/trace.py` | Feedback table, trace lookups |
| `frontend/app.js` | The 👍 / 👎 buttons (`rateButtons`) |
| `tests/test_recipes.py`, `tests/test_learning_gaps.py`, `tests/test_learn.py` | Tests for all of the above |
