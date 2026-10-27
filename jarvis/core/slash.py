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


def _git_repo() -> str:
    from jarvis.core import timemachine
    p = timemachine.vscode_folder()
    return str(p) if p else "."


CATS = ("Day", "Laptop", "Code", "Media", "Web & text", "KURAMA")
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
    Cmd("ports", "programs using ports", "Laptop", "[port]", phrase="show my open ports|what is running on port {a}",
        aliases=("port",)),
    Cmd("screenshot", "take a screenshot", "Laptop", phrase="take a screenshot", aliases=("ss",)),
    Cmd("lockscreen", "lock the screen", "Laptop", phrase="lock the screen"),
    Cmd("vol", "volume up / down / 0-100", "Laptop", "<up|down|N>", phrase="volume up|volume {a}", aliases=("volume",)),
    Cmd("bright", "brightness up / down / 0-100", "Laptop", "<up|down|N>", phrase="brightness up|brightness {a}",
        aliases=("brightness",)),
    Cmd("dark", "dark mode", "Laptop", phrase="dark mode"),
    Cmd("light", "light mode", "Laptop", phrase="light mode"),
    Cmd("dnd", "do not disturb on / off", "Laptop", "[on|off]", phrase="do not disturb on|do not disturb {a}"),
    Cmd("internet", "check / fix the internet", "Laptop", phrase="check my internet", aliases=("net", "wifi")),
    Cmd("clip", "clipboard history", "Laptop", phrase="show the clipboard history"),
    Cmd("jobs", "background jobs", "Laptop", tool=("jobs", "jobs", {"action": "list"}, "")),
    Cmd("tokens", "today's token use", "KURAMA", phrase="token usage"),
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
    Cmd("alerts", "which alerts are on / muted", "KURAMA", phrase="notification status"),
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
    cmd = _BY_NAME.get(name)
    if cmd is None and len(name) >= 3:
        close = difflib.get_close_matches(name, list(_BY_NAME), n=1, cutoff=0.7 if len(name) >= 4 else 0.8)
        cmd = _BY_NAME.get(close[0]) if close else None
    return cmd, arg, name


def phrase_for(cmd: Cmd, arg: str) -> str:
    bare, _, with_arg = cmd.phrase.partition("|")
    if arg:
        return (with_arg or bare).replace("{a}", arg)
    return bare if "{a}" not in bare else ""


def tool_call(cmd: Cmd, arg: str) -> tuple[str, str, dict] | None:
    if not cmd.tool:
        return None
    tool, group, fixed, key = cmd.tool
    args = {k: (v() if callable(v) else v) for k, v in fixed.items()}
    if key and arg:
        default = fixed.get(key)
        args[key] = int(arg) if isinstance(default, int) and arg.isdigit() else arg
    elif key and key not in args:
        if cmd.hint.startswith("<"):
            return None  # '/search' with nothing to search
        args[key] = ""
    return tool, group, args


def help_text(fmt: str = "plain") -> str:
    """Every command grouped. fmt='plain' for Telegram, 'md' for the desktop chat."""
    lines = ["Commands (0 tokens, type them in the chat or on Telegram):"]
    for cat in CATS:
        rows = [c for c in COMMANDS if c.cat == cat]
        if not rows:
            continue
        lines.append(f"\n{'**' + cat + '**' if fmt == 'md' else cat.upper()}")
        for c in rows:
            usage = f"/{c.name}" + (f" {c.hint}" if c.hint else "")
            lines.append(f"{'`' + usage + '`' if fmt == 'md' else usage} — {c.desc}")
    lines.append("\nPlain words work too: 'what's on today', 'find this function'.")
    return "\n".join(lines)


def catalog() -> list[dict]:
    """For the chat box suggestions."""
    return [{"cmd": c.name, "hint": c.hint, "desc": c.desc, "cat": c.cat, "aliases": list(c.aliases)}
            for c in COMMANDS]


def telegram_menu(limit: int = 100) -> list[tuple[str, str]]:
    """(command, description) pairs for Telegram's setMyCommands (lowercase, <= 32 chars, <= 256 desc)."""
    return [(c.name, c.desc[:60]) for c in COMMANDS][:limit]
