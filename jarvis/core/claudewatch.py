"""Claude Code watch: KURAMA follows a long Claude Code task for you while you are away, like the Colab training
link. OFF until you turn it on ("/claude on", "watch my Claude Code"); while off nothing is sent or kept.

How it hears Claude Code: Claude Code runs "hooks" (small commands) at its key moments. `install_hooks()` adds one
hook, scripts/claude_hook.py, to Claude Code's settings for those moments; it does nothing (exits at once) unless the
watch is on. While on it posts each event to KURAMA (POST /api/v1/claude/event, laptop only), and this module:

    started   (your prompt)            -> Telegram "▶️ Claude Code started: ..."
    each step (a tool it used)         -> counted: what it is doing now, files it changed, its to-do list
    question  (a permission it needs)  -> Telegram "❓ ... reply /claude yes or /claude no"; the hook waits for the
                                          answer (up to CLAUDE_ANSWER_WAIT_S), then the laptop's own dialog shows
    finished  (it stopped)             -> Telegram "✅ Finished in 47 min ..." with its last message
    silent for CLAUDE_STUCK_S          -> Telegram "⚠️ no activity for 10 min"

status() / report() build the cards from these events (0 tokens). say() sends a new instruction to a finished task
(Claude Code continues the same conversation in the background, `claude -p --resume <session>`).
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from jarvis.core import config

log = logging.getLogger("jarvis.claudewatch")
_lock = threading.Lock()
_sessions: dict[str, dict] = {}  # session id -> its state (kept while the watch is on; saved in data/)
_questions: dict[str, dict] = {}  # question id -> {"session", "what", "answer", "t"}
_stuck_thread: threading.Thread | None = None

HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "PostToolUse", "PostToolUseFailure", "PermissionRequest",
               "Notification", "Stop", "TaskCreated", "TaskCompleted", "SessionEnd")
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")


# ---------- on / off ----------
def flag() -> Path:
    """The file the hook checks first (exists = on): the hook never even starts Python while the watch is off."""
    return config.DATA_DIR / "claude_watch.on"


def is_on() -> bool:
    return flag().exists()


def turn_on() -> str:
    flag().parent.mkdir(parents=True, exist_ok=True)
    flag().write_text(str(time.time()))
    done = install_hooks()
    _start_stuck_check()
    return ("Watching Claude Code now. I'll message your Telegram when a task starts, when it asks something and when it "
            "finishes. Ask '/claude status' any time; '/claude off' stops it." + (f" ({done})" if done else ""))


def turn_off() -> str:
    flag().unlink(missing_ok=True)
    with _lock:
        _sessions.clear()
        for q in _questions.values():
            q.setdefault("answer", None)
    _save()
    return "Stopped watching Claude Code. Nothing is sent or kept now."


# ---------- the hook in Claude Code's settings ----------
def hook_command() -> str:
    script = config.ROOT / "scripts" / "claude_hook.py"
    return f'[ -f "{flag()}" ] && /usr/bin/python3 "{script}" || true'


def settings_files() -> list[Path]:
    """Every Claude Code settings file on this laptop (one per account: ~/.claude, ~/.claude-*)."""
    found = [p / "settings.json" for p in Path.home().glob(".claude*") if p.is_dir() and (p / "projects").is_dir()]
    if os.getenv("CLAUDE_CONFIG_DIR"):
        found.append(Path(os.environ["CLAUDE_CONFIG_DIR"]) / "settings.json")
    return sorted(set(found))


def install_hooks() -> str:
    """Add the watch hook to every Claude Code settings file (once; a backup is kept). Returns what it did."""
    cmd, changed = hook_command(), []
    for f in settings_files():
        try:
            data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        except (OSError, ValueError):
            continue  # a settings file we can't read is never overwritten
        hooks = data.setdefault("hooks", {})
        added = False
        for ev in HOOK_EVENTS:
            entries = hooks.setdefault(ev, [])
            if any(h.get("command") == cmd for e in entries for h in e.get("hooks", [])):
                continue
            entry: dict[str, Any] = {"hooks": [{"type": "command", "command": cmd,
                                                "timeout": int(config.CLAUDE_ANSWER_WAIT_S) + 30
                                                if ev == "PermissionRequest" else 10}]}
            if ev in ("PostToolUse", "PostToolUseFailure", "PermissionRequest"):
                entry["matcher"] = "*"
            entries.append(entry)
            added = True
        if added:
            if f.exists():
                shutil.copy2(f, f.with_suffix(".json.kurama-backup"))
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(data, indent=2), encoding="utf-8")
            changed.append(str(f.parent.name))
    return f"hooks added to {', '.join(changed)}; open Claude Code tasks pick them up when they start" if changed else ""


# ---------- events from the hook ----------
def _short(v: Any, n: int = 90) -> str:
    s = " ".join(str(v or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def _step_text(tool: str, inp: dict) -> str:
    """'edited querykind.py', 'ran: pytest -q', 'read config.py': one line for a tool call."""
    inp = inp if isinstance(inp, dict) else {}
    path = inp.get("file_path") or inp.get("notebook_path") or inp.get("path") or ""
    name = Path(str(path)).name if path else ""
    if tool in EDIT_TOOLS:
        return f"edited {name}"
    if tool == "Read":
        return f"read {name}"
    if tool == "Bash":
        return f"ran: {_short(inp.get('command'), 70)}"
    if tool in ("Grep", "Glob"):
        return f"searched {_short(inp.get('pattern'), 40)}"
    if tool in ("WebFetch", "WebSearch"):
        return f"looked up {_short(inp.get('url') or inp.get('query'), 50)}"
    if tool in ("TodoWrite", "TaskCreate", "TaskUpdate"):
        return "updated its to-do list"
    if tool in ("Task", "Agent"):
        return f"started a helper: {_short(inp.get('description') or inp.get('prompt'), 50)}"
    return tool


def _todos(inp: dict) -> list[dict] | None:
    items = inp.get("todos") if isinstance(inp, dict) else None
    if not isinstance(items, list):
        return None
    return [{"text": _short(i.get("content") or i.get("activeForm") or i.get("subject") or "", 80),
             "status": str(i.get("status") or "pending")} for i in items if isinstance(i, dict)]


def _session(sid: str, data: dict) -> dict:
    s = _sessions.get(sid)
    if s is None:
        s = _sessions[sid] = {"id": sid, "cwd": data.get("cwd") or "", "started": time.time(), "last": time.time(),
                              "prompt": "", "steps": [], "files": [], "todos": [], "status": "working",
                              "transcript": data.get("transcript_path") or "", "questions": 0, "warned": False,
                              "finished": None, "final": ""}
    return s


def event(data: dict) -> dict:
    """One event from the hook. Returns {"wait": question id} when the hook should wait for the owner's answer."""
    if not is_on():
        return {}
    ev = str(data.get("hook_event_name") or data.get("event") or "")
    sid = str(data.get("session_id") or "default")
    out: dict = {}
    msg: tuple[str, str] | None = None
    with _lock:
        s = _session(sid, data)
        s["last"], s["warned"] = time.time(), False
        if data.get("transcript_path"):
            s["transcript"] = data["transcript_path"]
        if ev == "UserPromptSubmit":
            if s["status"] == "finished" or not s["prompt"]:  # a new task in this conversation
                s.update(started=time.time(), steps=[], files=[], todos=[], status="working", finished=None, final="")
            s["prompt"] = _short(data.get("prompt"), 300)
            msg = ("▶️ Claude Code started", f"{_project(s)}\n📝 {s['prompt']}")
        elif ev in ("PostToolUse", "PostToolUseFailure"):
            tool, inp = str(data.get("tool_name") or ""), data.get("tool_input") or {}
            line = _step_text(tool, inp) + (" (failed)" if ev == "PostToolUseFailure" else "")
            s["steps"].append([time.time(), line])
            s["steps"] = s["steps"][-200:]
            s["status"] = "working"
            if tool in EDIT_TOOLS and (p := inp.get("file_path") or inp.get("notebook_path")) and p not in s["files"]:
                s["files"].append(str(p))
            if (todos := _todos(inp)) is not None:
                s["todos"] = todos
        elif ev == "TaskCreated":
            s["todos"].append({"text": _short(data.get("subject") or data.get("description") or data.get("task"), 80),
                               "status": "pending"})
        elif ev == "TaskCompleted":
            what = _short(data.get("subject") or data.get("description") or data.get("task"), 80)
            for t in s["todos"]:
                if t["text"] == what or (not what and t["status"] != "completed"):
                    t["status"] = "completed"
                    break
        elif ev == "PermissionRequest":
            qid = secrets.token_hex(3)
            what = _step_text(str(data.get("tool_name") or ""), data.get("tool_input") or {})
            _questions[qid] = {"session": sid, "what": what, "answer": None, "t": time.time()}
            s["status"], s["questions"] = "waiting for you", s["questions"] + 1
            out = {"wait": qid}
            msg = ("❓ Claude Code needs your OK",
                   f"{_project(s)}\nIt wants to: {what}\nReply /claude yes or /claude no "
                   f"(I wait {int(config.CLAUDE_ANSWER_WAIT_S // 60)} min, then the laptop asks).")
        elif ev == "Notification":
            text = _short(data.get("message"), 200)
            if "waiting for your input" in text.lower() or "idle" in text.lower():
                s["status"] = "waiting for you"
                msg = ("⏸ Claude Code is waiting for you", f"{_project(s)}\n{text}\nSend '/claude say <what to do>'.")
        elif ev == "Stop":
            s["status"], s["finished"] = "finished", time.time()
            s["final"] = _last_message(s.get("transcript", ""))
            msg = ("✅ Claude Code finished", _finished_text(s))
        elif ev == "SessionEnd":
            s["status"] = "closed"
        _save()
    if msg:
        _tell(*msg)
    return out


