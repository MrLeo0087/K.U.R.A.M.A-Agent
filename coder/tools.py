"""The coding agent's hands and eyes (the loop in loop.py picks one per step, like Claude Code does):

  list / find / grep / read           look at the project (read-only, output cut to what matters)
  edit / write                        change it: precise "old -> new" edits (cheap), whole new files; every file
                                      backed up first (undo), shown live in VS Code when it is open there
  run                                 a command in the project folder, with a timeout and its output; only safe
                                      commands run by themselves (ALLOW), installs / deletes ask the owner first
  run_project                         start it the right way (python / npm / a page server), read what it says
  screenshot / look                   a picture of the web page or the app's window; the vision model answers a
                                      question about it ("is the button on the left? grey?")
  page_errors                         the web page's JavaScript errors and missing files (0 tokens)
  ports / history / errors / docs     what runs on a port, the file's past versions (time machine), how this
                                      error was fixed before (error memory), the project's own docs (knowledge)
  ask / done                          a real question for the owner / the task is finished

Every tool returns plain text (cut to OUT_MAX characters): the loop shows the model only that.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from pathlib import Path

from coder import repomap, safety
from coder.run import Run

OUT_MAX = 1800
# commands that run by themselves (the first word, or the first two): read, build, test, run the project
ALLOW = re.compile(r"^(?:ls|cat|head|tail|wc|find|grep|rg|tree|pwd|echo|python3?|node|npm\s+(?:run|test|start|ls)|"
                   r"npx\s+(?:tsc|eslint|prettier|vite|jest|vitest)|pytest|ruff|mypy|go\s+(?:run|test|build|vet)|"
                   r"cargo\s+(?:run|test|build|check)|git\s+(?:status|diff|log|show|branch)|make|"
                   r"\S*/\.venv/bin/python|\.venv/bin/python|\S*/venv/bin/python)\b")
ASK_FIRST = re.compile(r"\b(?:pip3?\s+install|npm\s+(?:install|i|add|ci)|yarn|pnpm|apt|brew|rm|mv|chmod|chown|"
                       r"git\s+(?:push|reset|checkout|clean|rebase|commit)|curl|wget|sudo|dd|mkfs|kill)\b")
NEVER = re.compile(r"\bsudo\b|rm\s+-rf\s+[/~]|>\s*/dev/|mkfs|:\(\)\s*\{|\bshutdown\b|\breboot\b")


def _cut(text: str, n: int = OUT_MAX) -> str:
    text = text or ""
    if len(text) <= n:
        return text
    head, tail = text[: n // 3], text[-(2 * n) // 3:]  # errors are usually at the end
    return f"{head}\n… ({len(text) - n} characters cut) …\n{tail}"


def _path(run: Run, rel: str) -> Path:
    p = (run.root / (rel or ".").strip().lstrip("/")).resolve()
    if not p.is_relative_to(run.root.resolve()):
        raise ValueError(f"{rel} is outside the project")
    return p


# ---------------------------------------------------------------- look
def t_list(run: Run, path: str = ".") -> str:
    p = _path(run, path)
    if not p.is_dir():
        return f"{path} isn't a folder"
    files = repomap.files(p, 200)
    return _cut("\n".join(f.relative_to(run.root).as_posix() for f in files) or "(empty)")


def t_find(run: Run, name: str) -> str:
    hits = [f.relative_to(run.root).as_posix() for f in repomap.files(run.root, 2000) if name.lower() in f.name.lower()]
    return "\n".join(hits[:40]) or f"no file named like '{name}'"


def t_grep(run: Run, pattern: str, path: str = ".") -> str:
    out = []
    try:
        rx = re.compile(pattern, re.I)
    except re.error:
        rx = re.compile(re.escape(pattern), re.I)
    target = _path(run, path)
    for f in ([target] if target.is_file() else repomap.files(target, 1500)):
        try:
            for i, ln in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(ln):
                    out.append(f"{f.relative_to(run.root).as_posix()}:{i}: {ln.strip()[:160]}")
                    if len(out) >= 40:
                        return "\n".join(out) + "\n(more…)"
        except OSError:
            continue
    return "\n".join(out) or f"'{pattern}' isn't in the project"


def t_read(run: Run, path: str, start: int = 1, end: int = 0) -> str:
    p = _path(run, path)
    if not p.is_file():
        return f"{path} doesn't exist"
    from jarvis.core import editor
    lines = editor.read(p).splitlines()
    end = end or min(len(lines), start + 199)
    body = "\n".join(f"{i}: {ln}" for i, ln in enumerate(lines[start - 1:end], start))
    more = f"\n(lines {start}-{end} of {len(lines)}; read more with start/end)" if end < len(lines) else ""
    return _cut(body, 9000) + more


# ---------------------------------------------------------------- change
def _save(run: Run, p: Path, text: str) -> None:
    """Backed up, secrets refused; a file open in VS Code changes there (one Ctrl+Z undoes it)."""
    rel = p.relative_to(run.root).as_posix()
    safety.write(run, rel, text)  # (writes the disk; the editor reloads an unchanged buffer itself)
    try:
        from jarvis.core import editor
        if editor._holder(p) is not None:
            editor.save_text(p, text)
    except Exception:  # noqa: BLE001 - the disk already has it
        pass
    if rel not in run.written:
        run.written.append(rel)


def t_edit(run: Run, path: str, old: str, new: str) -> str:
    p = _path(run, path)
    if not p.is_file():
        return f"{path} doesn't exist (use write for a new file)"
    from jarvis.core import editor
    text = editor.read(p)
    n = text.count(old) if old else 0
    if n == 0:
        loose = re.sub(r"\s+", r"\\s+", re.escape(old.strip())) if old.strip() else ""
        m = list(re.finditer(loose, text)) if loose else []
        if len(m) != 1:
            return f"the old text isn't in {path} exactly once ({len(m) or n} matches): read the lines and copy them exactly"
        text = text[: m[0].start()] + new + text[m[0].end():]
    elif n > 1:
        return f"the old text is in {path} {n} times: include more lines so it is unique"
    else:
        text = text.replace(old, new, 1)
    _save(run, p, text)
    return f"edited {path}"


def t_write(run: Run, path: str, content: str) -> str:
    p = _path(run, path)
    if p.is_file() and len(content) < 0.5 * p.stat().st_size:
        return f"{path} exists and the new text is much shorter: use edit for a change (writing would drop code)"
    _save(run, p, content if content.endswith("\n") else content + "\n")
    return f"wrote {path} ({len(content.splitlines())} lines)"


# ---------------------------------------------------------------- run
def python_of(root: Path) -> str:
    for d in (".venv", "venv", "env"):
        if (root / d / "bin" / "python").exists():
            return str(root / d / "bin" / "python")
    return "python3"


def t_run(run: Run, command: str, timeout: float = 60) -> str:
    cmd = (command or "").strip()
    if not cmd:
        return "no command"
    if NEVER.search(cmd):
        return "refused: that command could harm the laptop"
    if ASK_FIRST.search(cmd) or not ALLOW.match(cmd):
        return f"NEEDS_YES: `{cmd}` changes the system or isn't on the safe list; ask the owner first (tool ask)"
    cmd = re.sub(r"^python3?\b", python_of(run.root), cmd)  # the project's own .venv when it has one
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "CI": "1", "FORCE_COLOR": "0", "NO_COLOR": "1"}
    t0 = time.monotonic()
    try:
        r = subprocess.run(cmd, shell=True, cwd=run.root, capture_output=True, text=True, timeout=timeout,
                           env=env, stdin=subprocess.DEVNULL)
        out, code = (r.stdout or "") + (r.stderr or ""), r.returncode
    except subprocess.TimeoutExpired as e:
        out, code = (str(e.stdout or "") + str(e.stderr or "")), "timeout (still running: a server or a loop)"
    run.note(f"ran `{cmd}` -> {code}")
    hint = ""
    if code not in (0, "0") and (m := re.search(r"(\w+Error: .+)", out)):
        try:  # error memory: how this error was fixed before (0 tokens)
            from jarvis.core import errmem
            if (k := errmem.lookup(m.group(1))) and k.get("fix"):
                hint = f"\n(last time this error was fixed by: {k['fix']})"
        except Exception:  # noqa: BLE001
            pass
    return _cut(f"$ {cmd}\nexit: {code} ({time.monotonic() - t0:.1f} s)\n{out}") + hint


def t_run_project(run: Run, seconds: float = 8) -> str:
    """Start the project the right way for a few seconds and report what it printed (a web page: its errors)."""
    from coder import preview, runcheck
    if preview.page_root(run.root) is not None and not (run.root / "package.json").exists():
        probs = preview.selftest(run.root) or []
        return "the page opens; buttons clicked; " + ("errors:\n" + "\n".join(probs) if probs else "no errors")
    pj = run.root / "package.json"
    if pj.exists():
        if not (run.root / "node_modules").exists():
            return "NEEDS_YES: the packages aren't installed (npm install); ask the owner first"
        scripts = __import__("json").loads(pj.read_text(encoding="utf-8")).get("scripts") or {}
        script = next((s for s in ("dev", "start", "serve") if s in scripts), None)
        if script is None:
            return "package.json has no dev/start script"
        return t_run(run, f"npm run {script}", timeout=seconds)
    entry = runcheck.entry(run)
    if entry is None:
        return "I can't tell how to start it (no main.py/app.py/index.html): read the README or ask"
    try:
        import psutil
        if psutil.virtual_memory().available < 700e6:
            return ("RAM is almost full (under 0.7 GB free): starting it now could freeze the laptop. Ask the owner to "
                    "close something (Brave tabs) first.")
    except Exception:  # noqa: BLE001
        pass
    return t_run(run, f"python3 {shlex.quote(entry)}", timeout=seconds)


# ---------------------------------------------------------------- see
def t_screenshot(run: Run) -> str:
    """A picture of the web page (headless) or of the app's own window (it is started for a moment)."""
    from coder import preview
    shots = run.dir / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    out = shots / f"{len(list(shots.glob('*.png'))) + 1:02d}.png"
    if preview.page_root(run.root) is not None:
        png = preview.screenshot(run.root)
        if not png:
            return "couldn't take a picture of the page"
        out.write_bytes(png)
        return f"screenshot saved: {out.name} (use look to ask about it)"
    from coder import runcheck
    entry = runcheck.entry(run)
    if entry is None:
        return "nothing to take a picture of (no page and no program entry)"
    return _window_shot(run, entry, out)


