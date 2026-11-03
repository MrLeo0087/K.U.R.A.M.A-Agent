# KURAMA learning and caching

How KURAMA remembers what you taught it, gets cheaper and more correct over time, and what you can say or press to
control it. Last updated 2026-11-03.

---

> **New here?** Read section 1 (the idea), then **section 18: what to do every day / week to make KURAMA better**.

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

## 16. Small mistakes in learning that were fixed (2026-11-03), with examples

Each one could have made KURAMA learn the wrong thing. They are fixed, and each has a test.

**1. Answering "no" to KURAMA's question was treated as a complaint.**

> KURAMA: "Here is your poem. Do you want more?"
> You: "no"

Before: KURAMA thought "no" meant "your reply was wrong" and gave the poem a 👎.
Now: a plain yes / no / "no thanks" is your **answer to the question**, never a verdict on the reply.
To complain, say more than one word: "no, that's wrong".

**2. Two quick messages could be checked in the wrong order.**

> KURAMA plays a song → you quickly say "perfect".

Before: each message was checked in its own background thread. Sometimes "perfect" was checked *before* KURAMA had
registered the song, so the praise landed on the reply **before** the song.
Now: messages are checked one by one, in the order they happened.

**3. Background noise could change how sure KURAMA was about your words.**

KURAMA's wake-word listener also turns room sound into text, all day. Each time, it overwrote the "how sure was the
speech recognition" record.

> You say "perfect, that's exactly what I wanted" clearly → a second later the TV says something unclear.

Before: KURAMA judged your clear "perfect" by the TV's unclear score and could ignore it.
Now: every phrase keeps its own score.

**4. An old complaint could block a shortcut that works.**

> Morning: "open browser" opened Firefox (a bug that was fixed that afternoon).
> Evening: "earlier you opened Firefox when I said open browser, that was wrong."

Before: KURAMA blocked its built-in "open browser" shortcut forever, so every "open browser" afterwards went to the
AI and cost tokens.
Now: a late complaint records the 👎 and removes any learned shortcut that caused it, but never blocks a
built-in one: the problem may already be fixed.

**5. 👍 then 👎 on the same reply kept the 👍.**

> You press 👍 on a reply, then realise it was wrong and press 👎.

Before: the 👎 removed the learned shortcut, but the 👍's note ("this request belongs to this area") stayed.
Now: the 👎 removes that too. You changed your mind, so all of it goes.

**6. The same answer could be stored twice.**

> You press 👍 on an answer and also say "perfect, thanks".

Before: the kept answer was saved twice.
Now: once.

**7. "When I say yes, …" would have hijacked every "yes".**

> "When I say yes, open YouTube."

Before: this would be saved, and from then on every "yes" you say to KURAMA's questions ("Shall I delete it?" →
"yes") would open YouTube instead.
Now: words that answer questions (yes, no, ok, okay, sure, stop, cancel, next, back, done, thanks, haan, ho,
hoina, na, nahi, huncha, hunna, thik cha) can't be your words. KURAMA asks you to pick other words.

**8. A normal new request was taken as a complaint.**

> You: "Open web WhatsApp" → KURAMA opens it.
> You: "Save this link as a WhatsApp."

Before: one of KURAMA's example complaints was "I said save the link". "Save this link as a WhatsApp" sounded close
to it, so KURAMA thought you were correcting the "open" and blocked its "open" shortcut for wordings like
"open web WhatsApp". From then on those went to the AI and cost tokens.
Now: the example is "**no**, I said save the link" (a complaint starts with a no), and "save this link as …" is
listed as a normal request. The wrong block was removed.

**About the scorecard number.** The scorecard (`venv/bin/python -m tests.eval.harness`) used to read what KURAMA had
learned from your real use, so one live 👍 or one wrong "complaint" could move it. Now it starts with an empty
learning folder every time and measures **only the code**. Its "instant" number is 72% on that basis. Your real
KURAMA does a little better, because it also uses what you taught it.

---

## 17. Sound: why it was quieter with KURAMA, and what changed

### The short answer

Your **Bluetooth speaker (U-2500BT) was on, but KURAMA was sending all sound to the laptop's small built-in
speaker.** When you turned KURAMA off, the sound went back to the Bluetooth speaker, so it was loud again. The
built-in speaker is small, so everything sounded quieter: your music, YouTube, and KURAMA's own songs.

### Why KURAMA touches the sound at all

When KURAMA listens to you, it must not hear its own voice or your music as if you were talking. So, only while it
listens, it puts a small **echo filter** between your apps and the speaker:

```
Normal (KURAMA not listening):    apps ──────────────────────────► your speaker

While KURAMA listens:             apps ──► KURAMA's echo filter ──► one speaker  (the filter knows what is
                                                                                   playing, so it removes it
                                                                                   from what the mic hears)
```

The filter must send the sound on to **one** speaker. The mistake was **which** one.

### What went wrong (two mistakes together)

**Mistake 1: KURAMA overwrote the system's "chosen speaker" memory.**
Ubuntu remembers which speaker you chose, even after a reboot, and uses it whenever that speaker is connected.
Every time KURAMA started, it set that memory to a speaker it had saved long ago: the laptop speaker. It did this
even when it hadn't changed anything.