def answer(yes: bool, qid: str = "") -> str:
    """The owner's answer to the newest (or a given) open question."""
    with _lock:
        open_q = [(k, q) for k, q in _questions.items() if q["answer"] is None and time.time() - q["t"] <
                  config.CLAUDE_ANSWER_WAIT_S]
        if qid:
            open_q = [(k, q) for k, q in open_q if k == qid]
        if not open_q:
            return "Claude Code isn't waiting for an answer right now."
        k, q = max(open_q, key=lambda kq: kq[1]["t"])
        q["answer"] = "allow" if yes else "deny"
        if s := _sessions.get(q["session"]):
            s["status"] = "working"
    return f"{'Allowed' if yes else 'Denied'}: {q['what']}. Claude Code continues."


def decision(qid: str) -> str:
    """'allow' / 'deny' once the owner answered, '' while waiting (the hook asks every 2 s)."""
    with _lock:
        q = _questions.get(qid)
        return (q or {}).get("answer") or ""


# ---------- cards ----------
def _project(s: dict) -> str:
    return f"📁 {Path(s.get('cwd') or '.').name or s.get('cwd')}"


def _mins(seconds: float) -> str:
    m = int(seconds // 60)
    return f"{m // 60} h {m % 60} min" if m >= 60 else (f"{m} min" if m else f"{int(seconds)} s")


def _eta(s: dict) -> str:
    todos = s.get("todos") or []
    done = sum(1 for t in todos if t["status"] == "completed")
    if not todos or not done or done >= len(todos):
        return ""
    per = (time.time() - s["started"]) / done
    return f"⏳ about {_mins(per * (len(todos) - done))} left"


def _finished_text(s: dict) -> str:
    took = _mins((s.get("finished") or time.time()) - s["started"])
    files = s.get("files") or []
    out = [_project(s), f"⏱ took {took} · {len(s['steps'])} steps · {len(files)} files changed"]
    if s.get("prompt"):
        out.append(f"📝 {s['prompt'][:150]}")
    if s.get("final"):
        out.append(f"💬 {s['final'][:600]}")
    return "\n".join(out)


def _current() -> dict | None:
    with _lock:
        live = sorted(_sessions.values(), key=lambda s: s["last"], reverse=True)
    return live[0] if live else None


def status() -> str:
    """The status card of the newest Claude Code task (0 tokens)."""
    if not is_on():
        return "I'm not watching Claude Code. Say '/claude on' (or 'watch my Claude Code') first."
    s = _current()
    if s is None:
        return "Watching Claude Code. No task has started since: give it a prompt and I'll follow it."
    todos = s.get("todos") or []
    done = sum(1 for t in todos if t["status"] == "completed")
    running = _mins((s.get("finished") or time.time()) - s["started"])
    out = [f"🤖 Claude Code: {s['status']} ({'took' if s['status'] == 'finished' else 'running'} {running})", _project(s)]
    if s.get("prompt"):
        out.append(f"📝 {s['prompt'][:160]}")
    if todos:
        out.append(f"✅ To-do: {done} of {len(todos)} done" + (f"   {_eta(s)}" if _eta(s) else ""))
        now = next((t["text"] for t in todos if t["status"] == "in_progress"), "")
        if now:
            out.append(f"▶️ Now: {now}")
    if s["steps"]:
        out.append(f"🕘 Last steps ({len(s['steps'])} so far, last {_mins(time.time() - s['steps'][-1][0])} ago):")
        out += [f"   • {line}" for _, line in s["steps"][-5:][::-1]]
    if s.get("final") and s["status"] == "finished":
        out.append(f"💬 {s['final'][:300]}")
    return "\n".join(out)


def report() -> str:
    """Everything about the newest task: the full to-do list, every file changed, the step log with times."""
    s = _current()
    if not is_on() or s is None:
        return status()
    out = [status(), ""]
    if s.get("todos"):
        mark = {"completed": "✅", "in_progress": "▶️"}
        out += ["📋 To-do list:"] + [f"   {mark.get(t['status'], '⬜')} {t['text']}" for t in s["todos"]]
    if s.get("files"):
        out += ["📄 Files changed:"] + [f"   • {Path(f).name}" for f in s["files"][:40]]
    if s["steps"]:
        out.append("🧾 Steps:")
        out += [f"   {time.strftime('%H:%M', time.localtime(ts))} {line}" for ts, line in s["steps"][-40:]]
    return "\n".join(out)


def screenshot() -> Path | None:
    """A screenshot of the screen now (for /claude status on the phone), or None."""
    try:
        from jarvis.tools.general.screenshot import screenshot as shoot
        out = shoot("full")
        m = re.search(r"(/\S+\.(?:png|jpg))", out)
        return Path(m.group(1)) if m else None
    except Exception as e:  # noqa: BLE001
        log.info("claude status screenshot failed: %s", e)
        return None


# ---------- a new instruction ----------
def say(text: str) -> str:
    """Send the owner's next instruction to the newest task: Claude Code continues that conversation in the
    background (headless, in the same folder); the hooks report it like any task."""
    text = " ".join((text or "").split())
    if not text:
        return "What should Claude Code do? e.g. '/claude say run the tests and fix them'"
    s = _current()
    if s is None:
        return "There's no Claude Code task to continue. Start one in Claude Code first (with '/claude on')."
    if s["status"] not in ("finished", "waiting for you", "closed"):
        return "Claude Code is still working on its task. I'll tell you when it finishes; then send your next step."
    exe = claude_binary()
    if exe is None:
        return "error: I can't find the claude program on this laptop."
    env = dict(os.environ)
    tp = str(s.get("transcript") or "")
    if m := re.match(r"(.*/\.claude[^/]*)/projects/", tp):  # the same Claude Code account as that task
        env["CLAUDE_CONFIG_DIR"] = m.group(1)
    log_file = config.DATA_DIR / "logs" / "claude_say.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as fh:
        subprocess.Popen([str(exe), "-p", "--resume", s["id"], text], cwd=s.get("cwd") or None, env=env,
                         stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
    return f"Sent to Claude Code: \"{_short(text, 120)}\". I'll message you when it finishes."


def claude_binary() -> Path | None:
    if p := shutil.which("claude"):
        return Path(p)
    found = sorted(Path.home().glob(".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude"))
    return found[-1] if found else None


# ---------- helpers ----------
def _last_message(transcript: str) -> str:
    """Claude Code's final words in that conversation (the end of its transcript file)."""
    try:
        p = Path(transcript)
        if not p.is_file():
            return ""
        with p.open("rb") as fh:
            fh.seek(max(0, p.stat().st_size - 200_000))
            lines = fh.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        m = d.get("message") if isinstance(d, dict) else None
        if d.get("type") == "assistant" and isinstance(m, dict):
            parts = m.get("content")
            texts = [c.get("text", "") for c in parts if isinstance(c, dict) and c.get("type") == "text"] \
                if isinstance(parts, list) else [str(parts or "")]
            if (t := " ".join(" ".join(texts).split())):
                return t
    return ""


def _tell(title: str, text: str) -> None:
    try:
        from jarvis.core import notify
        notify.notify(title, text, level="warning" if title.startswith(("❓", "⚠️")) else "info",
                      source="claude_code", telegram=True)
    except Exception as e:  # noqa: BLE001
        log.warning("claude watch notify failed: %s", e)


def _save() -> None:
    try:
        f = config.DATA_DIR / "claude_watch.json"
        f.write_text(json.dumps({"sessions": _sessions}, ensure_ascii=False)[:2_000_000], encoding="utf-8")
    except OSError:
        pass


def load() -> None:
    """After a restart: the tasks seen so far come back (only while the watch is on)."""
    global _sessions
    if not is_on():
        return
    try:
        _sessions = json.loads((config.DATA_DIR / "claude_watch.json").read_text(encoding="utf-8")).get("sessions") or {}
    except (OSError, ValueError):
        _sessions = {}
    _start_stuck_check()


def _start_stuck_check() -> None:
    """One small thread while the watch is on: a working task silent for CLAUDE_STUCK_S gets one warning."""
    global _stuck_thread
    if _stuck_thread is not None and _stuck_thread.is_alive():
        return

    def loop() -> None:
        while is_on():
            time.sleep(60)
            with _lock:
                quiet = [s for s in _sessions.values() if s["status"] == "working" and not s["warned"]
                         and time.time() - s["last"] > config.CLAUDE_STUCK_S]
                for s in quiet:
                    s["warned"] = True
            for s in quiet:
                _tell("⚠️ Claude Code is quiet", f"{_project(s)}\nNo activity for {_mins(time.time() - s['last'])}. "
                      "It may be stuck or waiting. '/claude status' shows the screen.")
    _stuck_thread = threading.Thread(target=loop, daemon=True, name="claude-watch")
    _stuck_thread.start()
