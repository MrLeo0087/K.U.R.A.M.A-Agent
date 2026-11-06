"""Slash commands: one short word instead of a sentence = no routing, no LLM, 0 tokens.

Every command maps either to a plain phrase the fast path already understands ('/weather pokhara' -> 'weather in
pokhara') or straight to a tool call. The same list feeds /list (desktop + Telegram), Telegram's '/' menu and the
chat box suggestions (GET /api/v1/slash). A typo ('/wether') is matched to the closest command.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Cmd:
    name: str
    desc: str
    cat: str
    hint: str = ""  # what may follow: '<place>', '[minutes]'
    phrase: str = ""  # '{a}' = the text after the command; 'x|y' = without | with text
    tool: tuple = ()  # (tool, group, args, name of the arg that gets the text)
    aliases: tuple = field(default=())
    template: str = ""  # the text arg built from the typed text: 'a poem about {a}'
    actions: tuple = ()  # a tool's own action words: '/backup run' -> action=run


def _git_repo() -> str:
    from jarvis.core import timemachine
    p = timemachine.vscode_folder()
    return str(p) if p else "."


CATS = ("Day", "Laptop", "Phone & safety", "Code", "Media", "Web & text", "KURAMA")


def _c(name: str) -> tuple:
    return ("_cmd", "self", {"cmd": name}, "")
COMMANDS: tuple[Cmd, ...] = (
    # --- day to day ---
    Cmd("time", "the time now", "Day", "[city]", phrase="what time is it|what time is it in {a}"),
    Cmd("date", "today's date (Nepali BS)", "Day", "[ad]", phrase="what is the date today|what is the date today in {a}"),
    Cmd("weather", "weather now", "Day", "[place]", phrase="weather|weather in {a}"),
    Cmd("today", "what's on today: to-do, reminders, classes", "Day", phrase="what is on today"),
    Cmd("todo", "my to-do list, or add one", "Day", "[task]", phrase="show my to-do list|add {a} to my to-do list"),
    Cmd("list", "every command (this list)", "KURAMA", aliases=("help", "commands", "menu")),
    Cmd("remind", "remind me", "Day", "<what> <when>", phrase="show my reminders|remind me to {a}"),
    Cmd("timer", "start a timer", "Day", "<minutes>", phrase="timer 5 minutes|timer {a} minutes"),
    Cmd("alarm", "set an alarm", "Day", "<time>", phrase="set an alarm for {a}"),
    Cmd("goals", "my long tasks", "Day", phrase="show my long tasks", aliases=("long",)),
    Cmd("links", "my saved links", "Day", "[name]", phrase="show my saved links|give me the link of my {a}"),
    Cmd("notes", "my study notes", "Day", "[subject]", phrase="show my notes|show my {a} notes"),
    Cmd("contacts", "my contacts", "Day", phrase="show my contacts"),
    Cmd("timetable", "today's classes", "Day", phrase="show my timetable"),
    Cmd("quiz", "a quiz question from my notes", "Day", "[subject]", tool=("quiz", "study", {"action": "ask"}, "subject")),
    Cmd("focus", "focus session (DND on)", "Day", "[minutes]", tool=("focus_mode", "desktop", {"action": "start", "minutes": 25}, "minutes")),
    Cmd("digest", "summary of my day", "Day", phrase="summarize my day"),
    Cmd("spent", "add an expense", "Day", "<amount> <what>", phrase="|spent {a}", aliases=("expense",)),
    Cmd("money", "spending report", "Day", "[today|week|month|year]",
        phrase="how much did I spend this month|how much did I spend {a}", aliases=("expenses",)),
    Cmd("spending", "every category + budgets this month", "Day", "[week|month|year]",
        phrase="spending breakdown by category this month|spending breakdown by category {a}", aliases=("categories",)),
    Cmd("budget", "set the monthly budget", "Day", "<amount> or <category> <amount>", phrase="|set budget {a}"),
    Cmd("habits", "my habits and streaks", "Day", phrase="my habits", aliases=("habit", "streaks")),
    Cmd("done", "check in a habit", "Day", "<habit>", phrase="|{a} done"),
    Cmd("brief", "my morning brief now", "Day", phrase="give me my morning brief"),
    # --- laptop ---
    Cmd("status", "what's going on right now", "Laptop", phrase="status"),
    Cmd("battery", "battery level", "Laptop", phrase="battery", aliases=("bat",)),
    Cmd("doctor", "why is my laptop slow", "Laptop", phrase="why is my laptop slow", aliases=("slow",)),
    Cmd("ram", "RAM / CPU check", "Laptop", tool=("laptop_doctor", "system", {"action": "check"}, "")),
    Cmd("freeram", "free RAM (stops idle notebooks, asks first)", "Laptop", phrase="free up some ram"),
    Cmd("shutdown", "shut down now, or later: /shutdown 30min, /shutdown 2hrs, /shutdown at 11 pm, /shutdown cancel",
        "Laptop", "[time|cancel|status]", phrase="shutdown|shutdown {a}"),
    Cmd("restart", "restart now, or later: /restart 1hr, /restart cancel", "Laptop", "[time|cancel]",
        phrase="restart|restart {a}", aliases=("reboot",)),
    Cmd("clean", "clean RAM / storage / KURAMA (safe, offline)", "Laptop", hint="ram|storage|kurama",
        tool=("cleanup", "system", {"action": "ram"}, "action")),
    Cmd("ports", "programs using ports", "Laptop", "[port]", phrase="show my open ports|what is running on port {a}",
        aliases=("port",)),
    Cmd("screenshot", "take a screenshot", "Laptop", phrase="take a screenshot", aliases=("ss", "screen")),
    Cmd("lockscreen", "lock the screen", "Laptop", phrase="lock the screen"),
    Cmd("vol", "volume up / down / 0-100", "Laptop", "<up|down|N>", phrase="volume up|volume {a}", aliases=("volume",)),
    Cmd("bright", "brightness up / down / 0-100", "Laptop", "<up|down|N>", phrase="brightness up|brightness {a}",
        aliases=("brightness",)),
    Cmd("dark", "dark mode", "Laptop", phrase="dark mode"),
    Cmd("light", "light mode", "Laptop", phrase="light mode"),
    Cmd("dnd", "do not disturb on / off", "Laptop", "[on|off]", phrase="do not disturb on|do not disturb {a}"),
    Cmd("aod", "always-on display: keep the screen on (on / off; alone = status)", "Laptop", "[on|off]",
        phrase="what is the status of always on display|turn {a} always on display", aliases=("caffeine", "awake")),
    Cmd("internet", "check / fix the internet", "Laptop", phrase="check my internet", aliases=("net", "wifi")),
    Cmd("clip", "clipboard history", "Laptop", phrase="show the clipboard history"),
    Cmd("jobs", "background jobs", "Laptop", tool=("jobs", "jobs", {"action": "list"}, "")),
    Cmd("tokens", "today's token use", "KURAMA", phrase="token usage"),
    Cmd("clearchat", "clear this conversation", "KURAMA", tool=_c("clearchat"), aliases=("new",)),
    Cmd("clear", "clear chat + reminders (asks first); /clear ram | storage | kurama cleans that", "KURAMA",
        "[yes|ram|storage|kurama]", tool=_c("clear")),
    Cmd("reset", "wipe everything (Settings or Telegram)", "KURAMA", tool=_c("reset")),
    Cmd("stop", "stop a stuck answer", "KURAMA", tool=_c("stop")),
    # --- the Telegram commands, on the laptop too ---
    Cmd("camera", "a photo from the laptop camera (to the workspace)", "Phone & safety", tool=_c("camera"), aliases=("photo",)),
    Cmd("video", "a short camera clip, e.g. /video 8", "Phone & safety", "[seconds]", tool=_c("video"), aliases=("rec", "record")),
    Cmd("where", "where the laptop is (map link)", "Phone & safety", tool=_c("where"), aliases=("locate",)),
    Cmd("here", "name this place, e.g. /here home", "Phone & safety", "[name]", tool=_c("here")),
    Cmd("history", "where the laptop/phone has been", "Phone & safety", "[laptop|phone] [hours]", tool=_c("history"),
        aliases=("trail",)),
    Cmd("guard", "anti-theft guard on / off / status", "Phone & safety", "[on|off]", tool=_c("guard")),
    Cmd("track", "lost mode on / off", "Phone & safety", "[on|off]", tool=_c("track")),
    Cmd("mute", "pause alerts, e.g. /mute ram 20", "Phone & safety", "[what] [minutes]", tool=_c("mute")),
    Cmd("unmute", "alerts back on", "Phone & safety", "[what]", tool=_c("unmute")),
    Cmd("notifications", "which alerts are on / paused", "Phone & safety", tool=_c("notifications"), aliases=("muted",)),
    Cmd("clipnow", "what's on the clipboard now", "Phone & safety", tool=_c("clipnow")),
    Cmd("control", "remote desktop (password on Telegram only)", "Phone & safety", tool=_c("control")),
    Cmd("changepass", "new remote password (Telegram only)", "Phone & safety", tool=_c("changepass")),
    Cmd("lock", "block risky Telegram commands (Telegram only)", "Phone & safety", tool=_c("lock")),
    Cmd("unlock", "unlock Telegram after /lock (Telegram only)", "Phone & safety", "<pin>", tool=_c("unlock")),
    # --- code ---
    Cmd("def", "open where the highlighted function is defined", "Code", "[name]",
        tool=("code_nav", "codequality", {"action": "find"}, "name"), aliases=("goto",)),
    Cmd("args", "arguments of the highlighted call + is it right", "Code", "[name]",
        tool=("code_nav", "codequality", {"action": "help"}, "name"), aliases=("lib", "syntax")),
    Cmd("run", "run the highlighted code", "Code", tool=("code_nav", "codequality", {"action": "run"}, ""),
        aliases=("exec",)),
    Cmd("explain", "explain the highlighted code / text", "Code", phrase="explain this"),
    Cmd("format", "format the file open in VS Code", "Code", phrase="format this file"),
    Cmd("check", "lint the file open in VS Code", "Code", phrase="check this file", aliases=("lint",)),
    Cmd("code", "where was I (coding)", "Code", phrase="where was I", aliases=("wherewasi",)),
    Cmd("projects", "my watched coding projects", "Code", phrase="list my coding projects"),
    Cmd("git", "git status of the VS Code project", "Code",
        tool=("git_info", "git", {"action": "status", "repo": _git_repo}, "")),
    # --- media ---
    Cmd("play", "play / continue the video or song", "Media", aliases=("resume", "continue")),
    Cmd("pause", "pause it", "Media"),
    Cmd("next", "next track", "Media", aliases=("skip",)),
    Cmd("prev", "previous track", "Media", aliases=("previous", "back")),
    Cmd("music", "music without the browser (sound only)", "Media", "[what]", phrase="play some music|play {a} music"),
    Cmd("stopmusic", "stop the music", "Media", tool=("music", "media", {"action": "stop"}, "")),
    Cmd("playlists", "my saved playlists", "Media", tool=("music", "media", {"action": "playlists"}, "")),
    Cmd("mymusic", "the songs in ~/Music (offline)", "Media", tool=("music", "media", {"action": "local"}, "")),
    Cmd("yt", "play something on YouTube", "Media", "<what>", phrase="open youtube|play {a} on youtube",
        aliases=("youtube",)),
    Cmd("image", "make a picture", "Media", "<prompt>", phrase="generate an image of {a}", aliases=("img",)),
    Cmd("chart", "charts of my spending, a file or a data link", "Media", "[file|link]",
        phrase="chart my expenses this month|make a chart from {a}", aliases=("graph",)),
    Cmd("diagram", "diagram of the VS Code project (from its README)", "Code", "[project]",
        tool=("make_diagram", "image", {"kind": "project"}, "target")),
    Cmd("flow", "flowchart of steps", "Code", "<step, step, step>", tool=("make_diagram", "image", {"kind": "flow"}, "target"),
        aliases=("flowchart",)),
    Cmd("callgraph", "who calls whom in the open Python file", "Code", tool=("make_diagram", "image", {"kind": "code"}, "target")),
    Cmd("audio", "MP3 of the highlighted text / a link / a file", "Media", "[link|file|text]", aliases=("mp3",)),
    Cmd("makevideo", "short narrated video about a topic", "Media", "<topic>", aliases=()),
    Cmd("reel", "vertical short video (reel)", "Media", "<topic>"),
    Cmd("download", "download a video / audio", "Media", "<link>", phrase="download this video|download {a}",
        aliases=("dl",)),
    # --- web & text ---
    Cmd("search", "search the web", "Web & text", "<words>", tool=("web_search", "web", {}, "query"), aliases=("s",)),
    Cmd("news", "latest news", "Web & text", "[topic]", tool=("live_search", "web", {"kind": "news", "query": "latest news"}, "query")),
    Cmd("wiki", "Wikipedia", "Web & text", "<topic>", tool=("wikipedia", "web", {}, "topic")),
    Cmd("page", "what is this web page about", "Web & text", phrase="what is this page about"),
    Cmd("translate", "translate the highlighted text", "Web & text", "[nepali|hindi|english]",
        phrase="translate this to nepali|translate this to {a}", aliases=("tr",)),
    Cmd("meaning", "meaning of the highlighted word", "Web & text", "[word]",
        phrase="meaning of this word|what is the meaning of {a}"),
    Cmd("summary", "summary of the highlighted text", "Web & text", phrase="summary of this paragraph"),
    Cmd("calc", "calculate", "Web & text", "<sum>", phrase="calculate {a}"),
    # writing: straight to the writer (a background job), no routing / planning call
    Cmd("poem", "write a poem", "Web & text", "<topic>", tool=("write_document", "jobs", {}, "request"),
        template="a poem about {a}"),
    Cmd("essay", "write an essay", "Web & text", "<topic>", tool=("write_document", "jobs", {}, "request"),
        template="an essay about {a}"),
    Cmd("story", "write a story", "Web & text", "<topic>", tool=("write_document", "jobs", {}, "request"),
        template="a short story about {a}"),
    Cmd("letter", "write a letter / email", "Web & text", "<to whom, about what>",
        tool=("write_document", "jobs", {}, "request"), template="a letter: {a}", aliases=("mail",)),
    Cmd("report", "write a report", "Web & text", "<topic>", tool=("write_document", "jobs", {}, "request"),
        template="a report on {a}"),
    Cmd("lyrics", "write song lyrics", "Web & text", "<topic>", tool=("write_document", "jobs", {}, "request"),
        template="song lyrics about {a}"),
    Cmd("offline", "the commands that work without internet", "KURAMA"),
    Cmd("claude", "Claude Code from anywhere: say <msg> / new <msg> / go [project] / status / report / yes / no / stop / usage",
        "Code", "[say|new|go|status|report|yes|no|stop|usage|on|off]", tool=("claude_code", "dev", {"action": "status"}, "text"),
        actions=("on", "off", "new", "go", "status", "report", "yes", "no", "say", "stop", "usage"), aliases=("claudecode", "cc")),
    Cmd("alerts", "recent alerts / which are muted", "KURAMA", phrase="notification status"),
)
_BY_NAME: dict[str, Cmd] = {}
for _c in COMMANDS:
    for _n in (_c.name, *_c.aliases):
        _BY_NAME[_n] = _c

_SLASH = re.compile(r"^/(?P<c>[a-z][\w-]*)(?:@\w+)?(?:\s+(?P<a>.*))?$", re.I | re.S)


def lookup(text: str) -> tuple[Cmd | None, str, str]:
    """(command, its text, the typed name); a close misspelling counts ('/wether' -> weather)."""
    m = _SLASH.match((text or "").strip())
    if not m:
        return None, "", ""
    name, arg = m.group("c").lower(), (m.group("a") or "").strip()
    cmd = _BY_NAME.get(name) or tool_cmd(name.replace("-", "_"))
    if cmd is None and len(name) >= 3:
        every = [*_BY_NAME, *tool_cmds()]
        close = difflib.get_close_matches(name, every, n=1, cutoff=0.7 if len(name) >= 4 else 0.8)
        cmd = (_BY_NAME.get(close[0]) or tool_cmd(close[0])) if close else None
    return cmd, arg, name


# --- every tool is a command too: '/<tool> [action] <text>' runs it directly (no routing, no AI call to pick it) ---
# Tools that need the internet: the AI (Groq / Gemini), the web, Telegram, Groq speech-to-text, edge-tts voices.
# Everything else runs on the laptop alone (files, apps, sound, screen, git, notes, money, timers...). Reading each
# tool's source for network calls was wrong both ways (tools hand their work to core modules), so this is a list.
ONLINE_TOOLS = frozenset({
    "ask_knowledge", "code_to_file", "coding", "dictate", "download_file", "find_my_phone", "fix_error",
    "generate_image", "install_app", "kaggle_train", "lecture", "live_search", "location_history", "make_audio",
    "make_tool", "make_video", "music", "open_url", "page_summary", "python_env", "quiz", "read_text", "read_webpage",
    "remote_desktop", "review_code", "send_file_telegram", "send_last_result", "send_message_telegram", "text_assist",
    "video_download", "weather", "web_search", "web_watch", "wifi_share", "wikipedia", "write_document", "youtube",
})
_TOOLS: dict[str, Cmd] = {}


def online(tool: str) -> bool:
    """The tool needs the internet (ONLINE_TOOLS)."""
    return tool in ONLINE_TOOLS


def tool_cmds() -> dict[str, Cmd]:
    """A command for every registered tool (the general v2 tools left out: they wrap these)."""
    if not _TOOLS:
        from jarvis.core import registry
        registry.REGISTRY.discover()
        for name, t in sorted(registry.REGISTRY.tools.items()):
            group = registry.group_of(t)
            if group == "core" or name.startswith("_"):
                continue
            props = registry.parameters_of(t).get("properties") or {}
            req = registry.parameters_of(t).get("required") or []
            text = [k for k, v in props.items() if k != "action" and v.get("type") in ("string", "number", "integer")]
            key = next((k for k in req if k in text), text[0] if text else "")
            acts = tuple((props.get("action") or {}).get("enum") or ())
            desc = (t.description or "").split(". ")[0].split(": ")[0][:70]
            hint = (f"[{'|'.join(acts[:4])}{'|…' if len(acts) > 4 else ''}] " if acts else "") + (f"<{key}>" if key else "")
            _TOOLS[name] = Cmd(name, desc, f"tool:{group}", hint.strip(), tool=(name, group, {}, key), actions=acts)
    return _TOOLS


def tool_cmd(name: str) -> Cmd | None:
    return tool_cmds().get(name)


def phrase_for(cmd: Cmd, arg: str) -> str:
    bare, _, with_arg = cmd.phrase.partition("|")
    if arg:
        return (with_arg or bare).replace("{a}", arg)
    return bare if "{a}" not in bare else ""


def _clean_target(arg: str) -> str:
    """'/clear ram', '/clear kurama storage', '/clear KURAMA' -> ram | storage | kurama ('' = the old /clear)."""
    from jarvis.core import cleanup
    found = {cleanup.word(w) for w in re.findall(r"[a-z]+", arg.lower())}
    return next((t for t in ("kurama", "ram", "storage") if t in found), "")


def tool_call(cmd: Cmd, arg: str) -> tuple[str, str, dict] | None:
    if cmd.name == "clear" and (target := _clean_target(arg)):
        return "cleanup", "system", {"action": target}
    if not cmd.tool:
        return None
    tool, group, fixed, key = cmd.tool
    args = {k: (v() if callable(v) else v) for k, v in fixed.items()}
    if cmd.actions and arg and (first := arg.split()[0].lower()) in cmd.actions:  # '/backup run', '/saved_links list'
        args["action"], arg = first, arg[len(first):].strip()
    if cmd.template and arg:
        arg = cmd.template.replace("{a}", arg)
    if cmd.cat.startswith("tool:") and key and arg:
        from jarvis.core import registry
        kind = ((registry.parameters_of(registry.REGISTRY.tools[tool]).get("properties") or {}).get(key) or {}).get("type")
        if kind in ("number", "integer"):
            try:
                args[key] = float(arg) if kind == "number" else int(arg)
            except ValueError:
                return None
            return tool, group, args
    if key and arg:
        default = fixed.get(key)
        args[key] = int(arg) if isinstance(default, int) and arg.isdigit() else arg
    elif key and key not in args:
        if cmd.hint.startswith("<") or (cmd.cat.startswith("tool:") and not args):
            return None  # '/search' with nothing to search ('/write_document' alone: the usage line)
        if not cmd.cat.startswith("tool:"):
            args[key] = ""
    return tool, group, args


NET_MARK = "🌐"


_PHRASE_TOOL: dict[str, str] = {}


def _net(c: Cmd) -> bool:
    """The command needs the internet: its tool, or (a phrase command) the tool its phrase runs."""
    if c.tool:
        return c.tool[0] != "_cmd" and online(c.tool[0])
    if c.phrase and c.name not in _PHRASE_TOOL:
        try:
            from jarvis.core import fastpath
            it = fastpath._match(phrase_for(c, "pokhara") or phrase_for(c, ""))  # the pattern only: which tool
            if it is not None:  # (not cached when unknown: the meaning model may still be loading)
                _PHRASE_TOOL[c.name] = it.tool
        except Exception:  # noqa: BLE001
            pass
    return online(_PHRASE_TOOL.get(c.name, ""))


def help_text(fmt: str = "plain", only_offline: bool = False) -> str:
    """Every command grouped, then every tool as a command. fmt='plain' for Telegram, 'md' for the desktop chat.
    🌐 = needs the internet (everything else also works offline)."""
    lines = [("Commands that work without internet" if only_offline else
              f"Commands (no routing, type them in the chat or on Telegram; {NET_MARK} = needs internet):")]
    for cat in CATS:
        rows = [c for c in COMMANDS if c.cat == cat and not (only_offline and (_net(c) or c.template))]
        if not rows:
            continue
        lines.append(f"\n{'**' + cat + '**' if fmt == 'md' else cat.upper()}")
        for c in rows:
            usage = f"/{c.name}" + (f" {c.hint}" if c.hint else "")
            lines.append(f"{'`' + usage + '`' if fmt == 'md' else usage} — {c.desc}" + (f" {NET_MARK}" if _net(c) else ""))
    shown = {c.tool[0] for c in COMMANDS if c.tool}
    groups: dict[str, list[str]] = {}
    for c in tool_cmds().values():
        if c.name in shown or (only_offline and online(c.name)):
            continue
        groups.setdefault(c.cat[5:], []).append(f"/{c.name}" + ("" if only_offline or not online(c.name) else NET_MARK))
    if groups:
        lines.append(f"\n{'**Every tool**' if fmt == 'md' else 'EVERY TOOL'} (/<tool> [action] <text>; /<tool> alone = how)")
        for g in sorted(groups):
            lines.append(f"{g}: " + " ".join(groups[g]))
    lines.append("\nPlain words work too: 'what's on today', 'find this function'.")
    return "\n".join(lines)


def catalog() -> list[dict]:
    """For the chat box suggestions."""
    return [{"cmd": c.name, "hint": c.hint, "desc": c.desc, "cat": c.cat, "aliases": list(c.aliases),
             "online": _net(c)} for c in (*COMMANDS, *[t for t in tool_cmds().values()
                                                        if t.name not in {c.tool[0] for c in COMMANDS if c.tool}])]


def telegram_menu(limit: int = 100) -> list[tuple[str, str]]:
    """(command, description) pairs for Telegram's setMyCommands (lowercase, <= 32 chars, <= 256 desc)."""
    return [(c.name, c.desc[:60]) for c in COMMANDS][:limit]