**Mistake 2: the filter followed that wrong choice.**
When KURAMA started listening, the filter sent everything to the system's current choice, which by then was the
laptop speaker.

```
Before the fix:
  KURAMA starts ──► "the chosen speaker is the LAPTOP speaker" (overwritten)
  KURAMA listens ──► apps ──► echo filter ──► LAPTOP speaker            (quiet)
  KURAMA off     ──► Ubuntu picks for itself ──► BLUETOOTH speaker       (loud)
```

That is exactly what you noticed: quieter with KURAMA, louder without it.

### What changed

1. **KURAMA no longer changes your speaker settings when it starts.** It only touches them while its echo filter
   is actually running.
2. **When the filter stops, KURAMA puts back exactly what Ubuntu remembered before.** Even if your Bluetooth
   speaker is off at that moment, Ubuntu still remembers it and picks it as soon as it connects.
3. **When the filter has to choose a speaker by itself**, it prefers: Bluetooth > USB > the laptop's own speaker >
   HDMI (a monitor or TV).
4. **If you chose a speaker yourself** (Ubuntu Settings → Sound), your choice always wins.
5. **If a Bluetooth or USB speaker connects while KURAMA is listening**, the sound moves to it straight away.
6. One-time repair: your remembered speaker was set back to the U-2500BT.

```
After the fix:
  KURAMA starts  ──► nothing changes (the chosen speaker stays BLUETOOTH)
  KURAMA listens ──► apps ──► echo filter ──► BLUETOOTH speaker          (loud)
  KURAMA off     ──► Ubuntu's own choice, unchanged ──► BLUETOOTH        (loud)
```

### The second problem: two volumes multiplied

Even on the right speaker, KURAMA's sound was quieter. While the echo filter runs there are **two volume sliders**,
and the sound passes through both:

```
apps ──► echo filter  (its own volume: 88%) ──► laptop speaker (its own volume: 81%)

what you hear  =  88% × 81%  ≈  71%
```

These are the real numbers read from your laptop on 2026-11-03. On top of that, your volume keys only moved the
**filter's** slider, which stops at 100%. The speaker's own 81% stayed underneath, so with KURAMA listening you
could never reach the loudness you get without KURAMA.

**Now there is one volume.** When the filter starts, it takes the speaker's volume (81% → the filter is 81%) and
sets the speaker itself to 100%:

```
apps ──► echo filter (81%) ──► laptop speaker (100%)        what you hear = 81%  (same as without KURAMA)
```

- Your volume keys move the filter's slider, and you can go all the way up, as without KURAMA.
- When the filter stops, the speaker gets **your last volume**: if you turned it up to 95% while KURAMA listened,
  the speaker is at 95% afterwards. Mute is kept the same way.
- When the sound moves to another speaker (Bluetooth connects), the old speaker gets your volume back and the new
  one is set up the same way.

Checked live: the speaker at 100% → the filter took 100% → I set it to 90% → after the filter stopped, the speaker
was at 90% (then I put it back to your 100%).

### Examples

| Situation | Where the sound goes now |
|---|---|
| Bluetooth speaker on, KURAMA listening | Bluetooth speaker |
| Bluetooth speaker on, KURAMA off | Bluetooth speaker |
| Bluetooth speaker switched off | Laptop speaker (nothing better is connected) |
| You turn the Bluetooth speaker back on while KURAMA listens | Moves to the Bluetooth speaker |
| You pick the laptop speaker in Settings on purpose | Laptop speaker (your choice wins) |
| Only the laptop speaker and an HDMI monitor | Laptop speaker (HDMI comes last) |

### KURAMA's own music volume (fixed the same day)

- KURAMA's music player started every song at volume 60. Because of how that player counts volume, 60 sounds
  about **4–5 times quieter** than full volume. It now starts at **100** and remembers the last music volume you
  set ("music volume 80").
- A song that started while KURAMA had turned the music down for your voice could stay quiet until it ended. It
  now gets its normal volume back as soon as the player is ready.
- "Increase the volume" while KURAMA's music plays changes **the music's** volume. To change the **laptop's**
  volume, name it: "increase the laptop volume", "set the laptop volume to 80", "system volume 80", "turn up the
  laptop sound" (instant, 0 tokens; before this fix none of these had a shortcut).

### If the sound is quieter again

Run these two commands and send me the output:

```bash
pactl list short modules | grep echo        # "sink_master=..." shows which speaker the filter uses
pw-metadata 0 default.configured.audio.sink  # the speaker Ubuntu remembers
for s in $(pactl list short sinks | cut -f2); do echo "$s $(pactl get-sink-volume $s | grep -o '[0-9]*%' | head -1)"; done
                                             # every volume: with KURAMA listening, the real speaker should be 100%
```

If you'd rather KURAMA never touch the sound at all: KURAMA Settings → turn **"Hear device sound"** on. Then
there's no echo filter. The cost: KURAMA can then hear its own voice and your music while it listens.

---

