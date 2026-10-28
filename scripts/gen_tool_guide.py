"""Write the 'Every tool in detail' part of COMMAND.md from the live tool registry (run after adding tools):

    venv/bin/python scripts/gen_tool_guide.py

What each tool does, whether it asks first, every action it has (from the tool's own schema) and example sentences
(EXAMPLES below, by hand). The text between the two markers in COMMAND.md is replaced; the rest is left alone.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jarvis.core import registry as R  # noqa: E402

START, END = "<!-- TOOLS:START -->", "<!-- TOOLS:END -->"

AREAS = [  # (title, groups, a line about the area)
    ("Everyday", ["general", "weather", "clock", "daily", "schedule"], "Time, weather, reminders, maths, files to convert."),
    ("Money & habits", ["tracker"], "Your spending and daily habits, kept in Excel sheets you can also edit."),
    ("Study & memory", ["study", "memory", "knowledge"], "Notes, quizzes, classes, things KURAMA remembers, search in your own files."),
    ("Laptop control", ["audio", "display", "desktop", "power", "apps", "windows", "screen", "system", "usage"],
     "Volume, screen, apps, windows, power, health of the laptop."),
    ("Files & folders", ["files", "filesearch", "automation"], "Find, open, make, move, lock, clean up, back up."),
    ("Phone & Telegram", ["telegram"], "Things that go to (or come from) your phone."),
    ("Web, links & reading", ["web", "browser"], "Live answers, search, web pages, saved links, read-later."),
    ("Text & clipboard", ["clipboard"], "Help with any text you highlight or copy."),
    ("Coding", ["codequality", "dev", "devutils", "git", "watch"], "Help inside VS Code and around your projects."),
    ("Create (images, charts, diagrams, audio, video, writing)", ["image", "jobs"], "Free generation; results land in the Workspace."),
    ("Music & video", ["media"], "Music without the browser, YouTube, downloads, hand gestures."),
    ("KURAMA itself", ["self", "toolsmith"], "About KURAMA, new tools, skills, reset."),
]

# tool -> (example sentences, optional tip)
EXAMPLES: dict[str, tuple[list[str], str]] = {
    # everyday
    "get_time": (["what time is it", "what time is it in Tokyo", "/time london"], ""),
    "get_date": (["what is the date today", "date in AD", "which week is this", "aajako miti", "/date"],
                 "Nepali Bikram Sambat by default; say 'in AD' for the English date."),
    "weather": (["weather", "weather in Pokhara tomorrow", "will it rain today", "/weather kathmandu"], "Up to 3 days ahead."),
    "set_alarm": (["set an alarm for 6 am", "wake me up at 5:30", "/alarm 6 am"], ""),
    "set_timer": (["timer 10 minutes", "set a timer for 25 minutes", "/timer 5"], ""),
    "stopwatch": (["start the stopwatch", "stop the stopwatch", "lap"], "Also shows on the Now & today card."),
    "calculate": (["15% of 2400", "calculate 1250 * 12", "sqrt 144", "/calc 99*99"], "Done locally: 0 tokens."),
    "convert_file": (["convert this pdf to markdown", "convert report.docx to pdf", "convert video.mp4 to mp3",
                      "convert photo.png to jpg"], "Big conversions run in the background. 'this' = the file you have open/selected."),
    "disk_cleaner": (["clean my disk", "what is taking my disk space", "clean the cache"], "Shows what it will delete and asks first."),
    "organize_files": (["organize my downloads", "organize the Documents folder", "undo the organizing"],
                       "Shows a plan in the Workspace; answer 'yes', 'no' or a change ('keep the pictures where they are')."),
    "add_reminder": (["remind me to call mom at 5", "remind me to drink water in 30 minutes", "remind me every day at 9 pm to study",
                      "/remind call ram at 6 pm"], "A heads-up 10 minutes before; also on Telegram."),
    "goals": (["my exam is in 30 days, remind me every day", "show my long tasks", "how many days until the exam",
               "today I wrote chapter 2 of the thesis", "move the exam to December 2", "make the thesis report"],
              "Long tasks only (weeks/months). Short tasks are the to-do list (read_later)."),
    "schedule_command": (["every day at 10 pm back up my documents", "at 11 pm shut down the laptop"],
                         "Runs a KURAMA action at a time (not a reminder for you). Asks first."),
    "schedules": (["what reminders do I have", "cancel the 5 pm reminder", "show my schedule"], ""),
    # money & habits
    "expenses": (["spent 200 on meat, 50 on tomato and 500 on vegetables", "got 20000 salary", "spent 300 on bus on October 20",
                  "how much did I spend this month", "how much did I spend on food from Oct 1 to Oct 15",
                  "spending breakdown", "set my food budget to 8000", "remind me to pay internet 1500 every month on the 5th",
                  "paid internet", "delete the last expense", "/money week"],
                 "Click the Money & habits card for the Money window (dates, categories, delete rows)."),
    "habits": (["add a habit: drink water 8 glasses a day, remind me at 10 am", "I drank 2 glasses of water", "did exercise",
                "my habits", "I didn't do exercise", "delete the water habit", "/done exercise"],
               "Streaks and the last 7 days show on the Money & habits card (✓ button = done today)."),
    # study & memory
    "study_notes": (["note for DSA: a stack is LIFO", "show my DSA notes", "show my notes from this week"], "Saved in ~/Notes by subject."),
    "quiz": (["start a quiz on DSA", "next question", "the answer is B", "my quiz stats"], "Spaced repetition from your own notes."),
    "timetable": (["show my timetable", "what classes do I have today"], "Paste your timetable once; it reminds you before classes."),
    "lecture": (["record this lecture", "record the online class", "stop recording and give me notes"],
                "Records the mic or the laptop's sound, then makes notes."),
    "contacts": (["what's Ram's number", "add Sita 9812345678", "show my contacts"], "Excel: ~/Documents/KURAMA/contacts.xlsx."),
    "remember": (["remember that my exam is on Nov 25", "remember I like lofi music"], ""),
    "recall": (["what do you know about me", "what did I tell you about the exam"], ""),
    "recall_session": (["what did we talk about yesterday", "what was that link from this morning"], ""),
    "forget": (["forget that", "forget my exam date"], ""),
    "index_folder": (["index my Notes folder", "learn my project folder"], "So you can ask questions about your own files."),
    "search_knowledge": (["search my notes for recursion", "find where I wrote about the API key"], ""),
    "ask_knowledge": (["according to my notes, what is a heap", "what does my project README say about setup"], ""),
    # laptop
    "audio": (["volume 40", "volume up", "mute", "unmute", "mute the mic", "set volume to 130", "/vol up"],
              "Up to 150% when Ubuntu's Over-Amplification is on. While KURAMA's music plays, 'volume up' changes the music."),
    "brightness": (["brightness 60", "brightness up", "/bright down"], ""),
    "set_theme": (["dark mode", "light mode", "/dark"], ""),
    "do_not_disturb": (["do not disturb on", "turn off do not disturb", "/dnd on"], ""),
    "focus_mode": (["start focus mode", "focus for 50 minutes", "stop focus mode", "/focus 25"], "DND on, then an alert when time is up."),
    "night_light": (["night light on", "turn off the night light"], ""),
    "set_wallpaper": (["set this picture as my wallpaper", "change my wallpaper to mountains"], ""),
    "share_wifi": (["share wifi", "show the wifi qr code"], "A QR code your phone can scan to join the Wi-Fi."),
    "battery_status": (["battery", "how long will the battery last", "/battery"], ""),
    "laptop_guard": (["turn on the guard", "is the guard on", "/guard on"], "While armed: a photo + location to Telegram when someone unlocks the laptop."),
    "lock_screen": (["lock the screen", "/lockscreen"], ""),
    "power_off": (["shut down the laptop", "restart the laptop", "log out"], "Always asks yes / no first."),
    "suspend_computer": (["suspend the laptop", "put the laptop to sleep"], "'sleep now' alone puts KURAMA to sleep, never the laptop."),
    "open_app": (["open VS Code", "open Brave", "open the calculator"], ""),
    "close_app": (["close Brave", "close Spotify"], ""),
    "kill_app": (["kill the frozen app", "force quit VS Code"], "Asks first. Never touches KURAMA or system processes."),
    "install_app": (["install VLC", "install obs studio"], "apt / snap / flatpak through a password popup."),
    "launch_workspace": (["open my coding workspace", "start my study setup"], "Opens a set of apps together."),
    "window": (["snap this window left", "maximize this window", "switch to Brave", "list my windows"], ""),
    "app_control": (["press ctrl+t", "new tab", "go to tab 3", "click the Save button", "scroll down"],
                    "Keys and clicks in the app in front."),
    "dictate": (["start dictation", "start dictation in Nepali", "stop dictation"],
                "Types what you say into any app; say 'new line', 'change paragraph', 'undo', 'stop'."),
    "screenshot": (["take a screenshot", "screenshot this window", "/screenshot"], "Saved to the Workspace."),
    "read_text": (["read the text on the screen", "what is written here", "read the text in this picture"], "OCR, handwriting too."),
    "scan_qr": (["scan the qr code", "scan the qr code on the screen"], ""),
    "laptop_doctor": (["why is my laptop slow", "free up some ram", "what is running on port 8080", "show my open ports",
                       "free port 3000", "/doctor", "/ports"], "Stopping anything asks first; KURAMA itself is never stopped."),
    "internet_doctor": (["check my internet", "fix my internet", "how fast is my connection", "/internet"], ""),
    "laptop_toggle": (["turn off wifi", "turn on bluetooth", "airplane mode on"], "Same as the switches on the Laptop card."),
    "location_history": (["where is my laptop", "where has my laptop been today", "/where", "/history phone 12"], ""),
    "find_my_phone": (["where is my phone", "give me the location I shared on Telegram", "find my phone", "ring my phone"],
                      "'where' = the last location your phone shared with the bot; 'find / ring' opens Google Find My Device."),
    "remote_desktop": (["/control (on Telegram)", "turn off remote desktop", "/changepass (on Telegram)"],
                       "Gives a RustDesk password for 15 minutes, only on Telegram after your PIN."),
    "status_now": (["status", "what's going on right now", "/status"], ""),
    "token_usage": (["token usage", "how many tokens did I use today", "/tokens"], ""),
    "daily_digest": (["summarize my day", "daily digest", "/digest"], "Also sent by itself at 10 PM."),
    "power_mode": (["low RAM mode", "normal mode", "full mode", "which mode am I in"], "How many helpers run in the background."),
    # files
    "find_files": (["find my resume pdf", "find report in Documents", "where is train.py"], "Searches the whole laptop, typos OK."),
    "list_folder": (["what's in my Downloads", "show this folder"], ""),
    "open_folder": (["open the Downloads folder", "open this folder"], "'this / here' = the folder you used last."),
    "folder_lock": (["lock this folder with a password", "unlock the secret folder"], "The password is typed in a popup, never in chat."),
    "make_folder": (["make a folder called notes here", "create a folder Projects in Documents"], ""),
    "write_file": (["write hello world to notes.txt", "save this text as todo.md"], ""),
    "move_path": (["move it to Documents", "move report.pdf to Desktop"], ""),
    "copy_path": (["copy this file to the USB", "copy notes.txt to Desktop"], ""),
    "delete_to_trash": (["delete this file", "delete old.zip"], "Goes to the Trash (you can restore it). Asks first."),
    "backup": (["back up my documents", "backup now", "when was the last backup"], ""),
    "download_file": (["download this file", "download https://example.com/file.zip"], ""),
    "tidy_downloads": (["clean my downloads", "tidy the downloads folder"], ""),
    "add_watchdog_target": (["keep my dev server alive", "restart my flask server if it crashes"], ""),
    "watchdog_status": (["what is the watchdog watching", "watchdog status"], ""),
    # phone
    "send_file_telegram": (["send this file to Telegram", "send report.pdf to my phone"], ""),
    "send_last_result": (["send the last result to my phone", "send that image to Telegram"], ""),
    "send_message_telegram": (["send me a message on Telegram: buy milk", "text my phone the wifi password"], ""),
    "wifi_share": (["share this file over wifi", "share the Downloads folder to my phone"],
                   "A link + QR for your phone on the same Wi-Fi."),
    "mute_alerts": (["mute RAM alerts for 20 minutes", "unmute alerts", "which alerts are muted", "/mute ram 20", "/notifications"],
                    "On Telegram you can also reply 'stop' to an alert."),
    # web
    "live_search": (["latest news about Nepal", "gold price today", "dollar rate", "football scores", "top 10 Ballon d'Or 2026",
                     "/news cricket"], "Fresh facts from the web; long lists go to the Workspace."),
    "web_search": (["search the web for python asyncio", "/search best laptop under 1 lakh"], ""),
    "read_webpage": (["read https://example.com/article", "summarize this link"], ""),
    "wikipedia": (["wikipedia Mount Everest", "/wiki Buddha"], ""),
    "web_watch": (["tell me when this website changes", "watch the exam results page"], ""),
    "open_url": (["open youtube", "open my facebook link", "open github.com"], "Your saved links win over normal websites."),
    "page_summary": (["what is this page about", "summarize this page", "/page"], "Reads the tab open in your browser; 'yes' = a detailed overview."),
    "read_later": (["add buy milk to my to-do list", "save this to read later at 9 pm", "show my list", "what's on today",
                    "done 2", "remove the second task", "/todo"], "To-do + reminders + read-later in one list (read_later.xlsx)."),
    "saved_links": (["save this link as facebook", "give me my claude code link", "show my saved links", "delete the x link"],
                    "links.xlsx."),
    # text
    "text_assist": (["explain this", "meaning of this word", "translate this to Nepali", "summary of this paragraph",
                     "improve this text", "explain this code", "fix this code", "give me code to test this function",
                     "how can I use this function", "what should I reply to my friend", "write a csv reader here"],
                    "Highlight first. Changes to your files are shown first and done only after 'yes'."),
    "clipboard": (["what did I copy 10 minutes ago", "show my clipboard history", "copy back the second one", "/clip"], ""),
    # coding
    "code_nav": (["find this function", "go to definition", "help me with this library", "is this correct syntax",
                  "what arguments does this take", "run this code", "/def", "/args", "/run"],
                 "Highlight in VS Code. find = opens the real code; help = real arguments + typo check; run = output (then 'fix it')."),
    "code_tidy": (["format this file", "check this file", "fix the problems", "/format", "/check"], "ruff; backups kept."),
    "dependency_doctor": (["check my dependencies", "are my requirements pinned", "any outdated packages"], ""),
    "repo_check": (["check my repo", "scan the repo for leaked keys", "check before commit"], ""),
    "review_code": (["review my code changes", "review the last commit"], ""),
    "run_tests": (["run the tests", "run the tests in this project"], ""),
    "fix_error": (["what does this error mean", "fix this error"], "Copy or highlight the error first."),
    "python_env": (["create a venv", "install pandas in this project", "which python is this project using"], ""),
    "scaffold_project": (["create a new flask project called shop", "start a python project"], ""),
    "check_dataset": (["check this dataset", "look at data.csv for problems"], ""),
    "decode_text": (["decode this", "pretty print this json", "decode this base64", "what time is this timestamp"], ""),
    "generate_requirements": (["make requirements.txt from imports"], ""),
    "notebook_to_script": (["turn this notebook into a script", "convert train.ipynb to python"], ""),
    "git_info": (["git status", "show the git log", "what changed in my code", "/git"], ""),
    "git_change": (["commit my changes", "make a new branch called login", "switch to main"], "Asks first."),
    "time_machine": (["watch the project at ~/code/app", "watch this project", "list my coding projects", "stop watching",
                      "/projects"], "Snapshots of only the projects you choose."),
    "where_was_i": (["where was I", "what was I working on", "/code"], ""),
    "run_training": (["train this model in the background", "run train.py and tell me when done"], ""),
    "training": (["how's training", "show the training progress"], ""),
    "kaggle_train": (["train this on Kaggle", "run the notebook on a free GPU"], "Needs ~/.kaggle/kaggle.json once."),
    "command_alerts": (["turn on command alerts", "tell me when long terminal commands finish"], ""),
    # create
    "generate_image": (["generate an image of a red panda", "make 4 versions of a fox", "make a phone wallpaper of Everest",
                        "same picture but at night", "an HD image of a castle", "/image a dragon over Pokhara"],
                       "Free (your Cloudflare workers, then Pollinations)."),
    "make_chart": (["chart my expenses", "pie chart of my spending this week", "make a chart from sales.csv",
                    "draw a graph of population by district from <link>", "/chart"], "Several views (bar, line, pie)."),
    "make_diagram": (["make a diagram of this project", "flowchart: wake up, brush, study", "diagram of this code",
                      "/diagram", "/flow a, b, c"], "Projects are drawn from their README only."),
    "make_audio": (["make an audio of this", "turn the last result into audio", "make an mp3 of <link>",
                    "make an audio of notes.pdf", "/audio"], "English / Nepali / Hindi voice."),
    "make_video": (["make a short video about the Himalayas", "make a reel about momo", "create a video with this script: ...",
                    "make a slideshow from ~/Pictures/trip", "/reel tea"], "Pictures + voice + captions, joined with ffmpeg."),
    "write_document": (["write a 1000-word essay about Nepal", "write a report on climate change", "write a python snake game"],
                       "A background job; saved in the Workspace."),
    "jobs": (["what jobs are running", "cancel the job", "show the result of job 12", "/jobs"], ""),
    # media
    "music": (["play lofi music", "play kya mujhe pyar hai by KK", "next", "pause", "music volume 80", "play my study playlist",
               "save this playlist as study", "play my music", "stop the music", "/music"],
              "Sound only (no browser). The next song is loaded while one plays."),
    "media_control": (["pause", "play", "next song", "what song is this", "pause the video", "continue the video",
                       "/play", "/pause", "/next"], "Works for KURAMA's music and for videos in the browser."),
    "youtube": (["play despacito on youtube", "search youtube for python tutorials", "/yt lofi"], "Opens YouTube in Brave."),
    "video_download": (["download this video", "download it in 720p", "download this as mp3", "download this playlist"], ""),
    "gesture_control": (["gesture control on", "turn off gesture control"], "Control media with your hand in front of the camera."),
    # kurama
    "about_me": (["what can you do", "how do you work", "what are your limits"], ""),
    "find_capability": (["do you have a tool to compress pdf", "can you track my sleep"], ""),
    "set_my_name": (["call me Leo", "my name is Dhiru"], ""),
    "reset_kurama": (["reset KURAMA", "/reset"], "Wipes what KURAMA knows (asks first; settings and password kept)."),
    "make_tool": (["make a tool that renames photos by date", "create a tool to count words in a file"],
                  "KURAMA writes a small tool and asks before running it."),
    "skills": (["show my skills", "use the rename skill", "delete the rename skill"], "Tools KURAMA made for you."),
}


def actions_of(schema: dict) -> list[str]:
    """'action: play (query = ...), url (...)' style lines from the tool's own parameter docs."""
    props = schema.get("function", {}).get("parameters", {}).get("properties", {})
    out = []
    for name, p in props.items():
        desc = (p.get("description") or "").strip()
        enum = p.get("enum")
        if not desc and not enum:
            continue
        line = f"`{name}`"
        if enum and len(enum) > 1 and not desc:
            line += ": " + ", ".join(enum)
        if desc:
            line += f": {desc}"
        out.append(re.sub(r"\s+", " ", line))
    return out


