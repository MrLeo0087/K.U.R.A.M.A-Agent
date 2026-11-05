"""Fast-path intents for saved links, the to-do list, long goals and the reading list.

Moved out of fastpath.py unchanged; fastpath re-imports every name, so `fastpath.X` still works."""
from __future__ import annotations

import re
from jarvis.core.intents.base import I, Intent, URL_RE, _RL_LIST, _nth, yes_no


def _small_talk(text: str) -> bool:
    """A greeting / thanks / okay (the everyday replies) or small talk by meaning: never a name for something."""
    s = (text or "").strip(" .!,")
    try:
        from jarvis.core import fastpath, templates
        if any(rx.match(s) for rx in (fastpath._HELLO, fastpath._THANKS, fastpath._OKAY, fastpath._BYE)):
            return True
        return templates.small_talk(s) is not None
    except Exception:  # noqa: BLE001 - model not loaded: not small talk
        return False


# --- saved links: 'this is the link for Claude Code, save it', 'give me my Facebook link' (0 tokens) ---
_L_WORD = r"(?:link|url|page|site|website|address)"


_L_STORE = r"(?:\s+(?:in|to|into|at)\s+(?:your\s+|my\s+|the\s+)?(?:memory|link\s+stor(?:e|er)|links?|store|bookmarks?|saved\s+links))?"


_L_SAVE = r"(?:save|store|keep|remember|bookmark|add)"


def links_intent(t: str) -> Intent | None:
    from jarvis.core import links
    low = t.strip(" .!?").lower()
    L = lambda a, **k: Intent("links", "saved_links", "links", {"action": a, **k})  # noqa: E731
    u = links.URL.search(t)
    url = {"url": u.group(0)} if u and re.search(r"https?://|www\.", u.group(0), I) else {}
    if links.pending():  # 'What should I call this link?' was asked
        if re.fullmatch(r"(?:no|cancel|never\s*mind|don'?t\s+save(?:\s+it)?|forget\s+it|leave\s+it)", low) or re.search(
                r"\b(?:already\s+(?:have|saved|got)|we\s+have\s+(?:it|this)|don'?t\s+(?:save|store)|remove\s+this\s+link)\b", low):
            return L("cancel")
        if m := re.fullmatch(r"(?:call|name|save|label)\s+it\s+(?:as\s+)?(?P<n>.+)|(?:it'?s|it\s+is|this\s+is)\s+(?:my\s+|the\s+)?(?P<n2>.+)", t.strip(" .!"), I):
            return L("name", name=m.group("n") or m.group("n2"))
        if len(low.split()) <= 5 and not t.strip().endswith("?") and len(re.sub(r"\W", "", low)) >= 2 \
                and not _small_talk(t):  # 'i' (a misheard 'hi') and 'hi' were saved as a link's name (11-05)
            return L("name", name=t.strip(" .!"))
    # save with a name
    for rx in (r"(?:this|that|it)\s+is\s+(?:the\s+|my\s+|a\s+)?" + _L_WORD + r"\s+(?:for|of|to)\s+(?:my\s+|the\s+)?(?P<n>[^,.;]+?)"
               r"(?:\s*[,.;]?\s*(?:so\s+|please\s+|and\s+|just\s+|can\s+you\s+)*(?:" + _L_SAVE + r")\b.*)?",
               r"(?:please\s+|can\s+you\s+)*" + _L_SAVE + r"\s+(?:(?:this|that|the|it)\s*" + _L_WORD + r"?|" + _L_WORD + r")\s*(?:of\s+(?:this|it)\s*)?" + _L_STORE
               + r"\s*(?:,\s*)?(?:as|called|named|under|with\s+(?:the\s+)?name|for)\s+(?:my\s+|the\s+)?(?P<n>.+?)" + _L_STORE,
               r"(?:please\s+|can\s+you\s+)*" + _L_SAVE + r"\s+(?:(?:this|that|the|it)\s*" + _L_WORD + r"?|" + _L_WORD + r")\s*(?:of\s+(?:this|it)\s*)?" + _L_STORE
               + r"\s*(?:,\s*)?(?:and\s+)?(?:call|name|say|label|title)\s+it\s+(?:as\s+)?(?P<n>.+)",
               r"(?:please\s+|can\s+you\s+)*" + _L_SAVE + r"\s+(?:my\s+|the\s+)(?P<n>[\w .+#-]{2,30}?)\s+" + _L_WORD + _L_STORE):
        if m := re.fullmatch(rx, links.URL.sub(lambda x: x.group(0) if not url else "", t.strip(" .!?")), I):
            n = links.clean_name(m.group("n"))
            if n and not re.fullmatch(r"(?:this|that|it)", n, I) and not re.search(r"\blater\b|\breading\b|\bread\b", n, I):
                return L("save", name=n, **url)
    # save, no name: KURAMA asks for one
    if re.fullmatch(r"(?:please\s+|can\s+you\s+)*" + _L_SAVE + r"\s+(?:the\s+)?(?:" + _L_WORD + r"\s+of\s+)?(?:this|that|the|it)\s*(?:"
                    + _L_WORD + r")?(?:\s+of\s+this)?" + _L_STORE[:-1] + r"(?:\s+please)?", low, I) or (
            re.fullmatch(r"(?:please\s+)?" + _L_SAVE + r"\s+(?:this\s+)?" + _L_WORD, low, I)):
        return L("save", **url)
    if re.fullmatch(r"(?:show|list|see|open|what\s+are|give\s+me|tell\s+me)?\s*(?:me\s+)?(?:all\s+)?(?:my\s+|the\s+)?(?:saved\s+links|links|"
                    r"link\s+stor(?:e|er)|bookmarks)(?:\s+(?:i|you)\s+(?:saved|have|kept))?", low, I) or re.fullmatch(
            r"what\s+links\s+(?:did\s+i|have\s+i|do\s+i\s+have|did\s+you)\s*(?:save|saved|keep|kept)?", low, I):
        return L("list")
    if m := re.fullmatch(r"(?:please\s+)?(?:delete|remove|forget)\s+(?:the\s+|my\s+)?(?P<n>.+?)\s+" + _L_WORD + _L_STORE, low, I):
        if links.lookup(m.group("n")):
            return L("delete", name=m.group("n"))
    if m := re.fullmatch(r"rename\s+(?:the\s+|my\s+)?(?P<n>.+?)\s+" + _L_WORD + r"\s+(?:to|as)\s+(?P<x>.+)", t.strip(" .!?"), I):
        if links.lookup(m.group("n")):
            return L("rename", name=m.group("n"), new_name=m.group("x"))
    # get / open by name; not saved -> None (the AI answers from its own knowledge)
    m = (re.fullmatch(r"(?:please\s+|can\s+you\s+)*(?P<v>give|send|show|tell|get|copy|share|open|find|what(?:'s|\s+is))\s+(?:me\s+)?(?:the\s+|my\s+)?"
                      + _L_WORD + r"\s+(?:of|for|to)\s+(?:my\s+|the\s+)?(?P<n>.+?)(?:\s+from\s+.+)?", low, I)
         or re.fullmatch(r"(?:please\s+|can\s+you\s+)*(?P<v>give|send|show|tell|get|copy|share|open|find|what(?:'s|\s+is))\s+(?:me\s+)?(?:the\s+|my\s+)"
                         r"(?P<n>[\w .+#-]{2,30}?)(?:'s)?\s+" + _L_WORD + r"(?:\s+from\s+.+)?", low, I))
    if m and links.lookup(m.group("n")):
        return L("open" if m.group("v").startswith("open") else "get", name=m.group("n"))
    return None


