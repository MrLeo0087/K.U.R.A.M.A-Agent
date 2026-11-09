# KURAMA final plan (2026-11-09): useful every day, two good agents, few tokens

Owner's direction: KURAMA must be worth it in daily life, not a toy with 150 tools. Telegram is the part that
already feels worth it, so it must be solid first. No VS Code chat panel, no Claude Code clone: a coding agent and
a study mode that are each excellent at their own job, cheap in tokens. Everything else serves the laptop and the
phone. Work rules stay: prove the cause, one general fix per class, tests + suite + scorecard, commit, stop after
each phase for the owner to test.

The test for every feature: **could Gemini / ChatGPT do this for me?** Yes -> don't build it (hand it to them, see
phase 5). No (it needs the laptop, the phone, time, or memory of my things) -> that is KURAMA.

---

## Phase 1 · Telegram solid ("reply where asked")
1. **Reply where asked.** A request from Telegram gets EVERYTHING back on Telegram: the answer, files, pictures,
   screenshots, results of background jobs, long answers (as a file or several messages), questions (yes/no as
   buttons). A request from the laptop stays on the laptop (only alerts go to the phone). Audit the 7 days of
   Telegram traces for results that stayed in the laptop workspace; fix by class.
2. **Phone alerts ring.** Since 11-06 alerts go to the group's topics, which follow the group's mute setting.
   Important ones (Claude Code finished / waiting / asking, reminders, laptop guard, a job done) go to the private
   chat with sound; a silent copy stays in the topic.
3. **Claude Code: waiting is not finished.** A Stop while a background task still runs (a video render) says
   "⏳ waiting for <task>"; "✅ finished" only when nothing is left running.
4. **One-tap buttons** under replies and in /menu: 🔒 Lock · 📸 Screenshot · 🖥 Screen off/on · 🔋 Status ·
   📂 Inbox · 🤖 Claude · 🎵 Music.
5. **Bugs from the traces:** "send morning brief" sent the words (a named thing must be sent, not its name);
   "turn off always on display" sent 12 times in 14 days (check it works); "open laptop" = the lock screen needs the
   Ubuntu password (say so with a 🔒/🔓 explanation, never a fake "done").

## Phase 2 · Voice and the windows (broken today)
1. **Mic: Alt / talk mode "didn't catch that".** Proven so far: since 11-09 09:13, 10 of 25 recordings reached
   Whisper as silence (empty, or its silence phrases "ありがとうございました", "Press Alt to"); the mic gives signal
   (3 s: peak 4127) and sits at 47% (was 70%). Missing proof: the level of the recordings. Step: log each
   recording's loudness + keep the last 5 failed WAVs, one test hold with the owner, fix what it shows (gain,
   browser auto-gain, source). A silent recording says "your mic is muted / too quiet", not "didn't catch".
   The model is already Groq's best (whisper-large-v3 first).
2. **Hold-to-talk turns appear in the chat** (main window and mini chat): the question and the reply.
3. **Music card:** progress bar moves, previous / pause / next / seek / volume work (checked live while a song
   plays, then a fake-player test).

## Phase 3 · A laptop that acts, not just warns
1. **RAM full -> it acts.** Safe at once: free KURAMA's own memory, stop KURAMA's idle helpers. Then a choice
   with buttons (laptop + Telegram): "Close Brave (2.9 GB)? · Close Kaggle tab? · Not now", and "always do this"
   remembered per app. Never kills unsaved work without a yes.
2. **Disk full -> it acts.** Safe at once: pip / uv / npm caches, thumbnails, KURAMA's old logs and temp, the
   trash older than 7 days. Then a list with sizes and buttons: old Downloads installers, duplicate files, big
   videos already sent to the phone, old Docker / venvs of deleted projects. A weekly line: "freed 3.4 GB".
3. **Phone inbox:** every photo / video / PDF / screenshot sent to the bot lands in ~/Inbox/<type>/<date>
   (names kept), big files go over Wi-Fi. "Where did my phone photo go?" answers with the path.
4. **Send to phone in one move:** right-click a file in Files -> "Send to phone" (a Nautilus script), or drop it on
   the KURAMA bubble; folders as a zip / link.
5. **Downloads tidy itself** (nightly: by type, installers and duplicates flagged, screenshots by date).
6. **"Start my day" / "done for today":** one word opens the saved tabs + VS Code project + music, or saves, closes,
   sleeps the laptop and sends a short report.
7. **Laptop health quietly:** battery care, disk / RAM trends, a nightly backup of chosen folders to a drive;
   a message only when it needs you.

## Phase 4 · Music that knows you
Proven cause of bad picks: "similar songs" are a YouTube TEXT search ("songs like <name>") -> random videos with
those words (ELO -> "Ilu Ilu Yeh Ilu Ilu").
1. **Real recommendations:** YouTube's own radio for the song (the RD mix of that video, read with yt-dlp, free)
   instead of the text search.
2. **Your taste:** skipped in the first 30 s = less of that artist / style; played to the end or "I like this" =
   more; your languages (Nepali / Hindi / English) and moods ("for study" = instrumental / lo-fi, no vocals).
3. **Moods and playlists:** "play something for studying / gym / sleep", "save this to my favourites", "play my
   favourites"; the card shows what's next and why ("because you played X").
4. Phase 2.3 (the card works) comes first.

