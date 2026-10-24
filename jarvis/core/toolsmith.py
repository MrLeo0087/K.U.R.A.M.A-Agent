"""Toolsmith (P7c): when no tool fits, KURAMA offers to build a small one, but ONLY after the user says yes.

handle(task) flow:
  1. A saved skill that fits -> tell the agent to use it (zero generation tokens).
  2. Consent: "I don't have a tool for that. Should I make a small one?" No -> stop (no LLM call).
  3. Generate with the fast tier (smart fallback), strict json_schema -> ToolSpec.
  4. Static AST check (allowlisted imports, jarvis_helpers only, no dunders/underscores/eval/open/...).
     A failure is regenerated once with the reason.
  5. Second yes for sensitive tools (network, file writes, shell, system, or a personal-data task),
     showing the plain summary and, for shell, the exact commands.
  6. Sandbox run: `python -I` runner, cwd data/sandbox/<id>/, rlimits, audit hook, 15 s wall timeout,
     stripped env. One retry on error with the (capped) traceback.
  7. Ask "save this tool for next time?": yes -> data/skills/<name>.py + .json, a tool in group "skills" (LRU 20);
     one-off -> sandbox folder and code deleted.
"""
from __future__ import annotations

import ast
import importlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import types
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from jarvis.core import config, safety, store

log = logging.getLogger("jarvis.toolsmith")

RUNNER = Path(__file__).with_name("sandbox") / "runner.py"
HELPERS = ("http_get", "read_text", "write_text", "run_cmd")
HELPER_NEEDS = {"http_get": "network", "read_text": "read_files", "write_text": "write_files", "run_cmd": "shell"}
SENSITIVE_NEEDS = {"network", "write_files", "shell", "system"}
DRY_RUN_CMDS = False  # smoke tests: run_cmd only reports what it would run
last_tokens = 0  # generation tokens of the most recent creation (for reports)
_tried: dict[str, float] = {}  # request -> time of the last make_tool attempt (one attempt per request)
TRY_TTL_S = 120

_PERSONAL = re.compile(
    r"\b(?:passwords?|passwd|credentials?|tokens?|secrets?|api ?keys?|private ?keys?|ssh|bank|credit ?card|"
    r"cards?|otp|pin|e-?mails?|mail|messages?|sms|send|post|upload|delete|remove|erase|wipe|contacts?|"
    r"phone numbers?|address|personal|private|diary|photos?|whatsapp|telegram)\b|"
    r"पासवर्ड|मेटाउ|मिटा|पठाउ|भेज|फोटो|सन्देश|संदेश", re.I)
_PATHS = re.compile(r"(?:(?<=\s)|^|(?<=[\"']))((?:~|/)[^\s\"',;]+)")

BANNED_NAMES = {"eval", "exec", "compile", "__import__", "open", "globals", "locals", "vars", "getattr",
                "setattr", "delattr", "breakpoint", "input", "help", "exit", "quit", "memoryview", "dir",
                "__builtins__", "os", "sys", "subprocess", "socket", "shutil", "ctypes", "importlib",
                "pickle", "marshal", "builtins", "posix", "io", "pathlib", "signal", "threading",
                "multiprocessing", "asyncio", "inspect", "gc", "code", "codeop"}
BANNED_ATTRS = {"format_map", "mro", "system", "popen", "modules", "load_module", "exec_module"}
_FRAME_ATTR = re.compile(r"^(?:f|gi|cr|ag|tb|co)_")

CONSENT = {"en": "I don't have a tool for that yet, but I can create one. Should I create a tool for it?",
           "hi": "मेरे पास इसके लिए अभी कोई टूल नहीं है, पर मैं बना सकता हूँ। क्या मैं इसके लिए टूल बना दूँ?",
           "ne": "मसँग यसको लागि अहिले टुल छैन, तर म बनाउन सक्छु। के म यसको लागि टुल बनाऊँ?"}
SAVE_ASK = {"en": "Done. Should I save this tool for next time?",
            "hi": "हो गया। क्या यह टूल आगे के लिए सेव कर दूँ?",
            "ne": "भयो। यो टुल पछिको लागि सेभ गरूँ?"}
SECOND = {"en": "The tool will: {summary}{cmds} Is it okay to run it?",
          "hi": "यह टूल यह करेगा: {summary}{cmds} क्या इसे चलाऊँ?",
          "ne": "यो टुलले यो गर्छ: {summary}{cmds} चलाऊँ?"}
