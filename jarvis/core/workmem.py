"""Working memory: the THINGS KURAMA made or touched in this conversation and the CHOICE it is waiting on.

The chat history keeps only words. Everything a tool did (the image it drew, the folder it made, the three files it
found) used to vanish after the turn, so "send that image to telegram", "open it in vs code" and "the second one"
had nothing to point at. Every tool call passes through safety.execute, which calls record_call(): real paths in
its arguments and result become things (only paths that exist on disk, never a guess). Finished background jobs add
their output. Shared across processes via the kv store (laptop and Telegram are one conversation).

  things()            newest first: {"p": path, "k": kind, "by": tool, "t": time}
  latest(kind)        the newest thing of a kind ("image", "folder", ...) or of any kind
  kind_named(text)    "that image" -> "image", "the pdf" -> "document" (reference words inside an action)
  line()              one short line for the AI's prompt (~40-60 tokens), "" when there is nothing recent
  choices / choose()  a tool answered with a numbered list of real paths ("which copy?"): "2" / "the second one"
                      / "the one in Redmi" re-runs that tool on the chosen path (0 tokens)
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Iterator

from jarvis.core import config, store

log = logging.getLogger(__name__)

_THINGS = "workmem_things"
_CHOICE = "workmem_choice"
MAX_THINGS = 12
LINE_THINGS = 4
CHOICE_TTL_S = 600

KINDS = {
    "image": (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".heic"),
    "video": (".mp4", ".mkv", ".webm", ".mov", ".avi"),
    "audio": (".mp3", ".m4a", ".wav", ".ogg", ".flac", ".opus"),
    "document": (".md", ".txt", ".pdf", ".docx", ".doc", ".odt", ".rtf", ".pptx", ".xlsx", ".csv", ".html"),
    "code": (".py", ".js", ".ts", ".sh", ".ipynb", ".json", ".yaml", ".yml", ".c", ".cpp", ".java", ".go", ".rs"),
    "archive": (".zip", ".tar", ".gz", ".7z", ".rar"),
}
# what a reference word inside an action points at ("send that image", "open the doc"): the action is already chosen
# by meaning; these only say WHICH remembered thing
_NOUNS = {
    "image": r"image|images|photo|photos|picture|pictures|pic|pics|screenshot|wallpaper|drawing|poster|logo|"
             r"chart|charts|graph|graphs|plot|diagram|diagrams",  # a chart is a picture (35c1679e sent the word "graph")
    "video": r"video|videos|clip|movie",
    "audio": r"song|audio|track|mp3|recording",
    "document": r"document|doc|docs|pdf|essay|note|notes|report|markdown|md|letter|text\s+file",
    "code": r"code|script|program",
    "archive": r"zip|archive",
    "folder": r"folder|directory|dir|project",
}
_NOUN_RX = {k: re.compile(rf"\b(?:{v})\b", re.I) for k, v in _NOUNS.items()}
_PATH = re.compile(r"(?<![\w~/.])(~?/[^\s\"'`<>|]+)")
_SKIP_TOOLS = {"_say", "_cmd", "request_tools"}
_SKIP_ROOTS = ("/proc", "/sys", "/dev", "/usr", "/etc", "/bin", "/lib")


def kind_of(p: Path) -> str:
    if p.is_dir():
        return "folder"
    suf = p.suffix.lower()
    return next((k for k, sufs in KINDS.items() if suf in sufs), "file")


def kind_named(text: str) -> str:
    """The kind a reference names ('that image' -> image), '' when it names none."""
    for k, rx in _NOUN_RX.items():
        if rx.search(text or ""):
            return k
    return ""


# --- what one step of a plan did (taskgraph): its calls, the things it made, the jobs it started ---
_COLLECT: contextvars.ContextVar[dict | None] = contextvars.ContextVar("kurama_workmem_collect", default=None)


@contextlib.contextmanager
def collect() -> Iterator[dict]:
    """Within the block, every tool call is added to the yielded {"calls": [(name, ok)], "things": [path],
    "jobs": [id]} (threads started inside see the same dict through the copied context)."""
    got: dict = {"calls": [], "things": [], "jobs": []}
    token = _COLLECT.set(got)
    try:
        yield got
    finally:
        _COLLECT.reset(token)


# --- things ---
def _load(key: str, default: Any) -> Any:
    try:
        return json.loads(store.kv_get(key) or "null") or default
    except (ValueError, TypeError):
        return default
    except Exception:  # noqa: BLE001  (store unavailable)
        return default


def things(max_age_s: float | None = None) -> list[dict]:
    """Remembered things, newest first, that still exist and are not older than max_age_s (default FOCUS_TTL_H)."""
    max_age = config.FOCUS_TTL_H * 3600 if max_age_s is None else max_age_s
    now = time.time()
    return [t for t in _load(_THINGS, []) if now - float(t.get("t", 0)) <= max_age and Path(t["p"]).exists()]


def note(path: str | Path, by: str = "") -> dict | None:
    """Remember a real file/folder KURAMA made or touched (ignored when it doesn't exist)."""
    try:
        p = Path(str(path)).expanduser()
        if not p.is_absolute() or not p.exists() or str(p).startswith(_SKIP_ROOTS) or p == Path.home() \
                or len(p.parts) < 3:  # '/', '/home', '/media': never "it" (text_assist once left '/')
            return None
        p = p.resolve()
        item = {"p": str(p), "k": kind_of(p), "by": by, "t": time.time()}
        rest = [t for t in _load(_THINGS, []) if t.get("p") != item["p"]]
        store.kv_set(_THINGS, json.dumps(([item] + rest)[:MAX_THINGS]))
        if (got := _COLLECT.get()) is not None and item["p"] not in got["things"]:
            got["things"].append(item["p"])
        return item
    except Exception as e:  # noqa: BLE001  (memory must never break a tool call)
        log.debug("workmem note failed: %s", e)
        return None


def latest(kind: str = "", max_age_s: float | None = None) -> Path | None:
    """The newest remembered thing of this kind ('' = any; 'file' = any non-folder)."""
    for t in things(max_age_s):
        if not kind or t["k"] == kind or (kind == "file" and t["k"] != "folder"):
            return Path(t["p"])
    return None


def newest_time() -> float:
    items = things()
    return float(items[0]["t"]) if items else 0.0


def clear() -> None:
    for k in (_THINGS, _CHOICE):
        try:
            store.kv_delete(k)
        except Exception:  # noqa: BLE001
            pass


def _short(p: str) -> str:
    home = str(Path.home())
    return "~" + p[len(home):] if p.startswith(home + "/") else p


def _ago(t: float) -> str:
    s = max(0, time.time() - t)
    return "just now" if s < 60 else f"{int(s // 60)} min ago" if s < 3600 else f"{int(s // 3600)} h ago"


def line() -> str:
    """'Things from this chat (newest first): image ~/Pictures/KURAMA/horse.png (2 min ago); folder ...'"""
    items = things(config.WORKMEM_PROMPT_AGE_S)[:LINE_THINGS]
    if not items:
        return ""
    body = "; ".join(f"{t['k']} {_short(t['p'])} ({_ago(t['t'])})" for t in items)
    return ("Things from this chat, newest first (\"it\", \"that image\", \"the folder\" mean these unless the user "
            f"names another): {body}.")


# --- paths in a tool call ---
def _real(cand: str) -> Path | None:
    """The longest existing path at the start of cand ('/a/My File.jpg. Ask me...' -> /a/My File.jpg)."""
    cand = cand.strip()
    for _ in range(10):
        c = cand.rstrip(" .,;:!?)]}*`'\"")
        if not c:
            return None
        p = Path(c).expanduser()
        if p.is_absolute() and len(c) > 1 and p.exists():
            return p
        cut = max(c.rfind(" "), c.rfind("("))
        if cut <= 0:
            return None
        cand = c[:cut]
    return None


def paths_in(text: str) -> list[Path]:
    """Existing absolute paths written in text, in order (spaces inside a path are kept when the path exists)."""
    out: list[Path] = []
    for ln in (text or "").splitlines():
        for m in _PATH.finditer(ln):
            p = _real(ln[m.start():])
            if p is not None and p not in out:
                out.append(p)
    return out


def _arg_paths(args: Any) -> list[Path]:
    vals = args.values() if isinstance(args, dict) else []
    out = []
    for v in vals:
        if isinstance(v, str) and v.strip().startswith(("/", "~")) and "\n" not in v:
            p = _real(v)
            if p is not None:
                out.append(p)
    return out


_FAILED = ("error", "refused", "the user declined", "sorry, that didn't work", "no open window")
_NUMBERED = re.compile(r"^\s*(?:\d{1,2}[.)]|[-*•])\s+")


def record_call(name: str, args: Any, ok: bool, result: str, data: dict | None = None) -> None:
    """Called by the safety gate for every finished tool call: remember the paths it acted on or produced; a
    numbered list of real paths ('I found three copies: 1. ... 2. ...') becomes a choice the next reply can pick."""
    if name in _SKIP_TOOLS or name.startswith("_"):
        return
    ok = bool(ok) and not str(result or "").lstrip().lower().startswith(_FAILED)  # many tools return "error: ..."
    if (got := _COLLECT.get()) is not None:
        got["calls"].append((name, ok))
        got["jobs"].extend(int(j) for j in re.findall(r"\bjob #(\d+)", str(result or "")) if int(j) not in got["jobs"])
    try:
        res = str(result or "")
        if sum(1 for ln in res.splitlines() if _NUMBERED.match(ln) or re.match(r"^\s*\d{1,2}\.\s", ln)) >= 2 or \
                len(re.findall(r"(?:^|\s)\d{1,2}\.\s", res)) >= 2:  # any numbered list (links, read later, to-do)
            from jarvis.core import registry  # the real tool, not the general one around it ('memory')
            if (t := registry.REGISTRY.tools.get(name)) is None or registry.group_of(t) != "core":
                store.kv_set(_LAST_LIST, json.dumps({"tool": name, "t": time.time()}))
        exact = [Path(p) for p in (data or {}).get("paths") or [] if Path(p).exists()]  # a typed Reply's paths
        listed = exact or [p for ln in res.splitlines() if _NUMBERED.match(ln) for p in paths_in(ln)]
        if len(listed) >= 2 and isinstance(args, dict):
            _offer(name, args, listed)
            return
        if not ok:
            return
        found = _arg_paths(args)
        made = paths_in(res)
        if len(made) > 3:  # a listing, not a thing it made: only what it was pointed at
            made = []
        for p in found + made:  # result paths last: they are the newest (what the tool produced)
            note(p, by=name)
    except Exception as e:  # noqa: BLE001
        log.debug("workmem record failed: %s", e)


def note_job(job: Any) -> None:
    """A finished background job's output (the essay, the image) is a thing too."""
    if getattr(job, "status", "") == "done" and getattr(job, "output_path", ""):
        note(job.output_path, by=f"job #{getattr(job, 'id', '')}")


# --- choices ---
_FIELDS = ("path", "file", "name", "target", "folder", "query", "item")


def _offer(tool: str, args: dict, options: list[Path]) -> None:
    field = next((k for k in _FIELDS if isinstance(args.get(k), str)), None) or \
        next((k for k, v in args.items() if isinstance(v, str) and len(v) < 200), None)
    if field is None:
        return
    store.kv_set(_CHOICE, json.dumps({"tool": tool, "args": args, "field": field, "t": time.time(),
                                      "options": [str(p) for p in options[:9]]}))


_LAST_LIST = "workmem_last_list"


def last_list(within_s: float = 300) -> str:
    """The tool that showed the newest numbered list (in the last 5 min), or ''."""
    c = _load(_LAST_LIST, None)
    return str(c.get("tool", "")) if c and time.time() - float(c.get("t", 0)) < within_s else ""


def choice() -> dict | None:
    c = _load(_CHOICE, None)
    if not c or time.time() - float(c.get("t", 0)) > CHOICE_TTL_S:
        return None
    return c


def drop_choice() -> None:
    try:
        store.kv_delete(_CHOICE)
    except Exception:  # noqa: BLE001
        pass


def choose(text: str) -> tuple[str, dict] | None:
    """The waiting choice's (tool, args) for a reply that picks one option: a position ('2', 'second', 'the
    last one') or words that fit exactly one option's path ('the one in Redmi 9A'). None otherwise."""
    c = choice()
    if c is None:
        return None
    t = " ".join((text or "").split()).strip(" .!?")
    if not t or len(t.split()) > 8:
        return None
    from jarvis.core import links
    opts = c["options"]
    pos = links.position(re.sub(r"\b(?:send|open|oprn|opne|use|take|pick|choose|select|it|copy|file|folder|please|"
                                r"number|no|num|go|to|now|that|this|the|one|in|vs\s*code|file\s*manager)\b", " ",
                                t, flags=re.I))  # '4 number folder' / 'go to 5 number folder' (11-04)
    pick = None
    if pos is not None and (1 <= pos <= len(opts) or pos == -1):
        pick = opts[pos - 1] if pos > 0 else opts[-1]
    else:
        words = [w for w in re.findall(r"[\w.-]{2,}", t.lower()) if w not in ("the", "one", "in", "from", "of",
                                                                                "that", "this", "inside")]
        hits = [o for o in opts if words and all(w in o.lower() for w in words)]
        if len(hits) == 1:
            pick = hits[0]
    if pick is None:
        return None
    drop_choice()
    if c["tool"] in _LISTERS:  # a pick from SEARCH results means that result, never "search again inside it"
        return act_on(pick, t)  # (11-04: 'open 1 in vs code' after a find re-ran find_files inside a .vsix file)
    return c["tool"], {**c["args"], c["field"]: pick}


_LISTERS = {"find_files", "list_folder", "recent_files", "find_and_send", "ranked_files", "files"}


def act_on(path: str, said: str) -> tuple[str, dict]:
    """What the reply asks for the picked path: send it / open it in VS Code / in the file manager / just open it."""
    if re.search(r"\b(?:send|share|forward|telegram|phone)\b", said, re.I):
        return "send_file_telegram", {"path": path}
    if re.search(r"\b(?:vs\s*code|vscode|code|editor)\b", said, re.I):
        return "open_path", {"path": path, "app": "vscode"}
    if re.search(r"\b(?:file\s*manager|files|nautilus|explorer)\b", said, re.I) or Path(path).is_dir():
        return "open_path", {"path": path, "app": "files"}
    return "open_path", {"path": path, "app": "default"}