# --- the to-do list = short tasks for today / soon (reminders + to-dos); long tasks are goals; the code is the project ---
_TD_CMD = re.compile(r"\b(?:shut\s*down|restart|reboot|run|command|script|backup|open|launch|start|turn\s+(?:on|off)|lock|suspend|"
                     r"sleep|kill|close|install|download|send|message|email|every|daily|weekly|hourly)\b", I)


def todo_now_intent(t: str) -> Intent | None:
    """Three separate lists, 0 tokens: the TO-DO list (tasks to do; never rings), REMINDERS (alerts at a time) and the
    READING list. 'schedule reading the book at 11:45 pm' -> a reminder (NOT schedule_command, which runs computer
    commands); 'is there anything in my to-do', 'what is the current work I have to do' -> the to-do list; 'what are
    my reminders' -> the reminders; 'remove/move/rename X' -> whichever list X is on."""
    from jarvis.core import readlater, reminders, todos
    low = t.strip(" .!?").lower()
    T = lambda a, **k: Intent("todo", "todo", "todo", {"action": a, **k})  # noqa: E731  (to-do list)
    R = lambda a, **k: Intent("readlater", "read_later", "links", {"action": a, **k})  # noqa: E731  (reading list)
    S = lambda a, **k: Intent("schedules", "schedules", "schedule", {"action": a, **k})  # noqa: E731  (reminders)
    lead = r"(?:okay\W+|ok\W+|so\W+|please\W+|kurama\W+|can\s+you\s+|could\s+you\s+|now\W+)*"
    from jarvis.core import pageread
    if pageread.waiting() and yes_no(t) == "no":
        return Intent("page", "page_summary", "browser", {"action": "cancel"})
    if pageread.waiting() and yes_no(t) == "yes":
        return Intent("page", "page_summary", "browser", {"action": "detail"})
    if pageread.waiting():  # "Want a detailed overview?" was just asked
        if re.fullmatch(r"(?:yes|yeah|yep|sure|ok(?:ay)?|please|go\s+ahead|do\s+it|haan|ho)(?:\W+(?:please|do\s+it|give\s+(?:it|me)|"
                        r"detail(?:ed)?(?:\s+overview)?|show\s+me))*|(?:give|show|write)\s+(?:me\s+)?(?:the\s+|a\s+)?(?:detail(?:ed)?|full)"
                        r"(?:\s+(?:overview|summary|version))?", low, I):
            return Intent("page", "page_summary", "browser", {"action": "detail"})
        if re.fullmatch(r"(?:no|nope|nah|not\s+now|no\s+thanks?|that'?s\s+(?:it|enough))", low, I):
            return Intent("page", "page_summary", "browser", {"action": "cancel"})
    if len(low.split()) <= 24 and re.search(r"\b(?:web\s*site|web\s*page|this\s+(?:page|site|tab|article)|current\s+(?:page|tab|site))\b", low) \
            and re.search(r"\b(?:about|showing|shows|summar|explain|overview|what|tell)\w*", low) \
            and not re.search(r"\b(?:link|save|store|bookmark|open|close|read\s+later|reading\s+list|qr|screenshot|copy|when|changes?|"
                              r"updates?|watch|monitor|notify|alert|https?)\b", low):
        return Intent("page", "page_summary", "browser", {"action": "summary"})
    # 'I already read the attention is all you need paper' = that reading-list link is done
    if (m := re.fullmatch(lead + r"i\s+(?:have\s+|had\s+)?(?:already\s+|just\s+)?(?:read|finished(?:\s+reading)?|completed|done\s+reading)\s+"
                          r"(?:the\s+)?(?P<x>.+?)(?:\s+(?:already|now|today))?", low, I)) and readlater.find(m.group("x")):
        return R("remove", text=m.group("x"))
    if (m := re.fullmatch(lead + r"(?:mark|set|tick)\s+(?:the\s+)?(?P<n>first|second|third|last|1st|2nd|3rd|\d{1,2})\s*(?:one|task|item|link|article)?"
                          r"\s+(?:in|on|from)\s+(?:my\s+|the\s+)?(?:read(?:ing)?[\s-]*later(?:\s+list)?|reading\s+list)\s+(?:as\s+)?(?:done|read|finished|complete(?:d)?)", low, I)):
        n = _nth(m.group("n"))
        return R("done", n=n if n > 0 else len(readlater.unread()))
    # 'add a task' was asked without details: this short reply is the task (with an optional due date)
    if todos.pending() and len(low.split()) <= 14 and not t.strip().endswith("?") and not re.match(
            r"(?:no|cancel|never\s*mind|stop|what|why|how|open|close|show)\b", low):
        extra, rest = _extras(t.strip(" .!"))
        task = re.sub(r"^(?:it'?s|it\s+is|to|for)\s+", "", rest.strip(" ,."), flags=I)
        if len(task) >= 2:
            return T("add", task=task, **_todo_extra(extra))
    if todos.pending() and re.match(r"(?:no|cancel|never\s*mind)\b", low):
        todos.clear_pending()
    # 'what's on today' = the whole day: to-dos, reminders, classes, long tasks
    if re.fullmatch(lead + r"(?:what(?:'s|\s+is)\s+(?:on\s+)?(?:for\s+)?today|what\s+(?:do\s+i\s+have|have\s+i\s+got)\s+today|"
                    r"(?:my|today'?s)\s+(?:plan|schedule|day)(?:\s+today)?|what(?:'s|\s+is)\s+(?:my|the)\s+(?:plan|schedule)\s+(?:for\s+)?today|"
                    r"how\s+(?:does|is)\s+my\s+day\s+look(?:ing)?)", low, I):
        return T("today")
    # remove everything: the to-do list or the reading list (reminders are cancelled one by one)
    if m := re.fullmatch(lead + r"(?:remove|delete|clear|cancel|erase|empty)\s+(?:all|every|everything)?\s*(?:of\s+)?(?:the\s+|my\s+)?"
                         r"(?P<k>tasks?|to[\s-]?dos?|to[\s-]?do\s*list|list|reading\s+list|read\s+later(?:\s+list)?)(?:\s+for\s+me)?", low, I):
        if re.search(r"\ball\b|\bevery|\bclear\b|\bempty\b|\blist\b", low):
            return R("clear", text="read") if re.search(r"read", m.group("k")) else T("clear")
    rm = r"(?:remove|delete|cancel|drop|forget|take|cross|strike|tick|clear|done|finish(?:ed)?|complete(?:d)?)"
    if m := re.fullmatch(lead + r"(?P<v>" + rm + r")\s+(?:off\s+|with\s+)?(?:the\s+|my\s+)?(?P<n>first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th|"
                         r"(?:number|no\.?|item)\s*\d{1,2}|\d{1,2})(?:\s+(?:one|task|item|reminder|to[\s-]?do|work))?(?P<tail>\s+(?:from|in|on|off)\s+.*)?", low, I):
        n = _nth(m.group("n"))
        if re.search(_RL_LIST, m.group("tail") or "", I):
            return R("done", n=n if n > 0 else len(readlater.ordered()))
        done = re.match(r"(?:done|finish|complete|tick)", m.group("v"))
        return T("done" if done else "delete", item=str(n if n > 0 else len(todos.items())))
    if m := re.fullmatch(lead + r"(?:no\W+)*(?:actually\W+)?" + rm + r"\s+(?:off\s+|out\s+)?(?:the\s+|my\s+)?(?P<x>.+?)\s+"
                         r"(?:from|off|out\s+of|in)\s+.*?\b(?P<k>to[\s-]?do(?:\s*list)?|list|tasks?|reminders?)\b.*", low, I):
        if m.group("k").startswith("reminder"):
            return S("cancel", item=m.group("x"))
        return T("delete", item=m.group("x"))
    if (m := re.fullmatch(lead + r"(?:no\W+)*(?:actually\W+)?" + rm + r"\s+(?:the\s+|my\s+)?(?P<x>.+?)(?:\s+(?P<k>task|reminder|to[\s-]?do|alarm))?", low, I)) \
            and not _LONG_WORDS.search(low):
        x = m.group("x")
        if m.group("k") not in ("reminder", "alarm") and todos.find(x):
            return T("done" if re.match(r"(?:done|finish|complete|tick)", low.split()[0] if low else "") else "delete", item=x)
        if reminders.named(x):
            return S("cancel", item=x)
    if (m := re.fullmatch(lead + r"(?:move|change|shift|reschedule|update|push|postpone|set)\s+(?:the\s+|my\s+)?(?P<x>.+?)(?:\s+(?P<k>task|reminder|to[\s-]?do|alarm))?"
                          r"\s+(?:to|for|at|till|until)\s+(?P<w>.+)", low, I)) and not _LONG_WORDS.search(low):
        from jarvis.core import when
        x, w = m.group("x"), m.group("w")
        if when.resolve(w, use_llm=False):
            if m.group("k") not in ("reminder", "alarm") and todos.find(x):
                return T("edit", item=x, due=w)
            if reminders.named(x):
                return S("move", item=x, when=w)
            if readlater.find(x):
                return R("reschedule", text=x, when=w)
    if m := re.fullmatch(lead + r"rename\s+(?:the\s+|my\s+)?(?P<x>.+?)(?:\s+(?P<k>task|reminder|to[\s-]?do))?\s+(?:to|as)\s+(?P<y>.+)", t.strip(" .!?"), I):
        x, y = m.group("x"), m.group("y")
        if (m.group("k") or "").lower() != "reminder" and todos.find(x):
            return T("edit", item=x, task=y)
        if reminders.named(x):
            return S("rename", item=x, text=y)
        if readlater.find(x):
            return R("rename", text=x + " » " + y)
    if (m := re.fullmatch(lead + r"(?:i\s+(?:have\s+)?(?:finished|completed|did|done)|i'?m\s+done\s+with|done\s+with|mark)\s+(?:the\s+)?(?P<x>.+?)"
                          r"(?:\s+as\s+(?:done|complete(?:d)?|finished))?", low, I)) and not re.search(r"\d", m.group("x")[:3]) \
            and todos.find(m.group("x")):
        return T("done", item=m.group("x"))
    # 'what's on my to-do', 'any task for me today' -> the to-do list; 'my reminders' -> the reminders; both -> the day
    if len(low.split()) <= 18 and re.search(r"\breminders?\b", low) and re.search(r"\b(?:tasks?|work|to[\s-]?dos?)\b", low) \
            and re.search(r"\b(?:show|what|tell|give|list|any)\b", low) and not re.search(r"\b(?:add|remove|delete|cancel|set)\b", low):
        return T("today")
    if re.fullmatch(lead + r"(?:what(?:'s|\s+is|\s+are)?\s+(?:my|the)\s+reminders?(?:\s+(?:for\s+)?today)?|(?:show|list|tell|give)\s+(?:me\s+)?"
                    r"(?:my\s+|the\s+|all\s+)?(?:reminders?|alarms?)(?:\s+(?:for\s+)?today)?|(?:is|are)\s+there\s+any\s+reminders?(?:\s+(?:today|for\s+me))?|"
                    r"(?:my\s+)?reminders?(?:\s+today)?)", low, I):
        return S("list")
    if re.fullmatch(lead + r"(?:"
                    r"(?:is|are)\s+there\s+(?:anything|something|any\s+(?:tasks?|work|to[\s-]?dos?))\s+(?:in|on|for)\s+(?:me\s+)?(?:my\s+|the\s+)?"
                    r"(?:to[\s-]?do(?:\s*list)?|list|today|now)(?:\s+(?:for\s+)?today)?"
                    r"|(?:is|are)\s+there\s+any\s+(?:tasks?|work|to[\s-]?dos?)(?:\s+for\s+me)?(?:\s+(?:today|now|left))?"
                    r"|what(?:'s|\s+is|\s+are)?\s+(?:in|on)\s+my\s+to[\s-]?do(?:\s*list)?(?:\s+today)?"
                    r"|what(?:'s|\s+is|\s+are)?\s+(?:my|the|today'?s)\s+(?:tasks?|to[\s-]?dos?)(?:\s+(?:for\s+)?today)?"
                    r"|what(?:'s|\s+is|\s+are)?\s+(?:the\s+)?(?:current\s+|next\s+)?(?:work|tasks?|things?)\s+(?:that\s+)?i\s+(?:have|need|got)\s+to\s+do(?:\s+(?:today|now|next))?"
                    r"|what\s+do\s+i\s+(?:have|need)\s+to\s+do(?:\s+(?:today|now|next))?"
                    r"|(?:show|tell|give)\s+(?:me\s+)?(?:my\s+|the\s+|today'?s\s+)?(?:tasks?|to[\s-]?dos?)(?:\s+(?:for\s+)?today)?"
                    r"|(?:my\s+)?(?:tasks?|to[\s-]?dos?)\s+(?:for\s+)?today)", low, I):
        return T("list")
    if len(low.split()) <= 12 and re.search(r"\b(?:tasks?|todos?|to-dos?|(?:my|any|the)\s+to\s+dos?)\b", low) and re.search(
            r"\b(?:any|anything|is\s+there|are\s+there|what|which|show|list|tell|have\s+i|do\s+i)\b", low) and not re.search(
            r"\b(?:long|code|coding|add|schedule|plan|remove|delete|clear|cancel|set|create|make|remind\s+me)\b", low):
        return T("list")
    if re.fullmatch(lead + r"(?:schedule|plan|add)\s+(?:a|the|my|one|new)?\s*(?:task|work|to[\s-]?do|thing)(?:\s+for\s+(?:me|the\s+task))?", low, I):
        return T("add", task="")  # asks what; the next short reply is the task
    # 'schedule reading the book at 11:45 pm' = an alert at that time: a reminder (a to-do never rings)
    m = re.fullmatch(r"(?:okay\W+|ok\W+|so\W+|please\W+|kurama\W+|can\s+you\s+|could\s+you\s+)*(?:schedule|plan)\s+(?P<x>.+)", low, I)
    if not m or _TD_CMD.search(m.group("x")) or re.search(r"\b(?:timer|alarm|meeting\s+with\s+kurama)\b", low):
        return None
    extra, rest = _extras(m.group("x"))
    if not extra.get("when"):
        return None
    task = re.sub(r"^(?:a|an|the|my|one)?\s*(?:new\s+)?(?:work|task|to[\s-]?do|job|thing|reminder)?\s*(?:for|to|of|:)?\s*", "", rest, flags=I)
    task = re.sub(r"\s+(?:for|to)\s*$", "", task, flags=I)
    task = re.sub(r"^(?:for|to)\s+", "", task.strip(" ,.-"), flags=I).strip(" ,.-")
    task = re.sub(r"\b(for|to)\s+\1\b", r"\1", task, flags=I)  # STT doubles: 'for for reading'
    task = re.sub(r"^\d+(?:-\d+)?\s+(?:tasks?|works?|things?)\s+(?:for|to)\s+", "", task, flags=I)  # '2-2 task for reading'
    task = re.sub(r"^(?:tasks?|works?)\s+(?:for|to)\s+", "", task, flags=I)
    if len(task) < 2:
        return None
    return Intent("remind", "add_reminder", "schedule", {"text": task, "when": extra["when"]}, task)


