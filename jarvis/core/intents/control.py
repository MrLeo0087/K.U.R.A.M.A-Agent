"""Fast-path intents for reminders, laptop power (shutdown/restart/sleep) and the clock.

Moved out of fastpath.py unchanged; fastpath re-imports every name, so `fastpath.X` still works."""
from __future__ import annotations

import re
import time
from jarvis.core.intents.base import I, Intent, _full, _rx


# --- P9b --- reminders: "remind me to X at/in ...", "remind me at ... to X", list, cancel
REMIND = _rx(r"(?:remind me|set (?:a |an |the |my )?(?:reminder|alarm)|add (?:a )?reminder|create (?:a )?reminder)"
             r"(?: for me)?(?: to| that| about| for)?\s+(?P<rest>.+)")


# "3:02 PM of today for reading book": time first, then the task
_WHEN_FIRST = re.compile(r"^(?P<d1>(?:today|tomorrow)\s+)?(?:at\s+)?(?P<t>\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.))"
                         r"(?:\s+(?:of\s+)?(?P<d2>today|tomorrow))?\s+(?:for|to|about)\s+(?P<x>.+)$", I)


REMIND_LIST = _rx(
    r"(?:what|which|any) (?:reminders|schedules|scheduled (?:commands|tasks)) (?:do i have|are there|are set|"
    r"have i set)(?: today)?",
    r"(?:list|show|tell)(?: me)?(?: all)?(?: of)?(?: my)? (?:reminders|schedules|scheduled (?:commands|tasks))",
    r"(?:my|all) reminders", r"do i have any reminders")


REMIND_CANCEL = _rx(r"(?:cancel|delete|remove|stop) (?:the )?(?:reminder|schedule|scheduled command)"
                    r"(?: number| no\.?)? ?#?(?P<id>\d+)")


# --- laptop control + clock (0 tokens) ---
_DEV = r"(?:\s+(?:the|my|this))?\s*(?:laptop|computer|pc|system|machine|device)"


_WHEN_NOW = r"(?:\s+(?:now|right\s+now|for\s+now|for\s+today|please|immediately))*"


_SHUTDOWN = re.compile(r"^(?:shut\s*down|power\s*off)(?:" + _DEV + r")?" + _WHEN_NOW + r"$|^(?:turn|switch)\s+off" + _DEV + _WHEN_NOW + r"$", I)


_RESTART = re.compile(r"^(?:restart|reboot)(?:" + _DEV + r")?" + _WHEN_NOW + r"$", I)


_SUSPEND = re.compile(r"^(?:(?:sleep|suspend|hibernate)" + _DEV + r"|suspend|put" + _DEV + r"\s+to\s+sleep|"
                      r"make" + _DEV + r"\s+sleep)(?:\s+now)?$", I)


_LOGOUT = re.compile(r"^(?:log\s*out|logout|sign\s*out)(?:\s+(?:of\s+)?(?:the|my)?\s*(?:session|account|laptop|computer))?$", I)


_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
        "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty five": 45, "half an": 0.5}


_AMOUNT = r"(?P<n>\d+(?:\.\d+)?|a|an|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|thirty|forty(?: five)?|half an)"


_UNIT = r"(?P<u>sec(?:ond)?s?|min(?:ute)?s?|hours?|hrs?)"


_TIMER = [re.compile(r"^(?:set|start|put|make)\s+(?:\w+\s+)?(?:timer|countdown|count\s*down)\s+(?:for|of)\s+" + _AMOUNT + r"\s*" + _UNIT + r"$", I),
          re.compile(r"^(?:set|start)?\s*(?:a|an)?\s*" + _AMOUNT + r"[\s-]*" + _UNIT + r"\s+(?:timer|countdown)$", I),
          re.compile(r"^(?:timer|countdown)\s+(?:for\s+)?" + _AMOUNT + r"\s*" + _UNIT + r"$", I)]


_ALARM = re.compile(r"^(?:set|put|create|add)\s+(?:an?\s+|the\s+)?alarm\s+(?:for|at)\s+(?P<w>.+)$|"
                    r"^wake\s+me\s+(?:up\s+)?(?:at|by|in)\s+(?P<w2>.+)$|^alarm\s+(?:for|at)\s+(?P<w3>.+)$", I)


_STOPWATCH = re.compile(r"^(?P<a>start|begin|stop|pause|reset|restart|resume|check|lap)?\s*(?:the\s+|a\s+)?stop\s?watch"
                        r"(?:\s+(?P<b>start|stop|status|time|lap|reset))?(?:\s+now)?$|^(?P<c>lap)$", I)