DECLINED = "The user said no, so no tool was made or run. Tell them kindly that's fine."
GEN_PROMPT = (
    "You write one tiny, safe Python tool for the assistant KURAMA. Define `def run(arg: str) -> str` that "
    "returns a short plain-text answer. Allowed imports only: {mods}; and `from jarvis_helpers import ...` with "
    "http_get(url)->str, read_text(path)->str, write_text(path, text)->str, run_cmd([...])->str with the "
    "list written inline, e.g. run_cmd(['gsettings', 'set', key, value]) (binaries: {cmds}). If the request "
    "lacks a value the tool needs, set arg empty and make run() return a short question asking for it. "
    "Never use open, os, sys, subprocess, eval, exec, getattr, dunder "
    "names or names starting with _. possible=false with a short kind reason if it can't be done this way. "
    "reusable=true if the same tool would help again with a different arg: make it general, the arg is what "
    "the user would change next time (e.g. the target date, amount, city or image path; get today with "
    "datetime.date.today()); arg_hint says what arg is (e.g. 'target date YYYY-MM-DD') and arg is the value "
    "for this request. name: general snake_case with no specific values. "
    "summary: one plain sentence a non-technical person understands. needs: what it touches (none if pure). "
    "Change ONLY what the user asked for; never reset or replace other settings (themes, icons, cursors, "
    "fonts, files). Prefer the smallest change (GNOME light/dark = org.gnome.desktop.interface color-scheme)."
)


class ToolSpec(BaseModel):
    """A small generated tool."""
    possible: bool = Field(description="false if this can't be done safely with the allowed modules")
    reason: str = Field(description="short reason when not possible, else empty")
    reusable: bool = Field(description="useful again later with a different arg")
    name: str = Field(description="snake_case tool name")
    summary: str = Field(description="what it does, one plain sentence")
    needs: list[Literal["none", "network", "read_files", "write_files", "shell", "system"]]
    arg_hint: str = Field(description="what the arg means, empty if unused")
    arg: str = Field(description="arg value for this request")
    code: str = Field(description="Python source defining run(arg: str) -> str")


@dataclass
class Check:
    ok: bool
    reason: str = ""
    helpers: set = field(default_factory=set)
    commands: list = field(default_factory=list)  # [["gsettings", "set", ..., "<value>"]]


@dataclass
class RunResult:
    ok: bool
    output: str = ""
    error: str = ""
    trace: str = ""


# --- static check ---
def allowed_cmds() -> list[str]:
    return [c for c in config.SHELL_ALLOWLIST if c not in config.TOOLSMITH_CMD_DENY]


def _module_ok(name: str) -> bool:
    return name in config.SANDBOX_IMPORTS


def _chain(node: ast.AST) -> tuple[str, list[str]] | None:
    attrs: list[str] = []
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    return (node.id, attrs[::-1]) if isinstance(node, ast.Name) else None