## Phase 5 · "Ask Gemini / ask ChatGPT" (0 KURAMA tokens)
Select code, a word or a sentence anywhere and say "ask Gemini why this works" / "ask ChatGPT why we wrote this":
1. KURAMA builds the prompt: your question + the selection + where it is (page title and URL, or the file name and
   the lines around it in VS Code).
2. Brave opens gemini.google.com / chatgpt.com (a new tab, or the one already open), the KURAMA browser extension
   pastes the prompt into the box and presses send. No copy, no typing, no screen clicking.
3. "ask Gemini" alone uses your default; follow-ups ("ask it simpler") go to the same tab.
4. Works by voice, typed, and the hotkey. If you aren't signed in there, it says so.

## Phase 6 · KURAMA core + two modes (the split)
- **Core** (always on): laptop, phone, Telegram, files, apps, music, reminders, money, Claude Code link, laptop
  health. About 60 tools behind ~10 general tools: fewer schemas per request = fewer tokens and fewer wrong picks.
- **Code mode** and **Study mode**: each its own prompt, tools, memory and chat thread (a mode button in the mini
  chat, /code, /study, Telegram too). Who answers: your switch > what is selected and where (code in VS Code ->
  code, text elsewhere -> study) > the meaning of the request. Core commands (volume, open YouTube, time) still
  work inside a mode at 0 tokens. Leaving: "back to normal" or 10 min idle.
- **Removed:** the KURAMA Coder chat panel in VS Code (the extension stays only to tell KURAMA the open file and
  the selection); explain / improve / replace selection in general mode (they belong to the modes now).

## Phase 7 · Study mode (best at reading and writing, few tokens)
1. **Context (0 tokens):** the browser extension sends the selection + its paragraph + the heading above it + the
   page title and URL; a PDF in the browser is read from the file (pdftotext, offline); other apps by a screen
   read. The page is summarized ONCE (~1.5k tokens) and cached.
2. **Answers:** paragraph + page summary + selection + task -> one call (gpt-oss-120b; Gemini when Groq is used
   up). Short by default (meaning in this context, plain words, one example: for docs a command you can run),
   "more" for the long version. Voice speaks two lines; the full answer is in the study chat.
3. **Tasks:** explain / meaning in context / simpler / in Nepali / summarize the section or page / write a
   paragraph or essay / revise my essay (changes shown, replace on yes) / translate / quiz me.
4. **Memory and notes (offline):** every answer is saved to notes per document and day; a glossary of the terms
   you asked; one thread per document, so tomorrow's follow-up still knows the page.
5. **Cost:** ~2-4k tokens per question, the page summary once.

## Phase 8 · Coding agent (best at its own job, few tokens)
**Its job:** inside one project folder: explain selected code, fix the error you just got (terminal traceback),
small features and changes, new small projects (scripts, Tkinter / web pages, ML notebooks and training scripts),
uv environments, run it to check, commit. Big multi-hour work -> "send to Claude Code" (Telegram), not done here.
**How it stays good and cheap:**
1. Measure first: coder/evals on your real requests (45 coding requests last week, 67.7k tokens; 6 over 5k; one
   build 18k tokens / 24 calls; "I can't tell which file this error comes from"). List failures by class.
2. Exact-edit changes (search -> replace blocks), never whole files; only the files that matter (from the
   traceback, the selection, the project map), project map cached (0 tokens).
3. A plan call only for multi-file work; check by running (0 tokens); at most 2 fix rounds, then it says what is
   wrong and stops.
4. Targets: median <= 6k tokens per change, >= 80% of the eval tasks done right.
5. Interface: KURAMA chat (Code mode), voice, Telegram /code; progress in the Progress section.

## Phase 9 · Helpers for your day (one at a time, after the above)
1. **GitHub in one line:** "new project X" (uv init + git + GitHub repo), "push my work" (commit message + push),
   a morning line if a build failed or an issue needs you.
2. **Kaggle on your phone:** training started, progress, done with the score.
3. **Reel-ready video:** any video -> 9:16, compressed to Instagram limits, caption + hashtag ideas.
4. **YouTube helper:** a 2-minute summary before you watch (from subtitles), download for offline, timestamps.
5. **Find by content:** "the PDF about attention I downloaded last week" (searches inside files, offline index).
6. **Phone on the laptop:** if Android, scrcpy (see and control the phone) + GSConnect (notifications,
   clipboard, files), started by "show my phone". Needs the owner's answer: Android or iPhone.

---

## Order and what "done" means
| Phase | Done when |
|---|---|
| 1 Telegram solid | a week of Telegram traces with every result delivered there; alerts ring; no false "finished" |
| 2 Voice + windows | 20 holds in a row heard; turns in the chat; music card moves and its buttons work |
| 3 Laptop acts | RAM / disk alerts come with what was done + buttons; inbox and send-to-phone used daily |
| 4 Music | next songs from YouTube radio; skips change what comes next |
| 5 Ask Gemini / ChatGPT | "ask Gemini why this works" sends the right prompt, 0 KURAMA tokens |
| 6 Core + modes | scorecard holds; selection requests go to the right mode; VS Code panel gone |
| 7 Study mode | answers name the page's context; notes + glossary fill themselves; <= 4k tokens a question |
| 8 Coding agent | eval targets met (<= 6k tokens median, >= 80% done) |
| 9 Helpers | each used in a real day |