_DEVICES = (("airplane", r"(?:air|aero)plane(?:\s+mode)?|flight\s+mode"), ("wifi", r"wi[\s-]?fi|wireless|internet"),
            ("bluetooth", r"blue\s?tooth"), ("power_mode", r"(?:battery|power)\s+saver"), ("screen", r"screen|display"))


_SW_VERB = re.compile(r"\b(?:turn|switch|put|make|set|enable|disable|activate|deactivate|start|stop|kill)\b", I)


_SW_FILL = re.compile(r"\b(?:the|my|this|that|it|please|bro|man|dude|now|again|then|also|just|for me|kurama|"
                      r"can you|could you|would you|will you)\b", I)


_SW_FOLLOW = re.compile(r"^(?:(?:turn|switch|put)\s+)?(?:it|this|that|them)?\s*(?:on|off|back on|back off)"
                        r"(?:\s+(?:it|this|that|them))?$|^(?:turn|switch|put)\s+(?:it|this|that|them)\s+(?:on|off)$", I)


SWITCH_TTL_S = 600  # "turn it off" refers to the device switched in the last 10 minutes


_AOD = r"(?:(?:the\s+|my\s+)?(?:always[\s-]*on(?:\s+display)?|aod|a\.o\.d\.?|caffeine|coffin|coffee\s+mode))"  # 'coffin' = STT


_AWAKE_ON = re.compile(r"\b(?:(?:turn|switch|put|set)\s+on\s+" + _AOD + r"|(?:enable|start|activate)\s+" + _AOD + r"|" + _AOD
                       + r"\s+on|keep\s+(?:the\s+|my\s+)?(?:screen|display|laptop)\s+(?:on|awake)|stay\s+awake|don'?t\s+"
                       r"(?:let\s+)?(?:the\s+|my\s+)?(?:screen|display|laptop)\s+(?:sleep|turn\s+off|go\s+off))\b", I)


_AWAKE_OFF = re.compile(r"\b(?:(?:turn|switch|set)\s+off\s+" + _AOD + r"|(?:disable|stop|deactivate)\s+" + _AOD + r"|" + _AOD
                        + r"\s+off|let\s+(?:the\s+|my\s+)?(?:screen|display|laptop)\s+sleep)\b", I)


_AWAKE_ASK = re.compile(r"\b(?:(?:what(?:'s|\s+is)|show|tell\s+me|check)\s+(?:the\s+)?(?:status\s+of\s+)?" + _AOD
                        + r"(?:\s+status)?|is\s+" + _AOD + r"\s+(?:on|off|enabled|running)|" + _AOD + r"\s+status)\b", I)


def switch_intent(t: str) -> Intent | None:
    """"turn off bluetooth", "bluetooth off bro", "disable wifi", and the follow-up "turn it off" (0 tokens)."""
    asking = re.match(r"^\W*(?:does|do|is|are|was|has|have|can\s+you\s+(?:check|tell)|check|tell\s+me\s+(?:if|whether))\b", t, I) \
        or t.rstrip().endswith("?")  # 'Does my laptop always on display on?' turned it ON (11-04): a question only reads
    if re.search(_AOD, t, I) and asking or _AWAKE_ASK.search(t):  # 'what is status of my AOD' (0 tokens)
        return Intent("control", "laptop_toggle", "system", {"setting": "stay_awake", "state": "status"})
    if _AWAKE_OFF.search(t):
        return Intent("control", "laptop_toggle", "system", {"setting": "stay_awake", "state": "off"})
    if _AWAKE_ON.search(t):  # 'turn on always on display' turned the screen OFF (11-04)
        return Intent("control", "laptop_toggle", "system", {"setting": "stay_awake", "state": "on"})
    low = t.lower()
    device = next((name for name, rx in _DEVICES if re.search(r"\b(?:" + rx + r")\b", low)), None)
    question = re.match(r"^(?:is|are|was|check|what(?:'s| is)|tell me|show me|can you (?:tell|check|give))\b", low) \
        or re.search(r"\b(?:status|whether)\b", low)
    if re.search(r"\b(?:speed|fast|slow|ping|bandwidth|mbps)\b", low) and re.search(r"\b(?:internet|wi[\s-]*fi|wifi|net|connection|network)\b", low):
        return Intent("netspeed", "internet_doctor", "system", {"action": "speed"})  # 'what is speed of my internet'
        # answered "Wi-Fi is enabled." (11-04)
    if question and not _SW_VERB.search(low) and "password" not in low:
        # "is bluetooth on?", "bluetooth status": a question, answered by reading the switch
        return Intent("control", "laptop_toggle", "system", {"setting": device, "state": "status"}) \
            if device in ("wifi", "bluetooth", "airplane", "power_mode") else None
    st = "off" if re.search(r"\b(?:off|down|disable|deactivate|kill|stop)\b", low) else \
        "on" if re.search(r"\b(?:on|up|enable|activate|start)\b", low) else None
    if st is None:
        return None
    rest = _SW_FILL.sub(" ", low)
    if device is None:  # follow-up: "turn it off", "then turn off this", "off"
        if not _SW_FOLLOW.match(" ".join(re.sub(r"\b(?:then|now|please|bro|kurama)\b", " ", low).split())):
            return None
        try:
            import json
            from jarvis.core import store
            last = json.loads(store.kv_get("last_switch", "") or "{}")
        except Exception:
            last = {}
        if time.time() - last.get("t", 0) > SWITCH_TTL_S or not last.get("device"):
            return None
        device = last["device"]
    elif not (_SW_VERB.search(rest) or len(rest.split()) <= 3):  # "my bluetooth is off" is a statement, not an order
        return None
    if device == "screen":
        return Intent("control", "laptop_toggle", "system", {"setting": "screen", "state": "off"}) if st == "off" else None
    if device == "power_mode":
        return Intent("control", "laptop_toggle", "system", {"setting": "power_mode", "state": "saver" if st == "on" else "balanced"})
    return Intent("control", "laptop_toggle", "system", {"setting": device, "state": st})