def _todo_extra(extra: dict) -> dict:
    """_extras() {'tag', 'when'} -> the todo tool's {'tag', 'due'}."""
    return {k: v for k, v in (("tag", extra.get("tag", "")), ("due", extra.get("when", ""))) if v}


# --- goals: long tasks (weeks-months): countdowns, daily check-ins, progress, report (0 tokens) ---
_G_NOUN = (r"exams?|tests?|finals|interview|deadline|submission|presentation|competition|trip|wedding|project|thesis|"
           r"course|semester|hackathon|internship|dissertation|goal|long[\s-]?(?:term\s+)?task|countdown")


_G_STOP = r"(?!(?:is|are|was|my|the|an?|our|will|and|to|in|on|of|that|which|for|it|i|starts?|ends?|after|within)\b)"


_G_PROGRESS = re.compile(
    r"(?:today\s*,?\s*|so\s+far\s*,?\s*)?(?:i|we)\s+(?:have\s+|had\s+|just\s+|only\s+)?(?:did|done|worked|finished|completed|"
    r"made|wrote|written|studied|learn(?:ed|t)|fixed|built|added|read|practi[cs]ed|started|spent|revised|solved|designed|"
    r"tested|deployed|coded|implemented|watched|attended|prepared|covered|reviewed|cleaned|planned|researched)\b"
    r"|(?:nothing|not\s+much|no\s+progress|didn'?t\s+do|i\s+didn'?t|i\s+could\s*n[o']t)\b", I)