## 18. Your routine: how to make KURAMA better, faster

KURAMA was reset to a fresh start on **2026-11-03** (backup: `data/reset-backups/20261103-214142` and
`~/Documents/KURAMA-backup-20261103-214142`). From now on it learns **only from you**. The more clearly you tell it
what was good and bad, the faster it improves.

### Every day (no extra time, just while you use it)

| When | Do this | Example |
|---|---|---|
| A reply is right | Press 👍, or say it | "perfect, that's exactly what I wanted" |
| A reply is wrong | Press 👎, or say it, **and say what you wanted** | "no, play it in the music player" |
| You use a word your own way | Teach it once | "when I say code, open VS Code" |
| You want a phrase for a whole command | Teach it once | "when I say good night, lock the screen" |
| You want KURAMA to talk differently | Give a rule once | "from now on keep your answers short" |

Tips that make it learn faster:

- **Say your common requests the same way.** After one 👍, "tell me the wikipedia summary of X" costs 0 tokens for
  every X. A different wording each time needs its own 👍.
- **Complain in words, not one word.** "no" alone counts as answering a question; "no, that's wrong" counts as a 👎.
- **When you complain, say the right thing to do.** "No, play it in the music player" teaches the fix at once. Just
  "wrong" only removes the bad answer.
- **Don't 👍 a reply you didn't check.** A 👍 makes it permanent until you remove it.
- **Don't expect 👍 to work on "this / that" requests** ("open this folder"). Those depend on the screen and are
  never learned on purpose (section 6).

### First week: teach your top requests

Pick the 10–20 things you ask most often. Ask each one normally, and when the reply is right, press 👍 once.
For example:

```
what is the weather in nepalgunj            → 👍
play song <a song you like>                 → 👍   (then every "play song X" is instant)
tell me the wikipedia summary of <topic>    → 👍
set the brightness to 60 percent            → 👍
what is my battery status                   → (already instant, no need)
```

Many common ones are already instant (time, date, battery, open app, music, volume, to-do list, weather). Only
things that went to the AI need a 👍. You can tell from the chip under the reply: **tok 0** = already instant.

### Every 2–3 days (10 minutes)

1. **What went wrong:**
   ```bash
   cd /media/leo/Project1/New_project/KURAMA
   venv/bin/python scripts/trace_report.py --days 3
   ```
   Read, in this order:
   - **"Your feedback"**: every 👎 with your words. Each line is a real problem.
   - **"Likely mistakes"**: requests you corrected without pressing 👎.
   - **"Asked the AI most often"**: requests that cost tokens again and again. 👍 them the next time they're right,
     or teach your words for them.
2. **Check what was learned:** type `/learned_shortcuts list`. If something looks wrong:
   `/learned_shortcuts forget N`.
3. **Check the savings:** `/learned_shortcuts stats` (tokens saved today / this week). This number should grow.

### Every week (30 minutes, with Claude Code)

1. Open Claude Code in the KURAMA folder.
2. Paste the prompt from **MONITORING.md → "Prompt to paste into a new Claude Code session"**. It reads the last
   days, groups the problems by kind, proves the cause from the traces and suggests fixes.
3. Pick the most important problem and let it fix that one (tests, scorecard, commit).
4. Afterwards: `venv/bin/python scripts/trace_report.py --mark-fixed`, so the next report shows only new problems.

This is how things like the to-do and coding misroutes get fixed: they're problems in the code, not something a
👍 can teach.

### Every month

- **Look at the trend** in the report header: `Path: fastpath N%` (instant answers, should go **up**), `Tokens:
  … /day` (should go **down**), the number of 👎 (should go **down**).
- **Groq prompt cache** line in the report: if it stays at 0%, ask Claude Code to make the start of each AI request
  identical (that's the next token saving).
- **After 1–2 months:** if you no longer need the buttons, remove the 👍 / 👎 (section 14). Spoken feedback keeps
  working.

### Things to avoid

| Don't | Why | Do instead |
|---|---|---|
| "Reset KURAMA" to fix one wrong thing | It wipes **everything** learned | `/learned_shortcuts forget N`, "forget the rule about …", or 👎 |
| Teach yes / no / ok as your words | Refused: they answer KURAMA's questions | Use other words |
| Leave a wrong reply without a word | Nothing is learned (by your choice), and the problem stays invisible | One 👎 is enough |

### How you know it's working

| Sign | Where |
|---|---|
| More replies with **tok 0** | The chip under each reply |
| `Saved about N tokens today` grows | `/learned_shortcuts stats` |
| Fewer 👎 in the report | `trace_report.py --days 7` → "Your feedback" |
| The instant % goes up | Report header: `Path: fastpath N%` |

---

## 19. Code map

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
| `jarvis/core/devaudio.py` | The echo filter: which speaker it uses, putting your speaker choice back (section 17) |
| `jarvis/core/trace.py` | Feedback table, trace lookups |
| `frontend/app.js` | The 👍 / 👎 buttons (`rateButtons`) |
| `tests/test_recipes.py`, `tests/test_learning_gaps.py`, `tests/test_learn.py` | Tests for all of the above |
