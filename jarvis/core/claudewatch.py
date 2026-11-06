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
_stop_asked: dict[str, float] = {}  # session id -> when the owner asked it to stop
_go: dict = {}  # '/claude go' opened a new chat here and it has no message yet: {"root", "workspace", "t"}

HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest",
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
            if ev in ("PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest"):
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
_SYSTEM_PROMPT = re.compile(r"^\s*<(?:task-notification|system-reminder|command-name|local-command-stdout|"
                            r"user-prompt-submit-hook|bash-notification)\b", re.I)


def _not_from_owner(prompt: Any) -> bool:
    """A 'prompt' Claude Code made itself (a background task's notification, a reminder), not the owner's words."""
    return bool(_SYSTEM_PROMPT.match(str(prompt or "")))


def _short(v: Any, n: int = 90) -> str:
    s = " ".join(str(v or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def _step_text(tool: str, inp: dict) -> str:
    """One step in everyday words: 'changed config.py', 'ran the tests', 'looked at the code'."""
    inp = inp if isinstance(inp, dict) else {}
    path = inp.get("file_path") or inp.get("notebook_path") or inp.get("path") or ""
    name = Path(str(path)).name if path else "a file"
    if tool == "Write":
        return f"created {name}"
    if tool in EDIT_TOOLS:
        return f"changed {name}"
    if tool == "Read":
        return f"looked at {name}"
    if tool == "Bash":
        cmd = str(inp.get("command") or "").lower()
        for rx, said in ((r"pytest|unittest|npm (?:run )?test|make test", "ran the tests"),
                         (r"git commit", "saved the work in git"), (r"git push", "uploaded the work (git push)"),
                         (r"git (?:status|diff|log)", "checked what changed (git)"),
                         (r"pip install|npm install|apt(?:-get)? install", "installed something"),
                         (r"ruff|flake8|eslint|mypy|lint", "checked the code style"),
                         (r"\bls\b|\bfind\b|\btree\b", "looked around the folders"),
                         (r"\bgrep\b|\brg\b", "searched the code"), (r"mkdir", "made a folder"),
                         (r"\brm\b", "deleted something"), (r"python|node", "ran a program")):
            if re.search(rx, cmd):
                return said
        return "ran a command"
    if tool in ("Grep", "Glob"):
        return "searched the code"
    if tool in ("WebFetch", "WebSearch"):
        return "looked something up on the web"
    if tool in ("TodoWrite", "TaskCreate", "TaskUpdate"):
        return "updated its plan"
    if tool in ("Task", "Agent"):
        return "asked a helper to do part of it"
    return f"used {tool}"


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
        if sid in _stop_asked and ev in ("PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest"):
            _stop_asked.pop(sid)  # '/claude stop': this hook answer makes Claude Code stop at once
            s["status"], s["finished"] = "stopped", time.time()
            out, msg = {"stop": "Stopped by the owner from KURAMA."}, ("⏹ Claude Code stopped", _project(s))
        elif ev == "PreToolUse":
            pass  # (only there so a stop can reach it before the next step)
        elif ev == "UserPromptSubmit" and _not_from_owner(data.get("prompt")):
            pass  # Claude Code's own wake-ups (a background task finished: "<task-notification>..."): not the owner's
            #       message, never "started" (11-06: the owner got a "started" message he never sent)
        elif ev == "UserPromptSubmit":
            if s["status"] == "finished" or not s["prompt"]:  # a new task in this conversation
                s.update(started=time.time(), steps=[], files=[], todos=[], status="working", finished=None, final="")
            s["prompt"] = " ".join(str(data.get("prompt") or "").split())[:4000]  # whole (owner: never cut)
            if _go.get("root") and (s.get("cwd") or "").startswith(_go["root"]):
                _go.clear()  # the chat '/claude go' opened has its first message: '/claude say' follows it now
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
            tool, inp = str(data.get("tool_name") or ""), data.get("tool_input") or {}
            what = _step_text(tool, inp) + (f": {_short(inp.get('command'), 120)}" if tool == "Bash" else "")
            _questions[qid] = {"session": sid, "what": what, "answer": None, "t": time.time()}
            s["status"], s["questions"] = "waiting for you", s["questions"] + 1
            out = {"wait": qid}
            msg = ("❓ Claude Code needs your OK",
                   f"{_project(s)}\nIt wants to: {what}\nReply /claude yes or /claude no "
                   f"(I wait {int(config.CLAUDE_ANSWER_WAIT_S // 60)} min, then the laptop asks).")
        elif ev == "Notification":
            text = _short(data.get("message"), 3000)
            if "waiting for your input" in text.lower() or "idle" in text.lower():
                s["status"] = "waiting for you"
                msg = ("⏸ Claude Code is waiting for you", f"{_project(s)}\n{text}\nSend '/claude say <what to do>'.")
        elif ev == "Stop":
            s["status"], s["finished"] = "finished", time.time()
            # its answer, from Claude Code itself (the transcript can lag behind: it gave the step before the end)
            s["final"] = str(data.get("last_assistant_message") or "").strip() or _last_message(s.get("transcript", ""))
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


def stop() -> str:
    """Stop the task that is working: Claude Code stops at its next step (a few seconds)."""
    install_hooks()  # (the stop needs the before-each-step hook: older installs get it now)
    with _lock:
        live = [s for s in _sessions.values() if s["status"] in ("working", "waiting for you")]
        for s in live:
            _stop_asked[s["id"]] = time.time()
        for q in _questions.values():
            if q["answer"] is None:
                q["answer"] = "deny"
    if not live:
        return "Claude Code isn't working on anything right now."
    return "Stopping Claude Code: it stops at its next step (a few seconds). I'll tell you when it has."


def plan_limits() -> list[str]:
    """Your plan's limits for each Claude Code account on this laptop: the 5-hour window and the week, used / left
    and when each resets. Claude Code's own /usage, run on its own ('claude -p /usage': a local command, 0 tokens,
    about half a second); nothing else is read."""
    exe = claude_binary()
    if exe is None:
        return []
    out = []
    for f in settings_files():
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(f.parent), KURAMA_NO_WATCH="1")  # not a task to watch
        try:
            r = subprocess.run([str(exe), "-p", "/usage", "--output-format", "json"], env=env, cwd=str(Path.home()),
                               capture_output=True, text=True, timeout=30)
            res = json.loads(r.stdout or "{}")
        except (OSError, subprocess.TimeoutExpired, ValueError):
            continue
        text = str(res.get("result") or "")
        rows = re.findall(r"^(Current [^:]+):\s*(\d+)%\s*used\s*[·•-]\s*resets\s*(.+)$", text, re.M)
        if not rows or res.get("is_error"):
            continue
        acc = "your account" if len(settings_files()) == 1 else f"account {f.parent.name}"
        out.append(f"📊 Claude Code limits ({acc})")
        for name, pct, reset in rows:
            label = {"current session": "5-hour window"}.get(name.lower(), name.replace("Current week", "Weekly"))
            reset = re.sub(r"\s*\([^)]*\)\s*$", "", reset.strip())  # '(Asia/Kathmandu)': local time anyway
            used = int(pct)
            bar = "█" * (used // 10) + "░" * (10 - used // 10)
            out.append(f"{label}: {bar} {used}% used, {100 - used}% left · resets {reset}")
    return out


def usage() -> str:
    """Your plan's limits (5-hour window, week: used, left, when they reset) and how much was used today."""
    limits = plan_limits()
    return "\n".join(limits + ([""] if limits else []) + [_used_today()]).strip()


def _used_today() -> str:
    """How much Claude Code was used: this task and today (from its own conversation files; 0 tokens)."""
    today = time.strftime("%Y-%m-%d")
    tot = {"in": 0, "out": 0, "cache": 0, "msgs": 0}
    sessions: set[str] = set()
    models: dict[str, int] = {}
    cur = _current()
    task = {"in": 0, "out": 0, "cache": 0, "msgs": 0}
    since = (cur or {}).get("started", 0)
    for f in settings_files():
        for tr in f.parent.glob("projects/*/*.jsonl"):
            try:
                if time.strftime("%Y-%m-%d", time.localtime(tr.stat().st_mtime)) != today:
                    continue
                lines = tr.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                if '"usage"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                m = d.get("message") if isinstance(d, dict) else None
                u = m.get("usage") if isinstance(m, dict) else None
                if not isinstance(u, dict) or _local_day(str(d.get("timestamp") or "")) != today:
                    continue  # (its times are UTC: compared as local days)
                n_in, n_out = int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
                n_cache = int(u.get("cache_read_input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0)
                tot["in"] += n_in
                tot["out"] += n_out
                tot["cache"] += n_cache
                tot["msgs"] += 1
                sessions.add(tr.stem)
                if m.get("model"):
                    models[m["model"]] = models.get(m["model"], 0) + 1
                if cur and tr.stem == cur["id"]:
                    task["in"] += n_in
                    task["out"] += n_out
                    task["cache"] += n_cache
                    task["msgs"] += 1
    if not tot["msgs"]:
        return "Claude Code hasn't been used today on this laptop."

    def k(n: int) -> str:
        return f"{n / 1_000_000:.1f}M" if n >= 1_000_000 else (f"{n / 1000:.0f}k" if n >= 1000 else str(n))
    out = ["📈 Used today"]
    if cur and task["msgs"]:
        out.append(f"This task: {task['msgs']} replies, {k(task['out'])} words written by it (tokens), "
                   f"{k(task['in'] + task['cache'])} read (mostly re-read from its memory), running "
                   f"{_mins(time.time() - since)}")
    out.append(f"Today: {len(sessions)} conversations, {tot['msgs']} replies, {k(tot['out'])} written, "
               f"{k(tot['in'] + tot['cache'])} read (most of it re-read from its memory, which is cheap)")
    if models:
        out.append("Model: " + ", ".join(sorted(models, key=models.get, reverse=True)[:2]))
    return "\n".join(out)


def _local_day(ts: str) -> str:
    from datetime import datetime
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d")
    except ValueError:
        return ""


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
        out.append(f"💬 Its answer:\n{s['final']}")  # the whole answer (a long one arrives as a file too)
    return "\n".join(out)


def _current() -> dict | None:
    """The newest real conversation (one you gave a prompt), never KURAMA's own '/usage' checks."""
    with _lock:
        live = sorted((s for s in _sessions.values() if s.get("prompt") and not s["id"].startswith("demo-")),
                      key=lambda s: s["last"], reverse=True)
    return live[0] if live else None


def status() -> str:
    """What Claude Code is doing, in everyday words (0 tokens)."""
    if not is_on():
        return "I'm not watching Claude Code. Say '/claude on' (or 'watch my Claude Code') first."
    s = _current()
    if s is None:
        return "I'm watching Claude Code, but no task has started yet. Give it a prompt and I'll follow it."
    todos = s.get("todos") or []
    done = sum(1 for t in todos if t["status"] == "completed")
    took = _mins((s.get("finished") or time.time()) - s["started"])
    state = {"working": "is working", "waiting for you": "is waiting for you", "finished": "has finished",
             "stopped": "was stopped", "closed": "was closed"}.get(s["status"], s["status"])
    out = [f"🤖 Claude Code {state} ({_project(s)[2:]})"]
    if s.get("prompt"):
        out.append(f"You asked: \"{s['prompt'][:160]}\"")
    if s["status"] in ("finished", "stopped"):
        out.append(f"It took {took}.")
    else:
        out.append(f"It started {took} ago.")
    if todos:
        line = f"Progress: {done} of {len(todos)} parts done"
        out.append(line + (f", about {_eta(s)[2:].replace(' left', '')} to go." if _eta(s) else "."))
        now = next((t["text"] for t in todos if t["status"] == "in_progress"), "")
        if now and s["status"] == "working":
            out.append(f"Right now: {now[:1].lower() + now[1:]}.")
    if s["status"] == "waiting for you":
        q = next((q for q in _questions.values() if q["session"] == s["id"] and q["answer"] is None), None)
        out.append(f"It needs your OK to {q['what']}. Reply /claude yes or /claude no." if q else
                   "It is waiting for your next instruction: /claude say <what to do>.")
    if s["steps"] and s["status"] != "finished":
        recent = list(dict.fromkeys(line for _, line in s["steps"][-8:][::-1]))[:4]
        ago = _mins(time.time() - s["steps"][-1][0])
        out.append(f"Lately it {', '.join(recent)} (last step {ago} ago).")
    if s.get("final") and s["status"] == "finished":
        out.append(f"Its answer: {s['final'][:300]}")
    if s.get("files"):
        out.append(f"Files changed so far: {len(s['files'])}.")
    return "\n".join(out)


def report() -> str:
    """The whole task in everyday words: what you asked, its plan, the files, the timeline, the result."""
    s = _current()
    if not is_on() or s is None:
        return status()
    out = [status(), ""]
    if s.get("todos"):
        mark = {"completed": "✅", "in_progress": "▶️"}
        out += ["Its plan:"] + [f"  {mark.get(t['status'], '⬜')} {t['text']}" for t in s["todos"]]
    if s.get("files"):
        out += ["Files it changed:"] + [f"  • {Path(f).name}" for f in s["files"][:30]]
    if s.get("final"):
        out += ["Its full answer:", s["final"]]
    if s["steps"]:
        out.append("What it did, in order:")
        last = ""
        for ts, line in s["steps"][-60:]:
            if line != last:  # 'changed config.py' five times in a row reads as one line
                out.append(f"  {time.strftime('%H:%M', time.localtime(ts))}  {line}")
            last = line
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
_NOT_LINKED = "VS Code isn't open on the laptop, so I can't reach the Claude Code chat. Open VS Code and send it again."


def _window(cwd: str = "", min_ext: int = 6) -> dict | None:
    """The linked VS Code window of that folder (else the one used last), or None."""
    from jarvis.core import editor
    wins = [w for w in editor.states() if int(w.get("ext") or 0) >= min_ext]
    return next((w for w in wins if cwd and str(w.get("root") or "") == cwd), None) or \
        next((w for w in wins if cwd and cwd.startswith(str(w.get("root") or "~~") + "/")), None) or \
        (wins[0] if wins else None)


def new(text: str = "", where: str = "") -> str:
    """'/claude new [message]' (or '/claude go [project]'): a NEW Claude Code chat in VS Code. With a message it is
    sent at once and that chat becomes the current one; without, the next '/claude say' starts it."""
    from jarvis.core import editor
    if not is_on():
        turn_on()
    root = ""
    if where.strip():
        from jarvis.core import fastpath
        p = fastpath.folder_in_words(f"open {where} in vs code")
        if p is None:
            return f"I can't find a project folder called '{where}'. Say it like '/claude go kurama'."
        root = str(p)
        if _window(root) is None or str(_window(root).get("root") or "") != root:  # open that project first
            subprocess.Popen(["code", root], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(40):
                time.sleep(0.5)
                if (w := _window(root)) is not None and str(w.get("root") or "") == root:
                    break
    st = _window(root)
    if st is None:
        text = " ".join((text or "").split())
        if text and (r := _via_uri("", text, root)) is not None:
            return r or f"Started a new Claude Code chat: \"{_short(text, 120)}\". /claude say goes to it now."
        return _NOT_LINKED
    name = str(st.get("workspace") or Path(str(st.get("root") or "")).name)
    text = " ".join((text or "").split())
    if text:
        r = editor.edit(st, "claude_new", text=text)  # a new chat tab with the message in its box
        if not r.get("ok") or not _press_enter(name):
            return f"VS Code couldn't start the new chat: {r.get('error') or 'no answer'}."
        _go.clear()  # (its first event makes it the current conversation)
        return f"Started a new Claude Code chat in {name}: \"{_short(text, 120)}\". /claude say goes to it now."
    r = editor.edit(st, "claude_new")
    if not r.get("ok"):
        return f"VS Code couldn't open a new Claude Code chat: {r.get('error') or 'no answer'}."
    _go.clear()
    _go.update(root=str(st.get("root") or ""), workspace=name, t=time.time())
    return f"A new Claude Code chat is open in {name}. Send /claude say <your task> to start it."


def go(where: str = "") -> str:
    return new("", where)


def say(text: str) -> str:
    """'/claude say <message>': into the CURRENT Claude Code conversation (the one used last, like this chat), in
    its VS Code chat: that conversation's tab opens with the message, Enter is pressed, you see it there, and if
    it is busy Claude Code queues it. Never a hidden copy, never a new session ('/claude new' is for that)."""
    text = " ".join((text or "").split())
    if not text:
        return "What should I tell Claude Code? e.g. '/claude say run the tests and fix them'"
    if _go and time.time() - _go.get("t", 0) < 6 * 3600:  # '/claude go' opened an empty chat: this starts it
        return new(text)
    s = _current()
    if s is None:
        return "There's no Claude Code conversation yet. Send /claude new <message> to start one."
    sent = _into_vscode(s, text)
    return sent if sent is not None else _NOT_LINKED


def _via_uri(session: str, text: str, cwd: str = "") -> str | None:
    """Without the KURAMA link: Claude Code's OWN VS Code address (vscode://anthropic.claude-code/open) opens that
    conversation (or a new one) with the message in its box, then Enter is pressed. The first time, VS Code asks
    "Allow 'Claude Code for VS Code' to open this URI?": tick "Do not ask me again" and Open, once."""
    import urllib.parse
    if not shutil.which("code") or not _vscode_running():
        return None
    if session:  # an open conversation refuses a prompt from the address: open it, then type into its box
        url = "vscode://anthropic.claude-code/open?session=" + urllib.parse.quote(session)
        subprocess.run(["code", "--open-url", url], capture_output=True, timeout=15)
        time.sleep(2.0)
        name = Path(cwd).name if cwd else ""
        if not _type_text(name, text) or not _press_enter(name):
            return "VS Code opened the chat, but I couldn't type the message there. Type it there, or try again."
        return ""
    q = {"prompt": text}
    url = "vscode://anthropic.claude-code/open?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)
    subprocess.run(["code", "--open-url", url], capture_output=True, timeout=15)
    time.sleep(2.5)  # the chat opens with the text in its box
    name = Path(cwd).name if cwd else ""
    if not _press_enter(name):
        return (f"I put \"{_short(text, 120)}\" in the Claude Code chat box in VS Code, but couldn't press Enter. "
                "Press Enter there.")
    return ""


def _vscode_running() -> bool:
    try:
        return subprocess.run(["pgrep", "-x", "code"], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _into_vscode(s: dict, text: str) -> str | None:
    """Type the message into that conversation's chat in VS Code; None when VS Code isn't open."""
    from jarvis.core import editor
    st = _window(str(s.get("cwd") or ""), min_ext=5)
    if st is None:  # the KURAMA link isn't active in VS Code: Claude Code's own address does it
        r = _via_uri(str(s.get("id") or ""), text, str(s.get("cwd") or ""))
        if r is None:
            return None
        if r:
            return r
        where = f"\"{_short(s.get('prompt') or '', 50)}\"" if s.get("prompt") else "the current chat"
        return (f"Sent to your Claude Code chat ({where}): \"{_short(text, 120)}\". I'll tell you when it answers. "
                "(If VS Code asked to allow opening a link on the laptop, tick 'Do not ask me again' and Open, once.)")
    r = editor.edit(st, "claude_say", session=s["id"] or None, text=text)
    if not r.get("ok"):
        log.info("claude say via VS Code failed: %s", r.get("error"))
        return f"VS Code couldn't open that chat: {r.get('error') or 'no answer'}."
    ws = str(st.get("workspace") or Path(str(st.get("root") or "")).name)
    if r.get("typed") is False and not _type_text(ws, text):  # the box is focused: KURAMA types the message
        return "VS Code opened the chat, but I couldn't type the message there."
    if not _press_enter(ws):
        return (f"I put \"{_short(text, 120)}\" in the Claude Code chat box in VS Code, but couldn't press Enter. "
                "Press Enter there, or try again.")
    where = f"\"{_short(s.get('prompt') or '', 50)}\"" if s.get("prompt") else "the current chat"
    return f"Sent to your Claude Code chat ({where}): \"{_short(text, 120)}\". I'll tell you when it answers."


def _type_text(workspace: str, text: str) -> bool:
    """Paste the message into the focused Claude Code box of that VS Code window, after clearing what is in it (the
    clipboard is put back)."""
    if not shutil.which("xdotool") or not shutil.which("xclip"):
        return False
    try:
        old = subprocess.run(["xclip", "-o", "-selection", "clipboard"], capture_output=True, text=True, timeout=3).stdout
        subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, timeout=3)
        out = subprocess.run(["xdotool", "search", "--name", f"{workspace}.*Visual Studio Code" if workspace
                              else "Visual Studio Code"], capture_output=True, text=True, timeout=5).stdout.split()
        if not out:
            return False
        subprocess.run(["xdotool", "windowactivate", "--sync", out[-1]], capture_output=True, timeout=5)
        time.sleep(0.3)  # clear the box first: VS Code adds '@file#line' of the open editor when it gets focus
        subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+a", "BackSpace"], capture_output=True, timeout=5)
        time.sleep(0.1)
        subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"], capture_output=True, timeout=5)
        time.sleep(0.4)
        subprocess.run(["xclip", "-selection", "clipboard"], input=old, text=True, timeout=3)  # your clipboard back
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def _press_enter(workspace: str) -> bool:
    """Bring that VS Code window to the front and press Enter in the Claude Code box it just focused."""
    if not shutil.which("xdotool"):
        return False
    try:
        out = subprocess.run(["xdotool", "search", "--name", f"{workspace}.*Visual Studio Code" if workspace
                              else "Visual Studio Code"], capture_output=True, text=True, timeout=5).stdout.split()
        if not out:
            return False
        subprocess.run(["xdotool", "windowactivate", "--sync", out[-1]], capture_output=True, timeout=5)
        time.sleep(0.4)
        subprocess.run(["xdotool", "key", "--clearmodifiers", "Return"], capture_output=True, timeout=5)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


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