_G_DEFAULT_Q = re.compile(r"(?:what|how)\b.*\b(?:do|doing|did|done|progress|going|work(?:ing|ed)?)\b", I)


def _goal(name: str):
    from jarvis.core import goals
    name = re.sub(r"\s+(?:goal|long\s+task|countdown|tracking)$", "", (name or "").strip(" ,.?!'"), flags=I)
    try:
        return goals.find(name) if name and len(name) <= 50 else None
    except Exception:
        return None


def _last_span(low: str) -> str:
    """'it's not 40 days, it's actually 30 days' -> 'in 30 days' (the LAST length/date said is the right one)."""
    spans = re.findall(r"\b\d{1,3}[\s-]*(?:days?|weeks?|months?|years?)\b", low)
    return f"in {spans[-1]}" if spans else low


def _goal_name(low: str, raw: str) -> str:
    m = re.search(r"(?:called|named|titled|(?:goal|long\s+task|project)\s*[:\-])\s*[\"']?(?P<n>[\w .'+#-]{2,40}?)[\"']?"
                  r"(?=\s*(?:,|\.|$|\s+(?:which|that|and|it|ends?|starts?|for|in|by|until|till|is|will)\b))", raw, I)
    if m:
        return m.group("n").strip()
    m = re.search(r"\b(?:my|an?|the|our)\s+(?P<n>(?:" + _G_STOP + r"[\w+#-]+\s+){0,3}?(?:" + _G_NOUN + r"))\b", low, I)
    n = m.group("n") if m else (re.search(r"\b(?:" + _G_NOUN + r")\b", low, I) or [""])[0]
    n = re.sub(r"^(?:new|big|long|long-term|upcoming|coming|next|own)\s+", "", n, flags=I)
    n = re.sub(r"\bexams\b", "exam", n, flags=I)
    return re.sub(r"\s*long[\s-]?(?:term\s+)?task$", "", n, flags=I) or "Goal"


_MONEYISH = re.compile(r"\b(?:spen[dt]|spending|expens\w*|expenc\w*|expecs\w*|money|budget|cost|costs|paid|rupees?|rs|"
                       r"income|salary|savings?|saved|kharcha|bills?)\b|खर्च", I)


_LONG_WORDS = re.compile(r"\b(?:long[\s-]?(?:term\s+)?(?:tasks?|works?|workers?|projects?)|goals?|monthly|countdowns?|"
                         r"(?:this|my|the|for\s+(?:the|my|this))\s+month)\b", I)


def goal_intent(t: str) -> Intent | None:
    """Long tasks only when the user says so: 'task / work / reminder' means the short to-do (owner). A sentence
    that names an item of the to-do list goes to the to-do unless 'long task / monthly / goal' is said."""
    i = _goal_intent(t)
    if i is None or i.args.get("action") in ("list", "add", "overview") or i.tool != "goals":
        return i
    low = t.strip(" .!?").lower()
    if _LONG_WORDS.search(low):
        return i
    from jarvis.core import reminders, todos
    if todos.find(low) or reminders.named(low) or re.search(r"\b(?:to[\s-]?do|reminders?|tasks?)\b", low):
        return None
    return i