_POWERMODE = re.compile(r"^(?:switch\s+to\s+|set\s+|use\s+|enable\s+)?(?P<m>power saver|battery saver|saver|balanced|"
                        r"performance|high performance)\s+mode$", I)


def _amount(m: re.Match) -> dict | None:
    n = m.group("n").lower()
    v = float(n) if n[0].isdigit() else _NUM.get(n)
    u = m.group("u").lower()
    key = "seconds" if u.startswith("s") else "hours" if u.startswith("h") else "minutes"
    return {key: v} if v else None


_PHONE_TAIL = re.compile(r"[\s,]+(?:and\s+)?(?:(?:when|once|after)\b[^,]{0,40}?[\s,]+)?(?:also\s+)?(?:send|message|text|"
                         r"notify|tell|ping|alert|inform|say|remind)\b.{0,40}?\b(?:telegram|telegra|phone|mobile)\b.*$", I)


_WALL_CHANGE = re.compile(r"^(?:(?:i\s+mean|actually|please|can\s+you|could\s+you|i\s+want\s+(?:you\s+)?to)\W+)*"
                          r"(?:change|switch|set\s+(?:a\s+)?(?:new|different)|give\s+me\s+a\s+new|new)\s+(?:the\s+|my\s+)?(?:image\s+in\s+my\s+)?"
                          r"(?:desktop\s+)?(?:wallpaper|background)(?:\s+(?:image|picture))?$", I)


_CHART = re.compile(r"^(?:(?:can|could)\s+you\s+)?(?:make|create|draw|show|give)\s+(?:me\s+)?(?:a\s+)?(?P<k>pie|bar|line)?\s*"
                    r"(?:chart|graph|plot)\s+(?:of|for|about|showing)\s+(?P<x>.+)$", I)


_TRAINING_Q = re.compile(r"\b(?:training|traning|trainning|traing)\b.*\b(?:happening|running|going|status|progress|done|finished)\b|"
                         r"^(?:is\s+there\s+)?any\s+(?:training|traning|trainning)\b", I)


_HABIT_DONE = re.compile(r"^i\s+(?:have\s+|just\s+)?(?:complete[d]?|did|done|finished|drank|drink|dring|had)\s+(?P<x>.+)$", I)


_HI_WAKE = re.compile(r"(?P<w>.+?)\s+(?:utha|uthaa|jaga|jagaa)\s*(?:dena|do|dijiye|dijie|dijiega)$|"
                      r"(?P<w2>.+?)\s+(?:uthaidinu|uthai\s+dinu|uthaunu|उठाइदिनु|उठा\s*देना|जगा\s*देना)$", I)


_HI_TIME = ((r"\bkal\b|\bभोलि\b|\bकल\b", "tomorrow"), (r"\baaj\b|\baja\b|\bआज\b", "today"),
            (r"\b(?:subah|bihana|सुबह|बिहान)\b", "am"), (r"\b(?:shaam|sham|beluka|साँझ|शाम|बेलुका)\b", "pm"),
            (r"\b(?:raat|rati|रात|राति)\b", "pm"), (r"\b(?:baje|bajey|bajay|बजे|बजे)\b", ""), (r"\b(?:mujhe|malai|मुझे|मलाई)\b", ""))