def _window_shot(run: Run, entry: str, out: Path) -> str:
    """Start the app, find its window by process id, take that window's picture, close the app."""
    p = subprocess.Popen([python_of(run.root), entry], cwd=run.root, stdout=subprocess.DEVNULL,
                         stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        wid = None
        for _ in range(16):
            time.sleep(0.5)
            if p.poll() is not None:
                err = (p.stderr.read() if p.stderr else b"").decode(errors="replace")
                return _cut(f"the program ended before a window appeared:\n{err}")
            lines = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True).stdout.splitlines()
            wid = next((ln.split()[0] for ln in lines if len(ln.split()) > 2 and ln.split()[2] == str(p.pid)), None)
            if wid:
                break
        if not wid:
            return "no window appeared (a terminal program? use run_project)"
        time.sleep(0.8)
        r = subprocess.run(["import", "-window", wid, str(out)], capture_output=True, timeout=10)
        if r.returncode or not out.exists():
            from jarvis.core import ocr
            g = ocr._geometry(int(wid, 16))
            if g is None:
                return "couldn't take the window's picture"
            import mss
            import mss.tools
            x, y, w, h = g[:4]
            with mss.mss() as m:
                img = m.grab({"left": x, "top": y, "width": w, "height": h})
                mss.tools.to_png(img.rgb, img.size, output=str(out))
        return f"screenshot saved: {out.name} (use look to ask about it)"
    finally:
        try:
            os.killpg(p.pid, 15)
        except OSError:
            pass