def _goal_intent(t: str) -> Intent | None:
    """Long goals. 'my exam starts in 30 days, remind me every day', 'I started a project that ends in 6 months, ask
    me every day what I did', 'show my goals', 'how many days until my exam', 'what did we do today in the project',
    'Thesis update: wrote chapter 2', a plain 'today I fixed the login' right after a check-in question, 'move my
    exam to December 2', 'remind me about the exam twice a day', 'stop asking about the project', 'pause the X goal',
    'the exam is over', 'make the project report', 'link the project to this repo'."""
    from jarvis.core import goals
    low = t.strip(" .!?").lower()
    G = lambda a, **k: Intent("goals", "goals", "schedule", {"action": a, **k})  # noqa: E731
    # the Coding card's projects: list / pin / unpin / stop watching (the code itself is never deleted)
    if re.fullmatch(r"(?:show|list|what\s+are|which\s+are|give\s+me)?\s*(?:me\s+)?(?:all\s+)?(?:my\s+|the\s+)?(?:coding|code|git)\s+projects?"
                    r"(?:\s+(?:list|you\s+watch|you\s+track))?|which\s+projects?\s+(?:do\s+you|are\s+you)\s+(?:watch|track)\w*", low, I):
        return Intent("code", "time_machine", "git", {"action": "list"})
    if m := re.fullmatch(r"(?:pin|focus\s+on|always\s+show|show\s+only)\s+(?:the\s+|my\s+)?(?P<p>.+?)\s+(?:project|repo)(?:\s+on\s+the\s+coding\s+card)?"
                         r"|(?:my\s+)?main\s+(?:coding\s+)?project\s+is\s+(?P<p2>.+)", low, I):
        return Intent("code", "time_machine", "git", {"action": "pin", "project": m.group("p") or m.group("p2")})
    if re.fullmatch(r"unpin\s+(?:the\s+|my\s+)?(?:coding\s+)?project|(?:go\s+back\s+to\s+)?automatic\s+project", low, I):
        return Intent("code", "time_machine", "git", {"action": "unpin"})
    if re.fullmatch(r"(?:please\s+)?stop\s+(?:watching|tracking|looking\s+at|snapshotting)(?:\s+(?:a|the|my|this|that|some|all\s+the)?\s*(?:projects?|repos?|folders?))?", low, I):
        return Intent("code", "time_machine", "git", {"action": "forget", "project": ""})  # no name: show the list to pick from
    if m := re.fullmatch(r"(?:please\s+)?stop\s+(?:watching|tracking|looking\s+at)\s+(?:the\s+)?(?:project\s+)?(?:number\s+|no\.?\s*)?(?P<n>\d{1,2}|first|second|third|last)"
                         r"(?:\s+(?:one|project))?", low, I):
        return Intent("code", "time_machine", "git", {"action": "forget", "project": "#" + str(_nth(m.group("n")))})
    if m := re.fullmatch(r"(?:stop\s+(?:watching|tracking|looking\s+at)|forget|hide|remove|delete)\s+(?:the\s+|my\s+)?(?P<p>.+?)\s+(?:project|repo)"
                         r"(?:\s+from\s+(?:the\s+)?(?:coding(?:\s+card)?|list|kurama))?", low, I):
        return Intent("code", "time_machine", "git", {"action": "forget", "project": m.group("p")})
    if m := re.fullmatch(r"(?:watch|track)\s+(?:the\s+|my\s+)?(?P<p>.+?)\s+(?:project|repo)\s+again", low, I):
        return Intent("code", "time_machine", "git", {"action": "watch", "project": m.group("p")})
    # 'watch the project at ~/code/app', 'look at this project /media/.../X', 'start watching my KURAMA project', 'watch this project'
    if m := re.fullmatch(r"(?:please\s+)?(?:start\s+)?(?:watch(?:ing)?|track(?:ing)?|protect|monitor|look\s+at|keep\s+an\s+eye\s+on|snapshot)\s+"
                         r"(?:the\s+|my\s+|this\s+)?(?:(?:coding\s+)?(?:project|folder|repo)\s*)?(?:(?:at|in|from|called|named|:)\s+)?(?P<p>[~/].+|.+?)"
                         r"(?:\s+(?:project|folder|repo))?", t.strip(" .!?"), I):
        p = m.group("p").strip()
        if p.startswith(("/", "~")) or re.search(r"\b(?:project|folder|repo)\b", low):
            return Intent("code", "time_machine", "git", {"action": "protect", "project": "" if p.lower() in ("this", "it", "project", "this project") else p})
    # the CODE work (what you're doing in your project): 'code work for today', 'code worker', 'what do I have to do
    # in my code', 'related to code' -> where was I (git changes, errors, next step)
    if len(low.split()) <= 20 and (re.search(r"\b(?:code|coding|programming)\s+(?:work(?:er)?s?|tasks?|jobs?|progress|to[\s-]?dos?)\b", low)
                                   or re.search(r"\b(?:related\s+to|in|on|for)\s+(?:my\s+|the\s+)?(?:code|coding|project\s+code)\b", low)
                                   and re.search(r"\b(?:work|do|doing|task|left|pending|today)\b", low)) \
            and not re.search(r"\b(?:write|explain|fix|format|improve|review|run|test|commit|error)\b", low):
        return Intent("code", "where_was_i", "git", {})
    # an answer to the open check-in question
    if _G_PROGRESS.match(low) and len(low.split()) <= 80 and (w := goals.waiting()):
        return G("log", goal=w["id"], text=t.strip())
    # an explicit progress note: 'Thesis update: ...', 'update for the project: ...', 'today on KURAMA app, I ...'
    for rx in (r"(?P<g>[\w .'+#-]{2,40}?)\s+(?:update|progress|log)\s*[:\-–]\s*(?P<x>.+)",
               r"(?:progress\s+)?(?:update|log|note)\s+(?:for|on|to)\s+(?:the\s+|my\s+)?(?P<g>[\w .'+#-]{2,40}?)\s*[:\-–]\s*(?P<x>.+)",
               r"today\s+(?:in|on|for)\s+(?:the\s+|my\s+)?(?P<g>[\w .'+#-]{2,40}?)\s*,?\s+(?P<x>(?:i|we)\s+.+)"):
        if (m := re.fullmatch(rx, t.strip(), I)) and (g := _goal(m.group("g"))):
            return G("log", goal=g["id"], text=m.group("x").strip())
    if re.fullmatch(r"(?:please\s+)?(?:show|list|see|open|check|tell\s+me|what\s+are|what'?s|give\s+me)?\s*(?:me\s+)?(?:all\s+)?"
                    r"(?:my\s+|the\s+)?(?:goals?|long[\s-]?(?:term\s+)?tasks?|countdowns?)(?:\s+list)?", low, I):
        return G("list")
    # 'this month' is only a time: it means the long tasks only next to work words ('what do I have to do this month',
    # 'my tasks for the month'), never with money, weather, news... ('my spending this month' is the money tracker)
    month_work = re.search(r"\b(?:this|my|the|for\s+(?:the|my|this))\s+month\b", low) and re.search(
        r"\b(?:tasks?|works?|to\s+do|doing|plans?|planned|goals?|projects?|targets?|to[\s-]?dos?|deadlines?)\b", low)
    long_words = re.search(r"\bmonthly\s+(?:tasks?|work|goals?|targets?)\b|\blong[\s-]?(?:term\s+)?(?:tasks?|work(?:ers?)?|projects?)\b", low)
    if (month_work or long_words) and re.search(r"\b(?:what|which|show|list|tell|any|have\s+to|need\s+to|running)\b", low) \
            and len(low.split()) <= 18 and not goals.end_in(low) and not _MONEYISH.search(low):
        return G("list")
    # the whole Work card: 'what is in my working list right now? what project?', 'what am I working on'
    if len(low.split()) <= 22 and re.search(r"\b(?:what|show|tell|list|give|which|see|check)\b", low) and re.search(
            r"\b(?:work(?:ing)?\s+(?:list|card|section|board|plan)|my\s+work\b|working\s+on|on\s+my\s+plate|my\s+projects?|"
            r"what\s+projects?|which\s+projects?|my\s+goals?\s+and|everything\s+i\s+(?:have|need)\s+to\s+do)", low) \
            and not re.search(r"\b(?:about|explain|code|repo|function|files?|folders?|errors?|bug|git|commit|branch|ask\s+me|"
                              r"remind|was|were|last|yesterday|left\s+off)\b", low) and not goals.end_in(low):  # 'working on a project for 6 months, ask me' = new goal
        return G("overview")
    if m := re.fullmatch(r"how\s+many\s+(?:more\s+)?days\s+(?:are\s+|is\s+)?(?:left\s+|remaining\s+)?(?:until|till|to|before|for|in)\s+"
                         r"(?:my\s+|the\s+)?(?P<g>.+?)(?:\s+(?:left|remaining|now))?|when\s+is\s+(?:my\s+|the\s+)?(?P<g2>.+)", low, I):
        if g := _goal(m.group("g") or m.group("g2")):
            return G("status", goal=g["id"])
    if m := re.fullmatch(r"what\s+(?:did|have|has)\s+(?:we|i)\s+(?:do|done|did|work(?:ed)?\s+on|achieved?|finish(?:ed)?)\s+(?:today\s+|this\s+week\s+)?"
                         r"(?:in|on|for|with)\s+(?:the\s+|my\s+|this\s+|our\s+)?(?P<g>.+?)(?:\s+(?:today|so\s+far|till\s+now|until\s+now|"
                         r"this\s+week|yet))*|(?P<k>today'?s|daily|weekly|this\s+week'?s)\s+(?:summary|progress|update|report)\s+(?:of|for|on)\s+"
                         r"(?:the\s+|my\s+)?(?P<g2>.+)", low, I):
        if g := _goal(m.group("g") or m.group("g2")):
            return G("week" if re.search(r"week", low) else "today", goal=g["id"])
    if m := re.fullmatch(r"how\s+(?:is|are)\s+(?:my\s+|the\s+|our\s+)?(?P<g>.+?)\s+going|(?:my\s+|the\s+)?(?P<g2>.+?)\s+progress|"
                         r"(?:show\s+(?:me\s+)?)?(?:the\s+)?progress\s+(?:of|on|for)\s+(?:my\s+|the\s+)?(?P<g3>.+)", low, I):
        if g := _goal(m.group("g") or m.group("g2") or m.group("g3")):
            return G("status", goal=g["id"])
    if m := re.fullmatch(r"(?:please\s+)?(?:make|write|create|generate|prepare|give\s+me)\s+(?:the\s+|a\s+|my\s+)?(?:(?P<g>.+?)\s+)?"
                         r"(?:full\s+|final\s+|formatted\s+)?(?:report|documentation|document)(?:\s+(?:for|of|on)\s+(?:the\s+|my\s+)?(?P<g2>.+))?", low, I):
        n = m.group("g2") or m.group("g") or ""
        if n and (g := _goal(n)) and g["kind"] == "project":
            return G("report", goal=g["id"])
    if m := re.fullmatch(r"link\s+(?:the\s+|my\s+)?(?P<g>.+?)\s+(?:goal\s+)?(?:to|with)\s+(?:this\s+|my\s+|the\s+)?(?:git\s+)?"
                         r"(?:repo(?:sitory)?|git|code|coding\s+project|project\s+folder)", low, I):
        if g := _goal(m.group("g")):
            return G("link", goal=g["id"])
    # remove / delete / cancel a goal named anywhere in the sentence ('can we remove that 30 day exam routing')
    _FILEISH = r"\b(?:files?|folders?|photos?|pictures?|images?|pdfs?|docs?|documents?|trash|downloads?|screenshots?|videos?|songs?)\b|\.\w{2,4}\b"
    if re.search(r"\b(?:remove|delete|cancel|drop|clear|forget|erase|discard|get\s+rid\s+of|don'?t\s+need|no\s+longer\s+need)\b", low) \
            and not re.search(_FILEISH, low) and len(low.split()) <= 25 and _LONG_WORDS.search(low):
        g = goals.named_in(low) or (goals.last_touched() if re.search(r"\b(?:that|this|the)\s+(?:goal|countdown|long\s+task|"
                                                                        r"routine|tracking)\b", low) else None)
        if g:
            return G("delete", goal=g["id"])
    # postponed / moved: a new date -> change it, no date -> ask for it
    if re.search(r"\b(?:postponed?|delayed|pushed\s+back|rescheduled|shifted|moved|changed)\b", low) \
            and not re.search(r"\b(?:remove|delete|cancel|drop|clear|forget)\b", low) \
            and not re.search(_FILEISH, low) and (g := goals.named_in(low)):
        return G("edit", goal=g["id"], end=low) if goals.end_in(low) else G("postponed", goal=g["id"])
    # a correction right after adding/changing a goal: 'no, it's actually 30 days', 'make it 2 months'
    if len(low.split()) <= 25 and re.search(r"\b(?:not|actually|sorry|no|wrong|mistake|instead|make\s+it|change\s+it|set\s+it|"
                                            r"it'?s|it\s+is)\b", low) and goals.end_in(low) and (g := goals.last_touched()):
        other = goals.named_in(low)
        if not (re.search(r"\b(?:" + _G_NOUN + r")\b", low, I) and (not other or other["id"] != g["id"])):
            return G("edit", goal=g["id"], end=_last_span(low))  # (a different goal named = a new goal, not a fix)
    # changes to an existing goal
    if m := re.fullmatch(r"(?:please\s+)?(?:move|change|shift|push|postpone|set)\s+(?:the\s+|my\s+)?(?P<g>.+?)(?:'s)?\s+(?:date\s+|deadline\s+|"
                         r"end\s+date\s+)?to\s+(?P<d>.+)|(?:my\s+|the\s+)?(?P<g2>.+?)\s+(?:is\s+now|has\s+moved\s+to|moved\s+to|is\s+moved\s+to|"
                         r"date\s+is\s+now)\s+(?:on\s+)?(?P<d2>.+)", low, I):
        d = m.group("d") or m.group("d2")
        if goals.end_in(d) and (g := _goal(m.group("g") or m.group("g2"))):
            return G("edit", goal=g["id"], end=d)
    if m := re.fullmatch(r"(?:please\s+)?remind\s+me\s+(?:about|of|for)\s+(?:the\s+|my\s+)?(?P<g>.+?)\s+(?P<r>(?:only\s+)?(?:once|twice|thrice|"
                         r"\w+\s+times?|at\s+).*)", low, I):
        if goals.times_in(m.group("r")) and (g := _goal(m.group("g"))):
            return G("edit", goal=g["id"], remind=m.group("r"))
    if m := re.fullmatch(r"(?:please\s+)?(?:stop|turn\s+off|disable|no\s+more|cancel)\s+(?:the\s+|my\s+|all\s+)?(?P<g>.+?)\s+(?:reminders?|messages?|"
                         r"countdown)(?:\s+(?:please|now))?", low, I):
        if g := _goal(m.group("g")):
            return G("edit", goal=g["id"], remind="off")
    if m := re.fullmatch(r"(?:please\s+)?(?:stop|don'?t|do\s+not|no\s+need\s+to)\s+ask(?:ing)?\s+(?:me\s+)?(?:about\s+)?(?:the\s+|my\s+)?(?P<g>.+?)"
                         r"(?:\s+(?:any\s*more|every\s*day|daily))*", low, I):
        if g := _goal(m.group("g")):
            return G("edit", goal=g["id"], ask="off")
    if (m := re.fullmatch(r"(?:please\s+)?ask\s+me\s+about\s+(?:the\s+|my\s+)?(?P<g>.+?)\s+(?:every\s*day\s+|daily\s+)?(?P<r>at\s+.+)", low, I)) \
            and not goals.end_in(low) and goals.times_in(m.group("r")) and (g := _goal(m.group("g"))):
        return G("edit", goal=g["id"], ask_at=m.group("r"))
    if m := re.fullmatch(r"(?:please\s+)?(?P<a>pause|resume|restart|unpause|continue|delete|remove|finish|complete|end|stop)\s+(?:the\s+|my\s+)?"
                         r"(?P<g>.+?)\s+(?:goal|long\s+task|countdown|tracking)|(?:my\s+|the\s+)?(?P<g2>.+?)\s+(?:is|are)\s+(?:done|finished|over|"
                         r"complete(?:d)?|cancel(?:led|ed))(?:\s+now)?", low, I):
        if g := _goal(m.group("g") or m.group("g2")):
            a = (m.group("a") or "done").lower()
            a = {"pause": "pause", "resume": "resume", "restart": "resume", "unpause": "resume", "continue": "resume",
                 "delete": "delete", "remove": "delete"}.get(a, "done")
            return G(a, goal=g["id"])
    # a new goal: a long-task word + an end date ('in 30 days', 'for 6 months', 'on November 28')
    if not re.search(r"\b(?:" + _G_NOUN + r")\b", low, I) and not re.search(
            r"\b(?:ask|remind)\s+me\s+(?:every\s*day|daily)\b.*\bdays?\s+(?:left|remaining)\b", low, I):
        return None
    end = goals.end_in(low)
    if not end or re.match(r"(?:how|when|what|which|is|are|do|does)\b", low) or t.strip().endswith("?"):
        return None
    if not re.search(r"\b(?:remind|ask|track|countdown|count\s+down|goal|notify|message|tell\s+me|keep|report|document|"
                     r"start|create|add|new|set\s+up|follow)", low, I):
        return None  # 'I have an interview in 2 weeks' is just talk
    if re.search(r"\bremind\s+me\s+to\b", low, I) and not re.search(r"\bevery\s*day|daily|each\s+day|countdown|days?\s+left\b", low, I):
        return None  # 'remind me to submit the project in 3 days' = one reminder
    if m := re.search(r"\bask\s+me\s+(?:every\s*day|daily|each\s+day|every\s+evening|every\s+night)?\s*(?:,\s*)?(?P<q>.*?)(?=[,.;]|\s+and\s+(?:remind|make|send|write)|$)", low, I):
        q = m.group("q").strip()
        if q and not _G_DEFAULT_Q.search(q) and not re.fullmatch(r"(?:about\s+(?:it|this|the\s+progress)|at\s+.+)", q, I):
            return None  # a custom question: the AI words it (goals tool via the router)
    args: dict = {"name": _goal_name(low, t), "end": end.isoformat()}
    ask = re.search(r"\bask\s+me\b|\bcheck\s+(?:in|on)\s+(?:with\s+)?me\b|\breport\b|\bdocument", low, I)
    if ask:
        args["ask"] = "yes"
    for clause in re.split(r"[,.;]|\s+and\s+(?=(?:also\s+)?(?:ask|remind|make|write|send|keep|check)\b)", low):
        if re.search(r"\bask\b|\bcheck\s+in\b", clause) and (tt := goals.times_in(clause)):
            args["ask_at"] = tt[0]
        elif re.search(r"\bremind|\bmessage|\bnotif|\btimes?\s+a\s+day|\bonce\b|\btwice\b", clause) and goals.times_in(clause):
            args["remind"] = clause
    return G("add", **args)