def build() -> str:
    tools = {t.name: (g, t) for g in R.REGISTRY.groups() for t in R.REGISTRY.schemas_for([g])}
    lines = [START, "", f"## 8. Every tool in detail ({len(tools)} tools)", "",
             "Generated from the tools themselves by `scripts/gen_tool_guide.py`.",
             "- **Runs at once** means it just does it. **Asks first** means it waits for your yes.",
             "- Under **What it understands** are the settings the AI fills in from your words. You never type them.",
             "- The **Say** lines are examples. Your own words work too.", ""]
    seen: set[str] = set()
    for title, groups, about in AREAS:
        names = [n for n, (g, _) in sorted(tools.items()) if g in groups]
        if not names:
            continue
        lines += [f"### {title} ({len(names)})", "", about, ""]
        for n in names:
            seen.add(n)
            _, t = tools[n]
            schema = R.schema_of(t)
            desc = schema["function"]["description"].strip()
            ex, tip = EXAMPLES.get(n, ([], ""))
            safety = {"safe": "runs at once", "confirm": "asks first", "blocked": "blocked"}.get(R.safety_of(t), R.safety_of(t))
            lines.append(f"#### `{n}`: {desc}")
            lines.append(f"- **Safety:** {safety}")
            acts = actions_of(schema)
            if acts:
                lines.append("- **What it understands:** " + acts[0])
                lines += [f"  - {a}" for a in acts[1:]]
            if ex:
                lines.append("- **Say:** " + " · ".join(f"“{e}”" if not e.startswith("/") else f"`{e}`" for e in ex))
            if tip:
                lines.append(f"- **Tip:** {tip}")
            lines.append("")
    rest = sorted(set(tools) - seen)
    if rest:  # a new group nobody placed yet
        lines += ["### Other", ""] + [f"- `{n}`: {R.schema_of(tools[n][1])['function']['description']}" for n in rest] + [""]
    lines.append(END)
    return "\n".join(lines)


def main() -> int:
    path = ROOT / "COMMAND.md"
    text = path.read_text()
    block = build()
    if START in text and END in text:
        text = text[:text.index(START)] + block + text[text.index(END) + len(END):]
    else:
        text = text.rstrip() + "\n\n---\n\n" + block + "\n"
    path.write_text(text)
    missing = [n for g in R.REGISTRY.groups() for n in (t.name for t in R.REGISTRY.schemas_for([g])) if n not in EXAMPLES]
    print(f"COMMAND.md: {block.count('#### ')} tools written" + (f"; no examples yet for: {', '.join(missing)}" if missing else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
