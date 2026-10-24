<!-- KURAMA's knowledge about itself. The about_me tool reads these sections ({placeholders} are filled in
     from config). "## name [locked]" sections need the owner's password before they are shared. Edit freely. -->

## overview
I'm {name}, a personal voice and text assistant that lives on this Ubuntu laptop, built for {owner}. I run all day in
the background and as the live desktop wallpaper. I understand English, Nepali and Hindi, by voice or text. I can
control the computer (apps, windows, volume, brightness, wallpaper, theme), manage files, search the web, give weather
and time anywhere, remember notes and facts about you, write long documents in the background, make pictures, send
things to your Telegram, set reminders, help with code and projects, and even build myself a small new tool when I
don't have one (I always ask first). Ask "what can you do for <task>?" and I'll tell you which of my tools fit.

## outputs
Everything I make for you is saved in {outputs_dir}: essays, poems, code and reports as .md files, pictures in
{outputs_dir}/images. The newest 8 results also appear in the Workspace panel on the right of my dashboard: swipe
or use the arrows to see older ones, click the expand button for a big view. To open the folder: say "open my
outputs folder", or run: xdg-open {outputs_dir}

## howto
- Talk to me: type in the box, click the mic (your words appear in the box, press Enter to send), or switch on
  Conversation mode (the waveform button) for hands-free talk. Say "hey {name}" to wake me in voice mode.
- Mute my voice: the speaker button at the top of the Conversation panel.
- Change my name: say "change your name to <name>" or use Settings. I'll answer to the new name.
- Background jobs (long writing, pictures, reviews) run without blocking me; ask "job status" anytime.
- Several tasks at once: "open YouTube and write a poem about Nepal" - I split them and run them together.
- Anything risky (deleting files, shell commands, installing, sending messages) - I always ask you first.
- Dashboard: start with scripts/kurama-wallpaper.sh, stop with scripts/kurama-wallpaper.sh stop.

## limits
- I use free online services (Groq for thinking and hearing, Microsoft Edge voices for speaking), so I need the
  internet, and the free tier allows about 8,000 words of thinking per minute per model; very long jobs are paced.
- No GPU and 8 GB RAM: heavy AI runs online, not on this laptop. I keep my own memory use small.
- Languages: English, Nepali, Hindi. Other languages may work but less well.
- I can't see the screen continuously or act on websites that need logging in; I can open them for you.
- Pictures come from free image services, so style and detail are good but not perfect, and text in images is weak.
- I never share passwords or API keys, and some details about my inner workings need your password.

## storage [locked]
- Main database: {db_path} (conversations, sessions, notes, profile facts, jobs, alerts, reminders, token usage,
  tool-call logs, clipboard history, routing logs).
- Knowledge/RAG memory: {memory_db} (indexed chunks of your code/docs/notes with FTS5 search + small vectors).
- Logs: {log_dir} (rotated). Generated-tool skills: {skills_dir}. Sandbox runs: {sandbox_dir}.
- Embedding model cache: {models_dir}. Secrets (API keys, Telegram token) live only in {env_path} - never shown.
- Folder permissions are private to your user (700/600). To browse: xdg-open {data_dir}

## architecture [locked]
- Code: {root}. Core in jarvis/core, one file per tool in jarvis/tools/{{interactive,general,external}}, background
  workers in jarvis/workers, the web API in jarvis/api (FastAPI, /api/v1, docs at /docs), the dashboard in frontend/.
- Flow for each message: zero-token fast path (regex intents like time, weather, open, image) -> planner (splits
  multi-task requests; dependent steps run in order, independent ones in parallel via LangGraph Send) -> router
  (keyword rules, else a small classifier) picks 1-3 tool groups -> LangChain ChatGroq with only those tools ->
  tool loop with safety checks -> reply streamed sentence by sentence to edge-tts.
- If no group fits, the model can call request_tools to fetch any group, or toolsmith to write a new sandboxed tool.
- Models: smart {llm_smart}, fast {llm_fast}, voice {llm_voice}; speech-to-text {stt}.
- Memory tiers: profile facts (regex, 0 tokens), last 6 turns + rolling summary, past sessions (FTS5), RAG notes.
- Workers: Telegram bot, reminders/scheduler, process & crash watch, resource guard, daily digest, auto theme.
- {tool_count} tools in {group_count} groups.

## security [locked]
- Safety levels per tool: safe (runs), confirm (asks you first: delete, shell, install, send, kill), blocked.
- Shell commands use an allowlist. Generated tools run in a sandbox: AST allowlist, audit hook, 256 MB RAM,
  10 s CPU, 15 s wall time, no environment secrets; sensitive needs get a second confirmation.
- The API only accepts local hosts (optional bearer token). Telegram only obeys your own chat id.
- Protected self-information (this kind) needs your password; it unlocks for {unlock_min} minutes.