_RL_CUE = r"(?:read(?:ing)?\s*later|reading\s+list|for\s+later|to\s+read\s+later)"


_TODO = r"(?:to[\s-]?do|todo)(?:\s*list)?"


_LIST_ANY = r"(?:" + _RL_LIST + r"|(?:to[\s-]?do|todo)\s*list|my\s+list|task\s+list)"


_MONS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"


_WHEN_BIT = re.compile(
    r"\b(?:(?:in|after)\s+(?:\d+(?:\.\d+)?|an?|one|two|three|four|five|six|ten|fifteen|twenty|thirty|half\s+an?)\s*"
    r"(?:min(?:ute)?s?|hours?|hrs?|days?)\b|day\s+after\s+tomorrow|tomorrow|tonight|today"
    r"|(?:at|by|around)\s+\d{1,2}(?:[:.]\d\d)?(?:\s*(?:am|pm|a\.m\.|p\.m\.))?|\d{1,2}(?:[:.]\d\d)?\s*(?:am|pm|a\.m\.|p\.m\.)"
    r"|(?:on\s+)?" + _MONS + r"\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+20\d\d)?|(?:on\s+)?(?:the\s+)?\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONS
    + r"|(?:on\s+|next\s+|this\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"|(?:this|in\s+the)\s+(?:morning|afternoon|evening)|at\s+night)\b", I)