def _hinglish_when(text: str) -> str:
    """'kal subah 6 baje' -> 'tomorrow 6 am'."""
    t = " " + text.lower() + " "
    ampm = "am" if re.search(_HI_TIME[2][0], t, I) else "pm" if re.search(_HI_TIME[3][0] + "|" + _HI_TIME[4][0], t, I) else ""
    for rx, rep in _HI_TIME:
        t = re.sub(rx, "" if rep in ("am", "pm") else rep, t, flags=I)
    t = " ".join(t.split())
    return re.sub(r"(\d{1,2}(?::\d{2})?)", lambda m: f"{m.group(1)} {ampm}".strip(), t, count=1) if ampm else t


def _everyday_intent(t: str) -> Intent | None:
    if _WALL_CHANGE.match(t):
        return Intent("control", "set_wallpaper", "desktop", {"mode": "next"})
    if m := _CHART.match(t):
        return Intent("control", "make_chart", "image", {"request": m.group("x"), **({"kind": m.group("k").lower()} if m.group("k") else {})})
    if _TRAINING_Q.search(t) and len(t.split()) <= 12:
        return Intent("control", "training", "watch", {"action": "status"})
    if (m := _HABIT_DONE.match(t.strip(" .!"))) and len(t.split()) <= 10:
        try:
            from jarvis.core import habits
            if habits.find(m.group("x")):
                return Intent("control", "habits", "tracker", {"action": "done", "text": m.group("x")})
        except Exception:
            pass
    if m := _HI_WAKE.match(t.strip(" .!?")):
        when = _hinglish_when(m.group("w") or m.group("w2"))
        if re.search(r"\d", when):
            return Intent("control", "set_alarm", "clock", {"when": when})
    return None


def _control_intent(t: str) -> Intent | None:
    if ei := _everyday_intent(t):
        return ei
    if _SHUTDOWN.match(t):
        return Intent("control", "power_off", "power", {"action": "shutdown"})
    if _RESTART.match(t):
        return Intent("control", "power_off", "power", {"action": "restart"})
    if _SUSPEND.match(t):
        return Intent("control", "suspend_computer", "power", {})
    if _LOGOUT.match(t):
        return Intent("control", "power_off", "power", {"action": "logout"})
    t2 = _PHONE_TAIL.sub("", t)  # "set a timer for 40 seconds and when it's done message me on Telegram"
    for rx in _TIMER:
        if (m := rx.match(t2)) and (args := _amount(m)):
            if t2 == t:
                return Intent("control", "set_timer", "clock", args)
            said = re.search(r"\b(?:saying|that\s+says|which\s+says|with\s+the\s+(?:text|words?))\s+[\"']?(?P<x>.+?)[\"'.!]*$",
                             t[len(t2):], I)  # 'send me a telegram message saying break time': the message it sends
            return Intent("control", "set_timer", "clock", {**args, "phone": True, **({"label": said.group("x")} if said else {})})
    if m := _ALARM.match(t):
        w = (m.group("w") or m.group("w2") or m.group("w3")).strip(" .")
        return Intent("control", "set_alarm", "clock", {"when": w if not t.lower().startswith("wake me up in") else f"in {w}"})
    if m := _STOPWATCH.match(t):
        a = (m.group("a") or m.group("b") or m.group("c") or "status").lower()
        a = {"begin": "start", "resume": "start", "restart": "reset", "pause": "stop", "check": "status",
             "time": "status"}.get(a, a)
        return Intent("control", "stopwatch", "clock", {"action": a})
    if si := switch_intent(t):
        return si
    if m := _POWERMODE.match(t):
        mode = m.group("m").lower()
        return Intent("control", "laptop_toggle", "system",
                      {"setting": "power_mode", "state": "saver" if "saver" in mode else "performance" if "perf" in mode else "balanced"})
    return None


def _p9b_intent(t: str) -> Intent | None:
    if _full(REMIND_LIST, t):
        return Intent("schedules", "list_schedules", "schedule")
    if m := _full(REMIND_CANCEL, t):
        return Intent("schedules", "cancel_schedule", "schedule", {"item": m.group("id")})
    if m := _full(REMIND, t):
        from jarvis.core import when

        got = when.split(m.group("rest"))
        if not got and (w := _WHEN_FIRST.match(m.group("rest"))):
            day = (w.group("d1") or w.group("d2") or "").strip()
            got = when.split(f"{w.group('x')} at {w.group('t')} {day}".strip())
        if got:
            what, when_text, _ = got
            return Intent("remind", "add_reminder", "schedule", {"text": what, "when": when_text}, what)
    return None
