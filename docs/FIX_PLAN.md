# Make existing KURAMA good first: fix plan (2026-10-31, from traces + code; before more Night Shift steps)

Evidence: data/traces.db (691 requests, 10-29 to 10-31), data/logs/stt.log, a 0-token replay of the old failing
requests through today's fastpath + router (live desktop context blanked), the code paths named below.
Night Shift step 2 (Safe Copy) waits until this plan is done.

## Proven problems (root cause shown)
1. **"result of job 1" did the wrong thing** (trace 8015abb3c860: sent a dog image to Telegram, made a NEW image).
   Root: the "jobs" area is covered by two general tools (config.CORE_COVERS: `create` and `kurama`); the AI was
   given `create` (can start jobs, can't show / cancel / pause them), so it improvised. Same class: every area
   covered by more than one general tool.
2. **"show job 1 result" runs a sports live search** (replay). The meaning gate let a "result" pattern through.
3. **Multi-task with a dependent step invents results** (trace 66eaad57e9cd: "report on black hole, then make a .md
   and send it to Telegram"). Root: agent._chain_node passes the previous step's REPLY text to the next step; when
   that step only STARTED a background job ("started job #4"), the next step ran at once, wrote a 41-character
   report.md ("Your detailed black hole report is ready.") into the KURAMA folder and sent that. The reply also
   claimed the report was ready (dishonest).
4. **Writing jobs don't use the Long Job Engine** (owner's observation, confirmed: jobs 2-4 are plain jobs).
   Essays / reports / code jobs still use the older writer resume (kv), no caps, no step log.
5. **Voice: real speech is dropped** (stt.log: 5 of the last 15 recognitions DROPPED, all real speech:
   "Namaste, Kurama.", "Hel Kurama", "Sot down to laptop.", "Timi Nepali Ma Bolo Sokso?"). Root: stt.py drops a
   transcript when Whisper's auto-detected language is not en/ne/hi (it said Tamil, Korean, Polish, Bengali...) and
   confidence < -0.6. Nepali / accented English is mislabelled all the time, so good text is thrown away.
6. **Multi-task cost**: each quick sub-task ran on the 120b model (9 AI calls, 6.5k tokens, two 429s), plus a
   gpt-oss tool-name glitch ('telegram<|channel|>final' -> 400).
7. **Router misses still present today** (replay): "my budget of this month is 2k" -> no tools; "remove that link"
   -> schedule/apps/files; "still now complete download?" -> clock/automation (no download status);
   "organize file bro ..." -> organizes a folder named "file bro".
8. **Scorecard reads the live desktop** (VS Code file / highlight): 4 false "text.selected" mistakes while a file is
   open; numbers depend on what is open.

## Needs evidence first (can't prove yet)
9. **Wake word rarely wakes**: there is no wake log (WAKE_DEBUG off), so the cause is unproven. Wake checks are
   Whisper calls on 0.4-3 s bursts louder than RMS 900, max 12/min, name matched by spelling (difflib 0.7).
   Suspects: quiet/far voice under the RMS floor, "Kurama" heard as other spellings, bursts merged/too long,
   the per-minute cap. Step: log every burst (length, loudness, text heard, match score, decision) for a day.
10. **AI asks yes/no in plain text, then loops on "yes"** (8 'yes' traces on 10-29/30, up to 6.9k tokens; the
    file-overwrite case). Some of this was fixed on 10-30 (typed-yes code workflow); replay 3 cases to confirm.

## Steps (one at a time; each: tests with fakes, related tests, full suite, scorecard, live check, commit, stop)
1. **Jobs + multi-task correctness** (problems 1-4, 6). DONE 2026-10-31 (PROGRESS.md). One general tool per area meaning (job status/cancel/pause/
   resume always reach the jobs tool; check every area covered twice); meaning gate for "result" shortcuts; a chain
   step that starts a background job makes the next steps WAIT for that job (follow-up runs on its output file,
   durable via the Long Job Engine), and the reply says "I'll send it when it's written"; writing jobs move onto
   the Long Job Engine (caps, steps, resume) keeping the same files; quick sub-tasks on the fast model unless they
   need reasoning; retry the same request once on the tool-name glitch. 0 extra tokens; fewer per multi-task.
2. **Voice: stop dropping real speech** (problem 5) + turn on the wake log (problem 9). DONE 2026-11-01 (also: mic input was 39%). Decide by the forced en/ne/hi
   pass's own confidence instead of Whisper's language label; keep real noise dropped (tests from the stt.log cases).
3. **Wake word** (after a day of wake.log): fix what the log shows. Likely: "KURAMA", "hey KURAMA", "wake up",
   "KURAMA wake up" all wake, matched by sound (phonetic) not spelling; loudness floor adapted to the room. If
   Whisper-per-burst is the limit, a local keyword spotter (Vosk small model with a fixed phrase list: no torch,
   0 tokens, no Groq limit; ~50 MB RAM, measured before adopting) does the first check, Whisper only confirms.
4. **Router misses + scorecard** (problems 7, 8): DONE 2026-11-01 (98% router). add the old trace phrasings (3+ wordings each) to the eval cases,
   fix by meaning (router examples / tool descriptions), never word rules; scorecard isolated from the live desktop.
5. **Plain-text yes/no** (problem 10): replay 3 cases (~5k tokens), then: risky actions always use the real yes/no
   card, the AI never asks in text.
6. **Mini KURAMA UI**: today the panel is an opaque square window (scripts/kurama_wallpaper.py, ensure_panel) and the
   page draws border-radius 0, so corners can only be sharp. Plan: transparent window (GNOME X11 compositor
   supports it) + 16 px round corners + soft shadow; frosted glass look (translucent tint + blur of KURAMA's own
   wallpaper behind it; blurring OTHER apps behind a window needs a GNOME extension such as Blur my Shell's
   application blur, to be checked); responsive sizes (compact / normal / wide with a side list); a header with mic,
   mode, live job chips with progress (tap = steps / pause / cancel), workspace peek, quick suggestions, attach
   file, settings. First a preview screenshot for your OK, then build.

Cleanup for the owner to decide: /media/leo/Project1/New_project/KURAMA/report.md (41 bytes, written by problem 3).