_TAG = re.compile(r"(?:\s+(?:with\s+(?:the\s+)?)?(?:tag(?:ged)?|label(?:led)?)\s+(?:as\s+|it\s+)?#?(?P<t>[\w-]{2,20})"
                  r"|\s*#(?P<t2>[a-z][\w-]{1,20}))", I)


def _take_tag(t: str) -> tuple[str, str]:
    m = _TAG.search(t)
    if not m:
        return "", t
    return (m.group("t") or m.group("t2")).lower(), (t[:m.start()] + t[m.end():]).strip()


def _take_when(t: str) -> tuple[str, str]:
    """'... after 2 hours' / 'at 2 pm' / 'tomorrow 2 pm' / 'November 28, 5 PM' -> (when text, the rest)."""
    hits = list(_WHEN_BIT.finditer(t))
    if not hits:
        return "", t
    a, b = hits[0].start(), hits[-1].end()
    phrase = t[a:b].strip(" ,")
    from jarvis.core import when
    if when.resolve(phrase, use_llm=False) is None:
        return "", t
    rest = (t[:a] + " " + t[b:]).strip()
    rest = re.sub(r"\s+(?:and\s+)?(?:i\s+(?:will|can|'ll|want\s+to|need\s+to)|i'll|remind\s+me\s+to|to)\s+(?:read|do|check)"
                  r"(?:\s+(?:this|it|that))?(?:\s+(?:link|page|article))?\s*$", "", rest, flags=I)
    return phrase, " ".join(rest.split()).strip(" ,.")


def _extras(t: str) -> tuple[dict, str]:
    tag, t = _take_tag(t)
    w, t = _take_when(t)
    return {k: v for k, v in (("tag", tag), ("when", w)) if v}, t