def check_code(code: str) -> Check:
    """Allowlist check of generated code. Check.ok False -> .reason says why."""
    if not code or len(code) > 8000:
        return Check(False, "code is empty or too long")
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return Check(False, f"syntax error: {e.msg} (line {e.lineno})")
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    modules: dict[str, str] = {}  # local alias -> real module name
    helpers: set[str] = set()
    commands: list[list[str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if not _module_ok(a.name):
                    return Check(False, f"import {a.name} is not allowed")
                if a.asname:
                    modules[a.asname] = a.name
                else:
                    modules[a.name.split(".")[0]] = a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level or not mod:
                return Check(False, "relative imports are not allowed")
            for a in node.names:
                if a.name == "*" or a.name.startswith("_"):
                    return Check(False, f"from {mod} import {a.name} is not allowed")
                if mod == "jarvis_helpers":
                    if a.name not in HELPERS or (a.asname and a.asname != a.name):
                        return Check(False, f"jarvis_helpers has no {a.name}")
                    helpers.add(a.name)
                    continue
                if not _module_ok(mod):
                    return Check(False, f"import from {mod} is not allowed")
                obj = getattr(importlib.import_module(mod), a.name, None)
                if isinstance(obj, types.ModuleType) and not _module_ok(f"{mod}.{a.name}"):
                    return Check(False, f"from {mod} import {a.name} is not allowed")
                if isinstance(obj, types.ModuleType):
                    modules[a.asname or a.name] = f"{mod}.{a.name}"
        elif isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)):
            return Check(False, "async code is not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_") or node.attr in BANNED_ATTRS or _FRAME_ATTR.match(node.attr):
                return Check(False, f"attribute .{node.attr} is not allowed")
        elif isinstance(node, ast.Name):
            if node.id in BANNED_NAMES or node.id.startswith("__"):
                return Check(False, f"{node.id} is not allowed")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "__" in node.value:
            return Check(False, "strings with double underscores are not allowed")
        elif isinstance(node, ast.arg) and node.arg.startswith("__"):
            return Check(False, f"{node.arg} is not allowed")
    # Module objects may only be used as `module.attr` and never reach a non-allowlisted submodule.
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in modules and not isinstance(node.ctx, ast.Store):
            parent = parents.get(node)
            if not (isinstance(parent, ast.Attribute) and parent.value is node):
                return Check(False, f"module {node.id} can only be used as {node.id}.something")
        if isinstance(node, ast.Attribute) and not isinstance(parents.get(node), ast.Attribute):
            ch = _chain(node)
            if ch and ch[0] in modules:
                obj: object = importlib.import_module(modules[ch[0]].split(".")[0])
                for part in modules[ch[0]].split(".")[1:] + ch[1]:
                    parent_obj, obj = obj, getattr(obj, part, None)
                    if obj is None and hasattr(parent_obj, "__path__") and not _module_ok(
                            f"{getattr(parent_obj, '__name__', '')}.{part}"):
                        return Check(False, f"{'.'.join([ch[0]] + ch[1])} is not allowed")
                    if isinstance(obj, types.ModuleType) and not _module_ok(obj.__name__):
                        return Check(False, f"{'.'.join([ch[0]] + ch[1])} reaches a module that is not allowed")
        if isinstance(node, ast.Name) and node.id in HELPERS:
            if node.id not in helpers:
                return Check(False, f"{node.id} must be imported from jarvis_helpers")
            parent = parents.get(node)
            if not (isinstance(parent, ast.Call) and parent.func is node):
                return Check(False, f"{node.id} can only be called directly")
            if node.id == "run_cmd":
                args = parent.args
                if len(args) != 1 or not isinstance(args[0], (ast.List, ast.Tuple)) or not args[0].elts:
                    return Check(False, "run_cmd needs one literal list like ['gsettings', 'get', ...]")
                first = args[0].elts[0]
                if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                    return Check(False, "run_cmd's first item must be a literal binary name")
                if first.value.rsplit("/", 1)[-1] not in allowed_cmds():
                    return Check(False, f"{first.value} is not an allowed command")
                commands.append([e.value if isinstance(e, ast.Constant) and isinstance(e.value, str)
                                 else "<value>" for e in args[0].elts])
    if not any(isinstance(n, ast.FunctionDef) and n.name == "run" for n in tree.body):
        return Check(False, "code must define def run(arg: str) -> str at top level")
    return Check(True, "", helpers, commands)


