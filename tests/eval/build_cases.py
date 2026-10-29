"""Builds tests/eval/cases.jsonl: KURAMA's test set (v2 phase 2).

Almost every case is a request the owner really said or typed (taken from the conversation history, Whisper
mishearings and all); a few short ones fill gaps. Each case names the INTENT that should happen, in words that stay
the same while the tools are rebuilt (phase 3), plus the arguments that matter. "chat" = answer without any tool;
"clarify" = garbled speech: no tool, ask again. Run: venv/bin/python tests/eval/build_cases.py
"""
from __future__ import annotations

import json
from pathlib import Path

L, T, V = "laptop", "telegram", "voice"

# (text, intent, key args or None, channel)
CASES: list[tuple[str, str, dict | None, str]] = [
    # --- chat / clarify (no tool) ---
    ("Hello Kurama, how are you?", "chat", None, L),
    ("Hello, how are you and what are you doing bro?", "chat", None, L),
    ("say hi in 3 words", "chat", None, L),
    ("Just got home", "chat", None, T),
    ("I still love you.", "chat", None, L),
    ("Sorry, I was too loud.", "chat", None, L),
    ("Well, I want to make some Langchain project, but I do not have the idea that what kind of project I can build", "chat", None, L),
    ("give me nepali word for learning", "chat", None, L),
    ("Tell me about yourself something.", "self.about", None, V),
    ("What the fuck are you doing?", "chat", None, L),
    ("Zilbaogi.", "clarify", None, L),
    ("Chitum musumlaigu.", "clarify", None, L),
    ("Plus the Blev.", "clarify", None, L),
    ("Oly, Japan, Ma, Mousim, Gusto, Zoh.", "clarify", None, L),
    ("E aí, se é, Raul, Wari.", "clarify", None, L),
    ("Продолжение следует...", "clarify", None, L),
    ("Uh... Uh...", "clarify", None, L),
    ("Hawaare", "chat", None, L),
    ("Kau!", "clarify", None, V),
    ("Q&A", "clarify", None, V),
    # --- time / date / weather ---
    ("What is time right now?", "time", None, L),
    ("what time is it ?", "time", None, L),
    ("tell me date", "date", None, L),
    ("And what is the date today?", "date", None, L),
    ("Tell me what is the day today?", "date", None, L),
    ("What is the weather today in Kathmandu?", "weather", {"place": "Kathmandu"}, L),
    ("So, I am wondering how the weather is in Japan now.", "weather", {"place": "Japan"}, L),
    ("do I need an umbrella in kathmandu today", "weather", {"place": "kathmandu"}, L),
    ("Can you tell me what is the weather in Nepal currently?", "weather", {"place": "Nepal"}, L),
    ("उसे के तुम बता सकती हो अभी जैपान में टाइम क्या हुआ है?", "time", None, L),
    # --- to-do / reminders / alarms / timers / stopwatch ---
    ("show my to-do list", "todo.list", None, L),
    ("Give me my list of tasks.", "todo.list", None, L),
    ("Is there anything in my ToDo?", "todo.list", None, L),
    ("Is there any tax for me today?", "todo.list", None, L),
    ("what do I have to do today", "todo.list", None, L),
    ("What's on today?", "day.today", None, L),
    ("add buy milk to my to-do list #shopping tomorrow 5 pm", "todo.add", {"task": "buy milk"}, L),
    ("add finish the report to my to-do list, it's urgent", "todo.add", {"task": "finish the report"}, L),
    ("Remove all the tasks for me.", "todo.clear", None, L),
    ("Okay, remove the second task from my list of tasks.", "todo.delete", {"item": "2"}, L),
    ("done 2", "todo.done", {"item": "2"}, L),
    ("mark 3 as complete", "todo.done", {"item": "3"}, L),
    ("set remiander for 3:02 PM of today for reading book", "reminder.add", None, L),
    ("Also set the reminder for tomorrow 6 am for walking.", "reminder.add", None, L),
    ("Also, I want you to schedule a tax for 2.20pm of today for working.", "reminder.add", None, L),
    ("Okay, schedule a work for 11.41pm for reading the book.", "reminder.add", None, L),
    ("remind me to call mom at 5 pm", "reminder.add", None, L),
    ("Is there any reminder for me today?", "reminder.list", None, L),
    ("what is my reminder today", "reminder.list", None, L),
    ("Set alram for 1:53pm", "alarm.set", None, T),
    ("set an alarm for 6 am", "alarm.set", None, L),
    ("set timer of 1 min", "timer.set", None, L),
    ("Actually, see the alarm there, ring in the 4 minutes.", "timer.set", None, L),
    ("Set 1 min timer and when it complere .. say me telegram", "timer.set", None, T),
    ("Start or stopwatch now.", "stopwatch", {"action": "start"}, L),
    ("Can you start the Stobas now?", "stopwatch", {"action": "start"}, L),
    ("Okay, now stop the stopwatch.", "stopwatch", {"action": "stop"}, L),
    ("Reset the stopwatch and start again.", "stopwatch", {"action": "reset"}, L),
    # --- open / close apps, sites, folders ---
    ("open Brave browser in my laptop", "open.app", None, L),
    ("Open Extension Manager.", "open.app", None, V),
    ("open youtube", "open.site", None, L),
    ("So, can you open the YouTube?", "open.site", None, L),
    ("Okay, now open the Facebook and YouTube in my breath.", "open.site", None, L),
    ("Ok, now open the Youtube, Facebook and SoFiScore website.", "open.site", None, L),
    ("Open project1 in laptop on file manager", "open.folder", None, T),
    ("Now open tara in laptop", "open.folder", None, T),
    ("Close brave", "close.app", None, T),
    ("I say that close the Brave browser that open in my laptop.", "close.app", None, L),
    ("Kill brave", "kill.app", None, T),
    ("Can you minimize the VS Code?", "window", None, L),
    # --- Telegram ---
    ("send hello to my telegram", "telegram.message", None, L),
    ("Send what are you doing to my telegram.", "telegram.message", None, L),
    ("Can you send this file to the telegram? /media/leo/Project1/Tara/OCR_CODE/EasyOCR/Nchat_ML/EasyOCR_Finetune/train.py", "telegram.file", None, L),
    ("Can you look for naruto.jpg image in my laptop and send me ?", "telegram.find_send", None, T),
    ("Send me tools.py file from laptop", "telegram.find_send", None, T),
    ("send this photo to telegram", "telegram.result", None, L),
    ("Generate image of futuristic car and get it on telegram", "image.generate", {"send_to_telegram": True}, T),
    # --- files and folders ---
    ("Give me list of file in Tara folder", "files.list", None, T),
    ("List of final rag", "files.list", None, T),
    ("Is there clz project folder", "files.find", None, T),
    ("Can you source tool.py file in my entire laptop?", "files.find", None, L),
    ("search for main.py in project1 then tara folder", "files.find", None, L),
    ("Find final rag folder in laptop", "files.find", None, T),
    ("Can you create a new folder in my home directory called NayaFolder?", "files.mkdir", None, V),
    ("organize download folder", "files.organize", None, L),
    ("my downloads folder is a mess, fix it", "files.organize", None, L),
    ("Okay, remove this project from my laptop currently.", "files.delete", None, T),
    # --- music, media, sound, screen ---
    ("Listen to music, buddy.", "media.play", None, L),
    ("play arijit sing some", "media.play", None, L),
    ("next", "media.control", None, L),
    ("The next song.", "media.control", None, L),
    ("Play", "media.control", None, T),
    ("increase volume", "volume", None, L),
    ("Can you increase the volume by 30?", "volume", None, L),
    ("Can you tell me what is the sound volume value of my laptop currently?", "volume", None, V),
    ("stop audio", "volume", None, L),
    ("increase brightness", "brightness", None, L),
    ("Set the laptop brightness in 1%.", "brightness", None, L),
    ("Sit the brightness at 1%.", "brightness", None, L),
    ("Take the screenshot of my display.", "screenshot", None, L),
    ("Give me screenshot of my laptop", "screenshot", None, T),
    ("Read this screen, Kurama.", "screen.read", None, L),
    ("What is writing on the screen?", "screen.read", None, L),
    ("look the screen and tell me what this website is about and what is showing ?", "web.read", None, L),
    # --- laptop switches / power ---
    ("Can you turn off the Bluetooth of my laptop?", "laptop.toggle", {"setting": "bluetooth"}, L),
    ("PON UP THE BLUETOOTH BRO", "laptop.toggle", {"setting": "bluetooth"}, L),
    ("Tone of the Bluetooth", "laptop.toggle", {"setting": "bluetooth"}, L),
    ("Can you give me my Bluetooth status that Bluetooth is on or off?", "laptop.toggle", {"setting": "bluetooth"}, L),
    ("turn off wifi", "laptop.toggle", {"setting": "wifi"}, L),
    ("Enable the night light of my laptop.", "night_light", None, L),
    ("Disable the night light.", "night_light", None, L),
    ("Can you enable the dark mode?", "theme", None, V),
    ("Can you enable the light mode of my laptop?", "theme", None, V),
    ("I mean, I want you to change my wallpaper.", "wallpaper", None, V),
    ("Shut down the laptop.", "power.shutdown", None, L),
    ("Laptop shutdown", "power.shutdown", None, T),
    ("restart this laptop", "power.restart", None, L),
    ("Sleep laptop", "power.sleep", None, T),
    ("Slip my laptop.", "power.sleep", None, L),
    ("Tell me the battery percentage.", "battery", None, L),
    ("What is my battery status", "battery", None, T),
    # --- system health ---
    ("Check ram of my laptop", "system.status", None, T),
    ("What's going on with my laptop like RAM, CPU, just tell me.", "system.status", None, V),
    ("Which process take most ram memery ?", "system.status", None, T),
    ("Who use most memory?", "system.status", None, T),
    ("my laptop is crawling, everything is slow", "system.status", None, L),
    ("internet speed test", "system.internet", None, L),
    ("wifi connected but nothing opens", "system.internet", None, L),
    ("empty the trash", "system.disk", None, L),
    ("my disk is almost full", "system.disk", None, L),
    # --- web / news / live answers ---
    ("what is result of recent arsenal match ?", "web.live", None, L),
    ("Tell.me today man united match", "web.live", None, T),
    ("What is today inter miami match result", "web.live", None, T),
    ("who are top 10 ranking for ballon dior 2026 .. give me top 10 ranking", "web.live", None, L),
    ("latest news about AI", "web.news", None, L),
    ("Can you search for recent Barcelona football match in Google and give me the result.", "web.live", None, V),
    ("लुम्बिनीका सभामुख तुलाराम घर्तीसहित ५ जनाविरुद्ध जालसाजी मुद्दा दायर भएको हो र ?", "web.live", None, L),
    # --- making things ---
    ("Can you generate the image of a man?", "image.generate", None, L),
    ("Generate an image of a misty hill in oil-paint style and send it to Telegram", "image.generate", {"send_to_telegram": True}, L),
    ("Can you generate a long essay about the Nepal in detail and send that essay in my telegram", "writing.job", None, V),
    ("Make the audio of this selected sentence.", "audio.make", None, L),
    ("make pie chart of my spend and budget", "chart.make", None, L),
    # --- selected text / code help ---
    ("Explain this code service that I select.", "text.selected", None, L),
    ("what is meaning of this sentence", "text.selected", None, L),
    ("Can you fix this sentence and make it look better?", "text.selected", None, L),
    ("KURAMA, convert this text into Nepali.", "text.selected", None, L),
    ("i keep getting KeyError: 'label' in my dataloader", "code.fix", None, L),
    ("where was I", "code.where", None, L),
    ("what did I change in the last hour", "code.changes", None, L),
    ("What is the git status of this project?", "code.git", None, V),
    # --- clipboard / dictation ---
    ("What i copy.recently", "clipboard", None, T),
    ("what is copy yesterday", "clipboard", None, L),
    ("Copy the area that I select.", "clipboard", None, L),
    ("dictate", "dictate", None, L),
    ("stop dictation", "dictate", None, L),
    # --- memory / people ---
    ("What is my name?", "memory.recall", None, V),
    ("Can you tell me what do you know about me?", "memory.recall", None, V),
    ("Remember that I am living in Nepalgunj, Baanke, Nepal.", "memory.remember", None, V),
    ("Actually I want you to remove all the remember note.", "memory.forget", None, V),
    ("What we are talking yesterday ?", "memory.session", None, T),
    ("Give me the phone number for Narayan Choula.", "contacts", None, L),
    ("Give me phone number of narayan", "contacts", None, T),
    # --- money / habits / goals / reading list / links ---
    ("Give me the monthly report of the expensive.", "money", None, L),
    ("How much rupees i spend ?", "money", None, T),
    ("What is my total budget for spending?", "money", None, L),
    ("add my habit of drink water 5 liter dairly", "habits", None, L),
    ("i complete 5 liter water", "habits", None, L),
    ("show my long tasks", "goals", None, L),
    ("save this link at read later", "readlater.add", None, L),
    ("give me list from my read later", "readlater.list", None, L),
    ("save this link in link store for groq activity dashboard", "links", None, L),
    ("give me link of dead shot", "links", None, L),
    # --- phone / laptop location, remote, gesture ---
    ("find my phone", "phone.find", None, L),
    ("show my phone location history", "phone.location", None, L),
    ("Give me location of laptop", "laptop.location", None, T),
    ("Stop tracking laptop", "laptop.location", None, T),
    ("/control laptop", "remote", None, T),
    ("Stop remote desktop", "remote", None, T),
    ("turn on gesture control", "gesture", None, L),
    ("Disable Media Jexor Control System.", "gesture", None, L),
    # --- training / day / tokens ---
    ("how is my training going", "training", None, L),
    ("Is there any traning happening?", "training", None, T),
    ("summarize today", "day.summary", None, L),
    ("How many token did i use today ?", "tokens", None, T),
    ("What is 18% of 2500", "calculate", None, L),
    ("what is my battery health", "battery", None, L),
    # --- Nepali / Hindi / mixed ---
    ("अहिले कति बज्यो", "time", None, V),
    ("kitne baje hain", "time", None, V),
    ("आज काठमाडौंको मौसम कस्तो छ?", "weather", None, V),
    ("youtube kholo", "open.site", None, V),
    ("volume badhao", "volume", None, V),
    ("mujhe kal subah 6 baje utha dena", "alarm.set", None, V),
    ("gana bajau", "media.play", None, V),
    # --- several tasks in one request (every listed intent must happen) ---
    ("Open youtbe and increases brightness of laptop by 60", "multi", {"all": ["open.site", "brightness"]}, T),
    ("write a 1000-word essay about Nepal and open YouTube", "multi", {"all": ["writing.job", "open.site"]}, L),
    ("turn off bluetooth and set a timer for 5 minutes", "multi", {"all": ["laptop.toggle", "timer.set"]}, L),
    ("add buy eggs to my to-do list and remind me to call mom at 6 pm", "multi", {"all": ["todo.add", "reminder.add"]}, L),
    ("what's the weather in Pokhara and what time is it", "multi", {"all": ["weather", "time"]}, L),
    ("take a screenshot and send it to my telegram", "multi", {"all": ["screenshot", "telegram.result"]}, L),
    ("close brave and open vs code", "multi", {"all": ["close.app", "open.app"]}, L),
]


def build() -> list[dict]:
    out, seen = [], set()
    for i, (text, intent, args, channel) in enumerate(CASES, 1):
        if text.lower() in seen:
            raise SystemExit(f"duplicate case: {text}")
        seen.add(text.lower())
        row = {"id": i, "text": text, "expect": intent, "args": args or {}, "channel": channel}
        if intent == "multi":
            row["all"], row["args"] = row["args"].pop("all"), {}
        out.append(row)
    return out


if __name__ == "__main__":
    path = Path(__file__).with_name("cases.jsonl")
    rows = build()
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"{len(rows)} cases -> {path}")