def todo_intent(t: str) -> Intent | None:
    """To-do list (its own list, not the reading list): add (with tag/due date, 'and remind me' = a linked reminder),
    show, done N."""
    low = t.strip(" .!?")
    # done / complete: 'done 2', 'mark 2 as done', 'I finished number 3', 'complete 1 from my list', 'tick 2'
    if re.fullmatch(r"(?:please\s+)?(?:(?:mark|set)\s+(?:number\s+|item\s+|no\.?\s*)?\d{1,3}\s+(?:as\s+)?(?:done|complete(?:d)?|finished|read)"
                    r"|(?:done|complete|completed|finished|tick|check\s+off)\s+(?:with\s+)?(?:number\s+|item\s+|no\.?\s*)?\d{1,3}"
                    r"|i\s+(?:have\s+)?(?:finished|completed|did|done)\s+(?:number\s+|item\s+|no\.?\s*)?\d{1,3}"
                    r"|(?:number\s+|item\s+)?\d{1,3}\s+is\s+(?:done|complete(?:d)?|finished))"
                    r"(?:\s+(?:in|on|from)\s+(?:my\s+|the\s+)?" + _LIST_ANY + r")?", low, I):
        if re.search(_RL_LIST + r"|\bread\b", low, I):
            return Intent("readlater", "read_later", "links", {"action": "done", "n": _nth(low)})
        return Intent("todo", "todo", "todo", {"action": "done", "item": str(_nth(low))})
    if re.fullmatch(r"(?:please\s+)?(?:remove|delete)\s+(?:number\s+|item\s+)?\d{1,3}\s+(?:from|in|on)\s+(?:my\s+|the\s+)?" + _LIST_ANY, low, I):
        if re.search(_RL_LIST, low, I):
            return Intent("readlater", "read_later", "links", {"action": "remove", "n": _nth(low)})
        return Intent("todo", "todo", "todo", {"action": "delete", "item": str(_nth(low))})
    # show
    if m := re.fullmatch(r"(?:please\s+|kurama\W+)*(?:show(?:\s+me)?|what(?:'s|\s+is|\s+are)?(?:\s+(?:on|in))?|list|open|see|check|give\s+me|read)?"
                         r"\s*(?:all\s+)?(?:my\s+|the\s+)?(?P<k>" + _TODO + r"|list|tasks|task\s+list)(?:\s+items?)?(?P<x>(?:\s+(?:for\s+)?today|"
                         r"\s+(?:tagged|with\s+tag|for)\s+#?[\w-]+|\s*#[\w-]+)?)", low, I):
        tag = re.search(r"#?([\w-]+)$", m.group("x").strip()).group(1).lower() if m.group("x").strip() and \
            not m.group("x").strip().endswith("today") else ""
        k = m.group("k").lower()
        if (k == "list" or not re.search(r"list|todo|-", k)) and not re.search(r"\bmy\b", low):
            return None  # 'what to do' is a question, 'my to do' / 'to-do list' is the list
        return Intent("todo", "todo", "todo", {"action": "list"} | ({"tag": tag} if tag else {}))
    # add
    m = (re.fullmatch(r"(?:please\s+|kurama\W+|can\s+you\s+)*(?:add|put|save|note|write|keep|include)\s+(?:down\s+)?(?P<x>.+?)\s+"
                      r"(?:to|in|on|into|onto)\s+(?:my\s+|the\s+)?" + _TODO + r"(?P<r>.*)", low, I)
         or re.fullmatch(r"(?:please\s+|kurama\W+)*(?:add|new|create|make)\s+(?:a\s+)?(?:new\s+)?(?:to[\s-]?do|todo)(?:\s+item)?\s*[:,-]?\s+(?P<x>.+?)(?P<r>)", low, I)
         or re.fullmatch(r"(?:to[\s-]?do|todo)\s*:\s*(?P<x>.+?)(?P<r>)", low, I))
    if m:
        body = m.group("x") + " " + m.group("r")
        remind = re.search(r"\b(?:and\s+)?remind\s+me\b(?P<w>.*)$", body, I)  # '... and remind me Thursday at 6'
        if remind:
            body = body[:remind.start()]
        extra, task = _extras(body)
        task = re.sub(r"^(?:a\s+(?:task|reminder)\s+(?:to\s+)?|to\s+)", "", task, flags=I).strip(" ,.")
        pr = "high" if re.search(r"\b(?:urgent|important|high\s+priority|asap)\b", task, I) else ""
        task = re.sub(r"[\s,]*\b(?:it'?s\s+)?(?:urgent|important|high\s+priority|asap)\b", "", task, flags=I).strip(" ,.")
        if task:
            args = {"action": "add", "task": task, **_todo_extra(extra)} | ({"priority": pr} if pr else {})
            if remind:
                args["remind"] = (remind.group("w").strip(" ,.") or extra.get("when", "")).strip()
            return Intent("todo", "todo", "todo", args)
    return None


def read_later_intent(t: str) -> Intent | None:
    """'read this later', 'I will read this later', 'save this link for later', 'add this to my reading list',
    'can you keep this link for read later', 'give me the read later link I gave you', 'what's on my reading list',
    'open the first article from my reading list', 'mark 2 as read'. A time ('save this to read later, I'll read it
    after 2 hours / at 2 pm / tomorrow 2 pm / November 28 5 pm') and a tag (#work) are passed on."""
    if td := todo_intent(t):
        return td
    if re.search(_RL_CUE, t, I) and len(t.split()) <= 24:
        if re.search(r"\b(?:give|show|tell|send|what(?:'s|\s+is|\s+was)|which|where)\b.{0,40}\b(?:link|links|url|page|article)\b"
                     r"|\b(?:link|links|url)\b.{0,30}\b(?:i\s+(?:gave|give|saved|save|added|kept)|you\s+saved)\b", t, I):
            return Intent("readlater", "read_later", "links", {"action": "last" if not re.search(
                r"\b(?:links|all|list|everything)\b", t, I) else "list"})
        if re.search(r"\b(?:keep|save|store|add|put|bookmark|remember|note)\b", t, I) and not re.search(
                r"\b(?:open|show|remove|delete|mark)\b", t, I):
            u = URL_RE.search(t)
            extra, _ = _extras(URL_RE.sub(" ", t))
            return Intent("readlater", "read_later", "links", {"action": "add", "url": u.group(0) if u else "", **extra})
    plain = URL_RE.sub(" ", t)
    extra, rest = _extras(plain)
    if re.fullmatch(r"(?:please\s+|kurama\W+)*(?:i(?:'ll|\s+will)\s+read\s+(?:this|it|that)(?:\s+(?:link|page|article|post|video))?\s+later|"
                    r"read\s+(?:this|it|that)(?:\s+(?:link|page|article|post|video))?\s+later|"
                    r"(?:save|keep|bookmark|add)\s+(?:this|that|it|the|these)?\s*(?:link|links|page|article|tab|post|video)?\s*"
                    r"(?:for\s+later|to\s+(?:my\s+)?" + _RL_LIST + r"|(?:to\s+)?read\s+later)|read\s+later)[\s.!]*", t, I) or (
            extra.get("when") and re.fullmatch(
                r"(?:please\s+|kurama\W+)*(?:(?:i(?:'ll|\s+will|\s+want\s+to)|let\s+me|remind\s+me\s+to)\s+)?read\s+(?:this|it|that)"
                r"(?:\s+(?:link|page|article|post|video))?(?:\s+later)?[\s.!]*", rest, I)):
        u = URL_RE.search(t)
        return Intent("readlater", "read_later", "links", {"action": "add", "url": u.group(0) if u else "", **extra})
    if not re.search(_RL_LIST, t, I):
        return None
    if re.search(r"\b(?:open|read|show\s+me\s+the)\b.*\b(?:article|link|item|page|one|number|\d)\b", t, I):
        return Intent("readlater", "read_later", "links", {"action": "open", "n": _nth(t)})
    if re.search(r"\bmark\b.*\bread\b|\b(?:done|finished)\s+(?:with|reading)\b", t, I):
        return Intent("readlater", "read_later", "links", {"action": "done", "n": _nth(t)})
    if re.search(r"\b(?:remove|delete)\b", t, I):
        return Intent("readlater", "read_later", "links", {"action": "remove", "n": _nth(t)})
    if re.search(r"\b(?:show|what|list|open|see|check|my)\b", t, I) and len(t.split()) <= 12:
        return Intent("readlater", "read_later", "links", {"action": "list", "text": "read"})
    return None
    if re.search(r"\b(?:open|read|show\s+me\s+the)\b.*\b(?:article|link|item|page|one|number|\d)\b", t, I):
        return Intent("readlater", "read_later", "links", {"action": "open", "n": _nth(t)})
    if re.search(r"\bmark\b.*\bread\b|\b(?:done|finished)\s+(?:with|reading)\b", t, I):
        return Intent("readlater", "read_later", "links", {"action": "read", "n": _nth(t)})
    if re.search(r"\b(?:remove|delete)\b", t, I):
        return Intent("readlater", "read_later", "links", {"action": "remove", "n": _nth(t)})
    if re.search(r"\b(?:show|what|list|open|see|check|my)\b", t, I) and len(t.split()) <= 12:
        return Intent("readlater", "read_later", "links", {"action": "list"})
    return None