# --- sandbox ---
def _env() -> dict:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "LANG": "C.UTF-8",
           "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
    for k in ("DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "XDG_CURRENT_DESKTOP", "WAYLAND_DISPLAY"):
        if os.environ.get(k):  # needed by gsettings & co; not secrets
            env[k] = os.environ[k]
    return env


def named_paths(text: str) -> list[str]:
    """Absolute or ~ paths the user wrote in the task (allowed write targets)."""
    out = []
    for m in _PATHS.finditer(text or ""):
        p = m.group(1).rstrip(".?!")
        if len(p) > 1 and p not in ("/", "~"):
            out.append(str(Path(p).expanduser()))
    return out


def run_sandbox(code: str, arg: str = "", write_paths: list[str] | tuple = (), timeout: float | None = None,
                cpu_s: int | None = None, mem_mb: int | None = None, keep_dir: bool = False) -> RunResult:
    """Run generated code in a fresh data/sandbox/<id>/ folder with rlimits; the folder is removed after."""
    run_dir = Path(config.SANDBOX_DIR) / uuid.uuid4().hex[:10]
    run_dir.mkdir(parents=True, exist_ok=True)
    code_path, out_path = run_dir / "tool.py", run_dir / ".out.json"
    code_path.write_text(code, encoding="utf-8")
    spec = {"arg": arg, "home": str(Path.home()), "sandbox": str(run_dir), "write_paths": list(write_paths),
            "allow_cmds": allowed_cmds(), "dry_run_cmds": DRY_RUN_CMDS,
            "mem_mb": mem_mb or config.SANDBOX_MEM_MB, "cpu_s": cpu_s or config.SANDBOX_CPU_S,
            "nofile": config.SANDBOX_NOFILE, "out_max": config.SANDBOX_STDOUT_MAX, "fsize": 2_000_000}
    try:
        with open(out_path, "wb") as out, open(run_dir / ".err.txt", "wb") as err:
            p = subprocess.run([sys.executable, "-I", str(RUNNER), str(code_path)], cwd=run_dir,
                               input=json.dumps(spec).encode(), stdout=out, stderr=err, env=_env(),
                               timeout=timeout or config.SANDBOX_TIMEOUT_S, start_new_session=True)
        raw = out_path.read_bytes()[: config.SANDBOX_STDOUT_MAX * 3].decode("utf-8", "replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            err_txt = (run_dir / ".err.txt").read_bytes()[-600:].decode("utf-8", "replace")
            why = f"killed (exit {p.returncode}: likely CPU or memory limit)" if p.returncode else "no result"
            return RunResult(False, error=why, trace=err_txt)
        if data.get("ok"):
            return RunResult(True, output=str(data.get("out", ""))[: config.SANDBOX_STDOUT_MAX])
        return RunResult(False, error=data.get("error", "error"), trace=data.get("trace", ""))
    except subprocess.TimeoutExpired:
        return RunResult(False, error=f"timed out after {int(timeout or config.SANDBOX_TIMEOUT_S)} s")
    finally:
        if not keep_dir:
            shutil.rmtree(run_dir, ignore_errors=True)


# --- generation ---
def _lang(text: str, lang: str | None) -> str:
    if lang in CONSENT:
        return lang
    from jarvis.core.planner import detect_lang
    return detect_lang(text or "")


def generate(task: str, feedback: str = "") -> ToolSpec:
    """One fast-tier strict json_schema call (smart tier fallback). Raises llm.LLMError."""
    from jarvis.core import llm

    system = GEN_PROMPT.format(mods=", ".join(config.SANDBOX_IMPORTS), cmds=", ".join(allowed_cmds()))
    user = f"Task: {task}\nToday: {date.today().isoformat()}"
    if feedback:
        user += f"\nYour previous code failed: {feedback[:600]}\nFix it."
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        return llm.structured(msgs, ToolSpec, tier=config.TOOLSMITH_TIER, purpose="toolsmith",
                              max_tokens=config.TOOLSMITH_MAX_TOKENS, priority="interactive")
    except llm.LLMError as e:
        log.info("toolsmith fast tier failed, trying smart: %s", e)
        return llm.structured(msgs, ToolSpec, tier="smart", purpose="toolsmith",
                              max_tokens=config.TOOLSMITH_MAX_TOKENS, priority="interactive")


def _needs(spec: ToolSpec, chk: Check) -> set[str]:
    needs = {n for n in spec.needs if n != "none"} | {HELPER_NEEDS[h] for h in chk.helpers}
    return needs


def is_sensitive(needs: set[str] | list[str], task: str) -> bool:
    return bool(set(needs) & SENSITIVE_NEEDS) or bool(_PERSONAL.search(task or ""))


def _second_prompt(summary: str, commands: list[list[str]], lang: str) -> str:
    cmds = ""
    if commands:
        cmds = " Commands: " + "; ".join(" ".join(c) for c in commands[:4]) + "."
    return SECOND.get(lang, SECOND["en"]).format(summary=summary.rstrip(". ") + ".", cmds=cmds)


def _spec_ok(spec: ToolSpec) -> Check:
    return check_code(spec.code) if spec.possible else Check(True)


def handle(task: str, user_text: str | None = None, lang: str | None = None) -> str:
    """The make_tool flow. Returns text for the agent's LLM (<= ~800 chars)."""
    global last_tokens
    full = user_text or task
    if user_text and len(user_text.split()) < 8 and task.lower() not in user_text.lower():
        full = f"{task} (the user said: {user_text})"  # "can you create such tool": the task is in `task`
    lang = _lang(full, lang)
    hit = find_skill(task + " " + (user_text or ""))
    if hit:
        return (f"A saved tool fits: {hit['name']} ({hit['summary']}). Call skills with action='use', name="
                f"'{hit['name']}' and arg = {hit.get('arg_hint') or 'empty'}.")
    key = (safety.context().get("request") or full).strip().lower()
    now = time.time()
    if now - _tried.get(key, 0) < TRY_TTL_S:
        return "make_tool already ran for this request. Don't call it again; tell the user the outcome kindly."
    for k in [k for k, t in _tried.items() if now - t > TRY_TTL_S]:
        _tried.pop(k, None)
    _tried[key] = now
    if not safety.ask(CONSENT.get(lang, CONSENT["en"])):
        return DECLINED
    from jarvis.core import llm

    before = store.tokens_for_purpose("toolsmith")
    try:
        spec = generate(full)
        chk = _spec_ok(spec)
        if spec.possible and not chk.ok:
            spec = generate(full, f"the safety check refused it: {chk.reason}")
            chk = _spec_ok(spec)
    except llm.LLMError as e:
        log.warning("toolsmith generation failed: %s", e)
        return "Sorry: I couldn't build the tool right now (the model is unavailable). Tell the user kindly."
    finally:
        last_tokens = store.tokens_for_purpose("toolsmith") - before
    if not spec.possible:
        return f"Not possible: {spec.reason[:200]}. Explain this to the user kindly, in one sentence."
    if not chk.ok:
        return f"I couldn't make a safe tool for that ({chk.reason}). Tell the user kindly; don't call make_tool again."
    needs = _needs(spec, chk)
    asked = False
    if is_sensitive(needs, full):
        if not safety.ask(_second_prompt(spec.summary, chk.commands, lang)):
            return DECLINED
        asked = True
    paths = named_paths(full)
    res = run_sandbox(spec.code, spec.arg, paths)
    if not res.ok:
        before = store.tokens_for_purpose("toolsmith")
        try:
            spec2 = generate(full, f"{res.error}\n{res.trace[-500:]}")
        except llm.LLMError:
            spec2 = None
        last_tokens += store.tokens_for_purpose("toolsmith") - before
        chk2 = _spec_ok(spec2) if spec2 else Check(False, "no retry")
        if spec2 and spec2.possible and chk2.ok:
            needs2 = _needs(spec2, chk2)
            if is_sensitive(needs2, full) and (not asked or needs2 - needs):
                if not safety.ask(_second_prompt(spec2.summary, chk2.commands, lang)):
                    return DECLINED
            spec, chk, needs = spec2, chk2, needs2
            res = run_sandbox(spec.code, spec.arg, paths)
    log.info("toolsmith %s: %d generation tokens, ok=%s, reusable=%s", spec.name, last_tokens, res.ok, spec.reusable)
    if not res.ok:
        return f"The tool failed ({res.error[:150]}). Tell the user kindly it didn't work."
    # the result first, then the user decides: keep the tool for next time, or use it once and drop it
    if safety.ask(f"{_short(res.output)} {SAVE_ASK.get(lang, SAVE_ASK['en'])}"):
        meta = save_skill(spec, full, needs, chk)
        note = f" (Saved as tool '{meta['name']}' for next time.)"
    else:
        note = " (Used once and removed, as the user asked.)"
    return f"Result: {res.output[:700]}{note}"


def _short(text: str, n: int = 160) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "..."


# --- skills (saved reusable tools) ---
def _skills_dir() -> Path:
    d = Path(config.SKILLS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_name(name: str) -> str:
    n = re.sub(r"[^a-z0-9_]+", "_", (name or "tool").lower()).strip("_")[:40] or "tool"
    if n[0].isdigit():
        n = "skill_" + n
    from jarvis.core import registry

    t = registry.REGISTRY.tools.get(n)
    if t is not None and (t.metadata or {}).get("group") != "skills":
        n = "skill_" + n
    return n


def list_saved() -> list[dict]:
    out = []
    for p in sorted(_skills_dir().glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def load_meta(name: str) -> dict | None:
    p = _skills_dir() / f"{name}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_meta(meta: dict) -> None:
    (_skills_dir() / f"{meta['name']}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                                                        encoding="utf-8")


def save_skill(spec: ToolSpec, task: str, needs: set[str], chk: Check) -> dict:
    name = _safe_name(spec.name)
    now = time.time()
    meta = {"name": name, "task": task[:300], "summary": spec.summary[:200], "needs": sorted(needs) or ["none"],
            "arg_hint": spec.arg_hint[:120], "commands": chk.commands[:4], "created": now, "last_used": now,
            "uses": 1, "sensitive": is_sensitive(needs, task), "gen_tokens": last_tokens}
    (_skills_dir() / f"{name}.py").write_text(spec.code, encoding="utf-8")
    _write_meta(meta)
    register(meta)
    _prune()
    return meta


def _prune() -> None:
    metas = sorted(list_saved(), key=lambda m: m.get("last_used", 0), reverse=True)
    for m in metas[config.SKILLS_MAX:]:
        delete(m["name"])


def delete(name: str) -> bool:
    d = _skills_dir()
    found = False
    for ext in (".py", ".json"):
        p = d / f"{name}{ext}"
        if p.exists():
            p.unlink()
            found = True
    from jarvis.core import meta as meta_mod, registry

    t = registry.REGISTRY.tools.get(name)
    if t is not None and (t.metadata or {}).get("group") == "skills":
        registry.REGISTRY.tools.pop(name, None)
    meta_mod._cache.clear()
    return found


_STOP = {"the", "a", "an", "to", "of", "for", "in", "on", "and", "is", "it", "me", "my", "what", "how", "can",
         "you", "please", "jarvis", "tell", "do", "i", "this", "that", "with", "from", "are", "be", "make",
         "tool", "small", "new", "want", "need", "give", "show", "get", "find", "use", "many", "much"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Zऀ-ॿ]{3,}", (text or "").lower()) if w not in _STOP}


def find_skill(text: str) -> dict | None:
    """Best saved skill whose task/summary/name shares >= 60% of the request's content words."""
    words = _words(text)
    if not words:
        return None
    best, score = None, 0.0
    for m in list_saved():
        s = len(words & _words(" ".join([m.get("task", ""), m.get("summary", ""), m.get("name", "").replace("_", " ")])))
        s /= len(words)
        if s > score:
            best, score = m, s
    return best if score >= 0.6 else None


def run_skill(name: str, arg: str = "") -> str:
    meta = load_meta(name)
    p = _skills_dir() / f"{name}.py"
    if meta is None or not p.exists():
        return f"error: no saved skill called {name!r}"
    code = p.read_text(encoding="utf-8")
    chk = check_code(code)  # re-check: the file could have been edited
    if not chk.ok:
        return f"error: saved skill {name} failed the safety check ({chk.reason})"
    ctx = safety.context()
    res = run_sandbox(code, arg, named_paths(ctx.get("user_text", "") + " " + arg))
    meta["uses"] = int(meta.get("uses", 0)) + 1
    meta["last_used"] = time.time()
    _write_meta(meta)
    if not res.ok:
        return f"error: the skill failed ({res.error[:150]})"
    return res.output[:780]


def use_skill(name: str, arg: str = "") -> str:
    """Run a saved skill; sensitive ones ask first (same prompt as the second confirm)."""
    meta = load_meta(name)
    if meta is None:
        return f"error: no saved skill called {name!r}; saved: {', '.join(m['name'] for m in list_saved()) or 'none'}"
    if meta.get("sensitive"):
        ctx = safety.context()
        lang = _lang(ctx.get("user_text", ""), ctx.get("lang"))
        if not safety.ask(_second_prompt(meta.get("summary", name), meta.get("commands") or [], lang)):
            return DECLINED
    return run_skill(name, arg)


def register(meta: dict, reg=None) -> None:
    """Expose a saved skill as a tool in group "skills" (sensitive -> safety confirm)."""
    from jarvis.core import meta as meta_mod, registry

    reg = reg or registry.REGISTRY
    name = meta["name"]

    def skill(arg: str = "") -> str:
        return run_skill(name, arg)

    skill.__name__ = name
    skill.__doc__ = f"{meta.get('summary', name)}\n\nArgs:\n    arg: {meta.get('arg_hint') or 'optional input'}"
    reg.tool(name=name, group="skills", safety="confirm" if meta.get("sensitive") else "safe",
             description=(meta.get("summary") or name)[:160])(skill)
    meta_mod._cache.clear()


def register_saved(reg) -> int:
    """Called by Registry.discover: register every saved skill (reads small JSON files only)."""
    n = 0
    d = Path(config.SKILLS_DIR)
    if not d.is_dir():
        return 0
    for m in list_saved():
        if (d / f"{m.get('name', '')}.py").exists():
            try:
                register(m, reg)
                n += 1
            except Exception as e:
                log.warning("could not register skill %s: %s", m.get("name"), e)
    return n


def skill_names() -> list[str]:
    return [m["name"] for m in sorted(list_saved(), key=lambda m: m.get("last_used", 0), reverse=True)]
