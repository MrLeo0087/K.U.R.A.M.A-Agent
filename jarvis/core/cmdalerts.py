"""Long-command alerts: any terminal command that runs longer than N minutes tells you when it ends (0 tokens).

A tiny bash hook (~/.config/kurama/cmd-notify.bash, sourced from ~/.bashrc) appends one JSON line per long command
to ~/.local/share/kurama/commands.jsonl: the command, exit code, seconds and folder. No network, no token. The
process_watch worker reads new lines and alerts: on the desktop when you're at the laptop, on Telegram when the
screen is locked (or always, config.CMD_ALERT_PHONE). Ctrl+C (exit 130) is not reported.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from jarvis.core import config, notify, store

HOOK = Path.home() / ".config" / "kurama" / "cmd-notify.bash"
EVENTS = Path.home() / ".local" / "share" / "kurama" / "commands.jsonl"
BASHRC = Path.home() / ".bashrc"
MARK = "# KURAMA command alerts"
SOURCE_LINE = f'[ -f "{HOOK}" ] && . "{HOOK}"  {MARK}'

HOOK_TEXT = r'''# KURAMA: tell me when a long terminal command finishes. Installed by KURAMA ("command alerts off" removes it).
KURAMA_CMD_MIN_SECS=${KURAMA_CMD_MIN_SECS:-%(secs)d}
__kurama_ready=1
__kurama_json() { local s=${1//\\/\\\\}; s=${s//\"/\\\"}; s=${s//$'\n'/ }; s=${s//$'\t'/ }; printf '"%%s"' "$s"; }
__kurama_pre() {
  [ -n "$COMP_LINE" ] && return
  [ "$__kurama_ready" = 1 ] || return
  __kurama_ready=0; __kurama_t0=$SECONDS
}
__kurama_post() {
  local rc=$? d
  if [ -n "$__kurama_t0" ]; then
    d=$((SECONDS - __kurama_t0))
    if [ "$d" -ge "$KURAMA_CMD_MIN_SECS" ] && [ "$rc" != 130 ]; then
      mkdir -p "%(dir)s"
      printf '{"cmd":%%s,"rc":%%d,"secs":%%d,"cwd":%%s,"t":%%d}\n' \
        "$(__kurama_json "$(HISTTIMEFORMAT= history 1 | sed 's/^ *[0-9]* *//')")" "$rc" "$d" \
        "$(__kurama_json "$PWD")" "$(date +%%s)" >> "%(events)s"
    fi
  fi
  __kurama_t0=""; __kurama_ready=1
  return $rc
}
trap '__kurama_pre' DEBUG
case ";$PROMPT_COMMAND;" in *";__kurama_post;"*) ;; *) PROMPT_COMMAND="__kurama_post${PROMPT_COMMAND:+;$PROMPT_COMMAND}";; esac
'''


def installed() -> bool:
    try:
        return MARK in BASHRC.read_text()
    except OSError:
        return False


def install(minutes: float | None = None) -> str:
    secs = int(max(10, (minutes or config.CMD_ALERT_MIN) * 60))
    HOOK.parent.mkdir(parents=True, exist_ok=True)
    HOOK.write_text(HOOK_TEXT % {"secs": secs, "dir": EVENTS.parent, "events": EVENTS})
    if not installed():
        text = BASHRC.read_text() if BASHRC.exists() else ""
        BASHRC.write_text(text.rstrip("\n") + "\n" + SOURCE_LINE + "\n")
    if not store.kv_get("cmdlog_offset"):
        store.kv_set("cmdlog_offset", str(EVENTS.stat().st_size if EVENTS.exists() else 0))
    return f"Command alerts are on: commands longer than {_human(secs)} will tell you when they finish. " \
                    f"Open a new terminal (or run: source ~/.bashrc) to start."


def uninstall() -> str:
    if installed():
        lines = [ln for ln in BASHRC.read_text().splitlines() if MARK not in ln]
        BASHRC.write_text("\n".join(lines) + "\n")
    HOOK.unlink(missing_ok=True)
    return "Command alerts are off (new terminals won't report long commands)."


def status() -> str:
    if not installed():
        return "Command alerts are off."
    m = re.search(r"KURAMA_CMD_MIN_SECS:-(\d+)", HOOK.read_text()) if HOOK.exists() else None
    recent = [e for e in recent_events(5)]
    head = f"Command alerts are on (commands longer than {_human(int(m.group(1))) if m else '?'})."
    if recent:
        head += " Recent: " + "; ".join(f"{'ok' if e['rc'] == 0 else 'failed'} {_human(e['secs'])} {e['cmd'][:50]}"
                                        for e in recent)
    return head


def _human(secs: int) -> str:
    m, s = divmod(int(secs), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m}m" if h else (f"{m} min" if not s else f"{m}m {s}s") if m else f"{s}s"


def recent_events(n: int = 5) -> list[dict]:
    try:
        lines = EVENTS.read_text(errors="replace").splitlines()[-n:]
    except OSError:
        return []
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def read_new() -> list[dict]:
    """Events appended since the last check (offset in kv)."""
    try:
        size = EVENTS.stat().st_size
    except OSError:
        return []
    offset = int(store.kv_get("cmdlog_offset") or 0)
    if size < offset:
        offset = 0
    if size == offset:
        return []
    with open(EVENTS, "rb") as f:
        f.seek(offset)
        data = f.read(64_000)
    cut = data.rfind(b"\n")
    if cut < 0:
        return []
    store.kv_set("cmdlog_offset", str(offset + cut + 1))
    out = []
    for ln in data[: cut + 1].decode("utf-8", "replace").splitlines():
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


RC_HINT = {1: "it reported an error", 2: "wrong usage or arguments", 126: "not executable (permissions)",
           127: "command not found", 137: "killed (often out of memory)", 139: "crashed (segfault)",
           143: "terminated"}


def screen_locked() -> bool:
    try:
        out = subprocess.run(["loginctl", "show-session", "auto", "-p", "LockedHint"], capture_output=True,
                             text=True, timeout=3).stdout
        return "LockedHint=yes" in out
    except (OSError, subprocess.SubprocessError):
        return False


def announce(e: dict) -> None:
    cmd = " ".join(str(e.get("cmd") or "a command").split())
    short = cmd if len(cmd) <= 60 else cmd[:57] + "…"
    rc, dur = int(e.get("rc", 0)), _human(int(e.get("secs", 0)))
    where = Path(str(e.get("cwd") or "")).name
    phone = config.CMD_ALERT_PHONE == "always" or (config.CMD_ALERT_PHONE == "away" and screen_locked())
    if rc == 0:
        notify.notify(f"✔ Done in {dur}", f"{short}" + (f"  (in {where})" if where else ""), level="info",
                      source="cmdalerts", telegram=phone)
    else:
        hint = RC_HINT.get(rc, "")
        notify.notify(f"✘ Failed after {dur}", f"{short}\nexit {rc}" + (f": {hint}" if hint else "")
                      + (f"  (in {where})" if where else ""), level="warning", source="cmdalerts", telegram=phone)


def check() -> int:
    """Called by the process_watch worker every tick: announce finished long commands."""
    if not config.CMD_ALERTS:
        return 0
    events = read_new()
    for e in events:
        if time.time() - float(e.get("t") or time.time()) < 3600:  # never replay old ones after a pause
            announce(e)
    return len(events)