def t_look(run: Run, question: str, shot: str = "") -> str:
    import base64
    shots = sorted((run.dir / "shots").glob("*.png")) if (run.dir / "shots").exists() else []
    pic = (run.dir / "shots" / shot) if shot else (shots[-1] if shots else None)
    if pic is None or not pic.exists():
        return "no screenshot yet: use screenshot first"
    from jarvis.core import llm
    r = llm.chat([{"role": "user", "content": [
        {"type": "text", "text": f"A screenshot of the app being built. {question} Answer briefly and concretely "
                                 "(positions, colours, what looks broken). No praise."},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(pic.read_bytes()).decode()}}]}],
        tier="vision", purpose="coder_look", max_tokens=500)
    run.tokens += int(r.prompt_tokens or 0) + int(r.completion_tokens or 0)
    return _cut(r.text or "(no answer)", 1500)


def t_page_errors(run: Run) -> str:
    from coder import preview
    if preview.page_root(run.root) is None:
        return "this project has no web page"
    probs = preview.seen(run.root) + (preview.selftest(run.root) or [])
    return "\n".join(dict.fromkeys(probs)) or "no errors on the page"


# ---------------------------------------------------------------- the laptop's other knowledge
def t_ports(run: Run, port: int = 0) -> str:
    from jarvis.core import ports
    return _cut(ports.check(int(port)) if port else ports.list_all(), 1200)


