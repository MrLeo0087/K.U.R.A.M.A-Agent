#!/usr/bin/env python3
"""Routing accuracy check: does each natural request reach the right tool? (no LLM calls, 0 tokens)

A request counts as right when the fast path picks the expected tool, or the router (keyword rules + the semantic
router; the LLM classifier is NOT called) sends the group that contains it. Prints the misses and a score.
    venv/bin/python scripts/eval_routing.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CASES: list[tuple[str, str]] = [
    # training / dev
    ("how is my training going", "training"), ("is the model still training", "training"),
    ("what is the current status", "status_now"), ("any update", "status_now"), ("whats going on", "status_now"),
    ("how many epochs are done", "training"), ("what is the current accuracy", "training"),
    ("stop training", "training"), ("stop the colab training now", "training"),
    ("tell me when train.py finishes", "training"), ("connect my colab notebook", "training"),
    ("start training with python train.py --epochs 20 and watch it", "run_training"),
    ("alert me when long terminal commands finish", "command_alerts"), ("turn on command alerts", "command_alerts"),
    ("what does this error mean", "fix_error"), ("I fixed it by lowering the batch size", "fix_error"),
    ("ModuleNotFoundError: No module named 'timm'\nwhile importing", "fix_error"),
    ("install timm in my kurama project", "python_env"), ("is my python environment ok", "python_env"),
    ("check my dataset data/train.csv before training", "check_dataset"), ("is my image dataset balanced", "check_dataset"),
    ("what did I change in the last 2 hours", "time_machine"), ("give me train.py as it was yesterday", "time_machine"),
    ("where was I", "where_was_i"), ("what was I working on", "where_was_i"),
    ("run the tests", "run_tests"), ("create a new fastapi project called shop", "scaffold_project"),
    ("git status of kurama", "git_info"), ("commit my changes", "git_change"),
    ("scan the repo for leaked keys", "repo_check"), ("review my staged changes", "review_code"),
    ("convert analysis.ipynb to a python script", "notebook_to_script"),
    # laptop
    ("why is my laptop so slow", "laptop_doctor"), ("my laptop is crawling", "laptop_doctor"),
    ("free up some ram", "laptop_doctor"), ("what is running on port 8000", "laptop_doctor"),
    ("why is my internet so slow", "internet_doctor"), ("websites are not loading", "internet_doctor"),
    ("internet speed test", "internet_doctor"), ("tell me when the internet is back", "internet_doctor"),
    ("turn off bluetooth", "laptop_toggle"), ("is wifi on", "laptop_toggle"), ("battery saver on", "laptop_toggle"),
    ("set volume to 40", "audio"), ("it's way too loud", "audio"), ("mute my mic", "audio"),
    ("make the screen brighter", "brightness"), ("switch to dark mode", "set_theme"),
    ("turn on night light", "night_light"), ("change my wallpaper", "set_wallpaper"),
    ("start a 25 minute focus session", "focus_mode"), ("take a screenshot", "screenshot"),
    ("lock the screen", "lock_screen"), ("how much battery is left", "battery_status"),
    ("shut down the laptop", "power_off"), ("guard my laptop while I'm away", "laptop_guard"),
    ("where is my laptop", "laptop_guard"),
    ("open vs code", "open_app"), ("close the camera", "close_app"), ("put chrome on the left half", "window"),
    ("open youtube", "open_url"), ("pause the music", "media_control"), ("play lofi on youtube", "youtube"),
    ("enable hand gesture control", "gesture_control"),
    # files / phone
    ("find my phone", "find_my_phone"), ("where is my phone", "find_my_phone"),
    ("find my resume pdf", "find_files"), ("what's in my downloads folder", "list_folder"),
    ("make a folder called experiments", "make_folder"), ("send me train.log on telegram", "send_file_telegram"),
    ("send hello to my telegram", "send_message_telegram"), ("what's on my clipboard", "clipboard"),
    ("what is using my disk space", "disk_cleaner"), ("clean the pip cache", "disk_cleaner"),
    ("download https://example.org/data.zip tonight", "download_file"), ("sort my downloads", "tidy_downloads"),
    ("back up my projects", "backup"),
    # web / info
    ("weather in pokhara tomorrow", "weather"), ("what time is it in london", "get_time"),
    ("latest news about AI", "live_search"), ("who is the prime minister of nepal", "web_search"),
    ("watch tu.edu.np/results for BSc", "web_watch"), ("tell me when this website changes https://x.org", "web_watch"),
    ("tell me about Mount Everest from wikipedia", "wikipedia"), ("what is 18% of 2500", "calculate"),
    ("100 dollars to rupees", "calculate"), ("draw a dragon flying over kathmandu", "generate_image"),
    # memory / time
    ("remember my locker code is 4432", "remember"), ("what did we talk about yesterday", "recall_session"),
    ("remind me at 6 pm to call mom", "add_reminder"), ("what reminders do I have", "schedules"),
    ("set a timer for 10 minutes", "set_timer"), ("wake me up at 6:30", "set_alarm"), ("start the stopwatch", "stopwatch"),
    ("write a 1000 word essay about Nepal", "write_document"), ("how is my essay job going", "jobs"),
    ("how many tokens did I use today", "token_usage"), ("summarize my day", "daily_digest"),
    # study
    ("note for DSA: a heap is a complete binary tree", "study_notes"), ("show my DSA notes from this week", "study_notes"),
    ("record the lecture", "lecture"), ("record this online class", "lecture"), ("stop the recording", "lecture"),
    ("what do I have tomorrow", "timetable"), ("when is my next class", "timetable"),
    ("quiz me on DSA", "quiz"), ("make a quiz from my physics notes", "quiz"),
    # self / toolsmith
    ("what can you do", "about_me"), ("change your name to Friday", "set_my_name"),
    ("build me a tool that counts words in a pdf", "make_tool"),
]

# Held out: messier, indirect phrasings (typos, STT slips, no keywords). Reported separately; never tuned on first.
HARD: list[tuple[str, str]] = [
    ("my model training crashed again can you check", "training"), ("what accuracy did it reach so far", "training"),
    ("give me an update", "status_now"), ("is colab still running my notebook", "training"),
    ("why does python say cuda out of memory", "fix_error"), ("i keep getting this keyerror label", "fix_error"),
    ("pip says it cant find torchvision install it", "python_env"), ("are there nulls in my csv", "check_dataset"),
    ("undo my changes to model.py from this morning", "time_machine"), ("what was i doing on the tara project", "where_was_i"),
    ("everything is lagging so bad", "laptop_doctor"), ("something is eating all my memory", "laptop_doctor"),
    ("wifi connected but nothing opens", "internet_doctor"), ("is my net down", "internet_doctor"),
    ("its too quiet i cant hear", "audio"), ("my eyes hurt the screen is too bright", "brightness"),
    ("sit the brightness at 30", "brightness"), ("tone of the bluetooth", "laptop_toggle"),
    ("send this to my phone /home/leo/a.pdf", "send_file_telegram"), ("whats on my laptop clipboard", "clipboard"),
    ("my disk is almost full", "disk_cleaner"), ("grab that dataset overnight https://x.org/d.tar", "download_file"),
    ("my downloads folder is a mess", "tidy_downloads"), ("is it going to rain in kathmandu", "weather"),
    ("let me know when the exam results page updates", "web_watch"), ("convert 50 euro to npr", "calculate"),
    ("ping me at 7 to drink water", "add_reminder"), ("count down 3 minutes", "set_timer"),
    ("jot down for physics newton third law", "study_notes"), ("start recording todays class", "lecture"),
    ("whats my schedule tomorrow", "timetable"), ("test me on what i studied", "quiz"),
]

# Free phrasing for the newer tools: none of these sentences are in config.TOOL_EXAMPLES or a fast-path rule (a few
# single keywords like "stt" / "cluttered" were added after a first run). Add NEW phrasings here, don't tune to them.
FREE: list[tuple[str, str]] = [
    ("can you activate the stt mode", "dictate"), ("i will speak, you write it", "dictate"),
    ("start writing whatever i say", "dictate"), ("i'm tired of typing, let me talk", "dictate"),
    ("disable the voice writing", "dictate"), ("correct this for me", "text_assist"),
    ("make my selected email sound nicer", "text_assist"), ("polish the text i highlighted", "text_assist"),
    ("put this into simple english", "text_assist"), ("there are mistakes in what i selected, fix them", "text_assist"),
    ("nobody should open my college folder", "folder_lock"), ("make my diary folder secret", "folder_lock"),
    ("i want to see my locked exam folder again", "folder_lock"), ("my cousin wants to use the internet", "share_wifi"),
    ("show me the network password", "share_wifi"), ("my laptop is too weak to train this, use kaggle", "kaggle_train"),
    ("is the gpu training done yet", "kaggle_train"), ("this downloads folder is so cluttered", "organize_files"),
    ("tidy up and rename my pictures folder by what's in them", "organize_files"),
    ("keep that youtube clip on my laptop", "video_download"), ("turn this docx into a pdf please", "convert_file"),
    ("put obs studio on this computer", "install_app"), ("uninstall that zoom thing", "install_app"),
    ("move this folder to my mobile over wifi", "wifi_share"), ("note down hari's mobile number 9812345678", "contacts"),
    ("what's the current dollar rate in nepal", "live_search"), ("hit the save button in this app", "app_control"),
]


def score(cases: list[tuple[str, str]], fastpath, registry, router) -> tuple[int, list[str]]:
    right, misses = 0, []
    for text, tool in cases:
        it = fastpath.match(text)
        if it is not None:
            got_tool = registry.resolve(it.tool, it.args)[0]
            ok, how = got_tool == tool, f"fastpath -> {got_tool}"
        else:
            r = router.route(text, log_it=False)
            group = registry.group_of(registry.get(tool)) if registry.get(tool) else "?"
            ok, how = group in r.groups, f"{r.method} -> {r.groups}"
        right += ok
        if not ok:
            misses.append(f"  MISS {text!r}: want {tool}; got {how}")
    return right, misses


def main() -> int:
    import logging
    logging.disable(logging.WARNING)
    import tempfile
    from jarvis.core import config, fastpath, registry, router, store

    # a fresh temporary database: the owner's live power mode (e.g. Low RAM = understanding model off) or saved
    # pending states must never change what this check measures
    store.init(Path(tempfile.mkdtemp()) / "eval.db")
    config.FASTPATH = True
    router.classify = lambda text, available: ([], False)  # 0 tokens: no LLM classifier in this check
    registry.REGISTRY._ensure()
    missing = [t for _, t in CASES if registry.get(t) is None]
    if missing:
        print("unknown tools in the eval:", missing)
    missing += [t for _, t in HARD if registry.get(t) is None]
    right, misses = score(CASES, fastpath, registry, router)
    hard, hmisses = score(HARD, fastpath, registry, router)
    free, fmisses = score(FREE, fastpath, registry, router)
    print("\n".join(misses + ["  (held out)"] + hmisses + ["  (free phrasing)"] + fmisses))
    print(f"routing accuracy: {right}/{len(CASES)} = {right / len(CASES):.1%}; "
          f"held-out messy phrasings: {hard}/{len(HARD)} = {hard / len(HARD):.1%}; "
          f"free phrasing (new tools): {free}/{len(FREE)} = {free / len(FREE):.1%}")
    return 0 if right == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
