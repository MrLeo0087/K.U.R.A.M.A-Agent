""""Start my day" / "done for today" (plan 11-09 phase 3, 0 tokens).

done(): saves what you work with (the browser tabs the KURAMA extension sees, the VS Code project, the song
playing), snapshots the project (code time machine), stops the music, sends a short report to Telegram, then asks
once: close Brave + VS Code and sleep the laptop?
start(): opens the saved tabs, the project in VS Code and the music again, and says what is on today.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time

from jarvis.core import store

KEY = "day_session"
MAX_TABS = 15


def _open(argv: list[str]) -> bool:
    if not shutil.which(argv[0]):
        return False
    try:
        subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return False


def capture() -> dict:
    """What you work with right now."""
    from jarvis.core import browsertab, music, timemachine
    tabs = [t for t in browsertab.tabs() if str(t.get("url", "")).startswith("http")][:MAX_TABS]
    if not tabs and (one := browsertab.get(max_age_s=12 * 3600)):
        tabs = [{"url": one[0], "title": one[1]}]
    try:
        proj = timemachine.vscode_folder()
    except Exception:  # noqa: BLE001
        proj = None
    song = None
    try:
        if music.running() and (cur := music.PLAYER.current()) and not cur.get("direct"):
            song = {"url": cur.get("url"), "title": cur.get("title")}
    except Exception:  # noqa: BLE001
        pass
    return {"tabs": [{"url": t["url"], "title": t.get("title", "")} for t in tabs], "project": str(proj) if proj else "",
            "song": song, "ts": time.time()}


def saved() -> dict:
    try:
        d = json.loads(store.kv_get(KEY) or "{}")
        return d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


def _report(s: dict) -> str:
    lines = [f"🌙 Done for today ({time.strftime('%a %d %b, %H:%M')})."]
    if s["project"]:
        lines.append(f"💻 Project: {s['project'].rsplit('/', 1)[-1]} (snapshot saved)")
    if s["tabs"]:
        lines.append(f"🌐 {len(s['tabs'])} tabs saved: " + ", ".join((t["title"] or t["url"])[:40] for t in s["tabs"][:5])
                     + (" …" if len(s["tabs"]) > 5 else ""))
    if s["song"]:
        lines.append(f"🎵 Music: {s['song']['title'][:60]}")
    try:
        done = [r for r in store.jobs_list(30, ("done",)) if r.get("finished") and float(r["finished"]) > time.time() - 86400]
        if done:
            lines.append(f"✅ {len(done)} jobs finished today: " + ", ".join(str(r['title'])[:40] for r in done[:4]))
    except Exception:  # noqa: BLE001
        pass
    lines.append("Say 'start my day' tomorrow to open everything again.")
    return "\n".join(lines)


def done(ask=None) -> str:
    """Save, snapshot, report; then (on yes) close Brave + VS Code and sleep. ask(prompt) -> bool."""
    s = capture()
    store.kv_set(KEY, json.dumps(s))
    if s["project"]:
        try:
            from pathlib import Path

            from jarvis.core import timemachine
            timemachine.snapshot(Path(s["project"]), reason="done for today")
        except Exception:  # noqa: BLE001
            pass
    try:
        from jarvis.core import music
        if music.running():
            music.stop()
    except Exception:  # noqa: BLE001
        pass
    report = _report(s)
    try:
        from jarvis.core import notify
        notify.telegram_send(report)
    except Exception:  # noqa: BLE001
        pass
    if ask is not None and ask("Close Brave and VS Code and sleep the laptop now?"):
        from jarvis.tools.general.close_app import close_app
        for app in ("brave", "code"):
            try:
                close_app(app)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(3)
        _open(["systemctl", "suspend"])
        return report + "\nClosing your apps and sleeping the laptop. Good night!"
    return report


def start() -> str:
    s = saved()
    if not s:
        return "Nothing saved yet: say 'done for today' at the end of the day, and tomorrow I'll open it all again."
    did = []
    urls = [t["url"] for t in s.get("tabs") or []]
    if urls:
        browser = next((b for b in ("brave-browser", "brave", "google-chrome", "chromium") if shutil.which(b)), "")
        if browser and _open([browser, *urls]) or not browser and _open(["xdg-open", urls[0]]):
            did.append(f"{len(urls)} tabs")
    if s.get("project") and _open(["code", s["project"]]):
        did.append(f"VS Code: {s['project'].rsplit('/', 1)[-1]}")
    if s.get("song") and s["song"].get("url"):
        try:
            from jarvis.core import music
            music.play_url(s["song"]["url"], label=s["song"].get("title") or "")
            did.append(f"music: {(s['song'].get('title') or '')[:50]}")
        except Exception:  # noqa: BLE001
            pass
    return f"☀️ Good morning! Opened {', '.join(did)}." if did else "☀️ Good morning! Nothing to open from last time."