def t_history(run: Run, path: str = "") -> str:
    from jarvis.core import timemachine
    try:
        return _cut(timemachine.history(run.root, path, 10), 1500)
    except Exception as e:  # noqa: BLE001
        return f"no history: {e}"


def t_docs(run: Run, query: str) -> str:
    try:
        from jarvis.tools.general.search_knowledge import search_knowledge
        return _cut(str(search_knowledge(query)), 1500)
    except Exception as e:  # noqa: BLE001
        return f"no docs index: {e}"


TOOLS = {
    "list": (t_list, "list(path='.'): files under a folder"),
    "find": (t_find, "find(name): files whose name contains it"),
    "grep": (t_grep, "grep(pattern, path='.'): lines matching a regex, file:line: text"),
    "read": (t_read, "read(path, start=1, end=0): numbered lines of a file (200 at a time)"),
    "edit": (t_edit, "edit(path, old, new): replace the exact old text (unique, copied from read) with new"),
    "write": (t_write, "write(path, content): create a NEW file (or rewrite a small one completely)"),
    "run": (t_run, "run(command, timeout=60): run a safe command in the project folder (python/node/npm run/pytest/git status…)"),
    "run_project": (t_run_project, "run_project(): start the project briefly and see its output / page errors"),
    "screenshot": (t_screenshot, "screenshot(): a picture of the web page or the app's window"),
    "look": (t_look, "look(question): ask the vision model about the last screenshot"),
    "page_errors": (t_page_errors, "page_errors(): the web page's JavaScript errors and missing files"),
    "ports": (t_ports, "ports(port=0): what is running on a port (0 = all)"),
    "history": (t_history, "history(path=''): the file's / project's past versions (time machine)"),
    "docs": (t_docs, "docs(query): search the indexed docs and notes"),
}


def call(run: Run, name: str, args: dict) -> str:
    fn = TOOLS.get(name, (None, ""))[0]
    if fn is None:
        return f"no tool '{name}'. Tools: {', '.join(TOOLS)}"
    try:
        return fn(run, **{k: v for k, v in (args or {}).items() if k in fn.__code__.co_varnames})
    except Exception as e:  # noqa: BLE001 - a tool error is an observation, never a crash of the loop
        return f"tool error: {type(e).__name__}: {str(e)[:300]}"


# ---------------------------------------------------------------- the schemas the model calls (native tool calling)
def _schema(name: str, desc: str, props: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props, "required": required}}}


_S, _I = {"type": "string"}, {"type": "integer"}
SCHEMAS = [
    _schema("list", "List the project's files under a folder.", {"path": _S}, []),
    _schema("find", "Files whose name contains the text.", {"name": _S}, ["name"]),
    _schema("grep", "Lines matching a regex (file:line: text).", {"pattern": _S, "path": _S}, ["pattern"]),
    _schema("read", "Numbered lines of a file (200 at a time).", {"path": _S, "start": _I, "end": _I}, ["path"]),
    _schema("edit", "Replace the exact old text (copied from read, unique) with new text.",
            {"path": _S, "old": _S, "new": _S}, ["path", "old", "new"]),
    _schema("write", "Create a NEW file with this content (or rewrite a small file completely).",
            {"path": _S, "content": _S}, ["path", "content"]),
    _schema("run", "Run a safe command in the project folder (python, node, npm run/test, pytest, git status...).",
            {"command": _S, "timeout": _I}, ["command"]),
    _schema("run_project", "Start the project briefly: its output, or the web page's errors after clicking its buttons.",
            {}, []),
    _schema("screenshot", "A picture of the web page or of the app's window.", {}, []),
    _schema("look", "Ask the vision model about the last screenshot.", {"question": _S}, ["question"]),
    _schema("page_errors", "The web page's JavaScript errors and missing files.", {}, []),
    _schema("ports", "What runs on a port (0 = all ports).", {"port": _I}, []),
    _schema("history", "Past versions of a file / the project (time machine).", {"path": _S}, []),
    _schema("docs", "Search the indexed docs and notes.", {"query": _S}, ["query"]),
    _schema("done", "The goal is reached AND checked: say what you did in 1-3 short sentences.", {"summary": _S}, ["summary"]),
    _schema("ask", "Ask the owner ONE question (a real choice, or a command that NEEDS_YES).",
            {"question": _S, "command": _S}, ["question"]),
]
