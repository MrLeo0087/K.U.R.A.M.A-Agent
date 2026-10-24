"""One "status" for everything that's going on (0 tokens): training runs (epoch x/N, accuracy, loss trend, ETA),
background jobs, downloads, a lecture being recorded, page watches, the guard, what's next, the laptop itself and
the latest alerts. Telegram /status, "status", "what's going on", "any update" all answer with this.
"""
from __future__ import annotations

import time
from datetime import datetime

import psutil

from jarvis.core import store


def _ago(t: float) -> str:
    d = time.time() - t
    return f"{int(d // 60)} min ago" if d < 3600 else f"{d / 3600:.1f} h ago"


def training_lines() -> list[str]:
    from jarvis.core import training
    out = []
    for w in store.watches_list(("active",)):
        if w["kind"] not in training.KINDS:
            continue
        st = w["state"]
        line = training.describe(w)
        if w["kind"] == "colab" and st.get("last_msg"):
            line += f" (last update {_ago(st['last_msg'])})"
        out.append(line)
    for w in store.watches_list(("done", "failed", "stopped"), 10):
        if w["kind"] in training.KINDS and time.time() - float(w.get("finished") or 0) < 6 * 3600:
            out.append(f"#{w['id']} {w['label']}: {w['status']} {_ago(w['finished'])}, {w.get('result') or ''}".rstrip(", "))
    return out[:6]


def status_all() -> str:
    parts: list[str] = []
    if tl := training_lines():
        parts.append("Training:\n" + "\n".join(tl))
    jobs = store.jobs_list(5, ("queued", "running"))
    if jobs:
        parts.append("Jobs: " + "; ".join(f"#{j['id']} {j['title'][:40]} ({j['status']}"
                                          + (f", {j['progress']}" if j.get("progress") else "") + ")" for j in jobs))
    dls = [w for w in store.watches_list(("active",)) if w["kind"] == "dl"]
    if dls:
        from jarvis.core import automation
        parts.append("Downloads: " + automation.downloads_text().replace("\n", "; "))
    from jarvis.core import guard, lecture
    if lecture.recording():
        st = lecture.state()
        parts.append(f"Recording lecture '{st['title']}' for {int((time.time() - st['start']) / 60)} min.")
    webs = [w for w in store.watches_list(("active",)) if w["kind"] == "web"]
    if webs:
        changed = [w for w in webs if w["state"].get("last_change", 0) > time.time() - 86400]
        parts.append(f"Watching {len(webs)} page(s)" + (f"; changed today: {', '.join(w['label'] for w in changed)}"
                                                        if changed else ""))
    if guard.armed():
        parts.append("Laptop guard: ON.")
    nxt = []
    try:
        from jarvis.core import study
        if study.classes():
            nxt.append(study.show("next"))
    except Exception:
        pass
    rows = store._exec("SELECT text, kind, next_run FROM schedules WHERE enabled=1 AND next_run > ? "
                       "ORDER BY next_run LIMIT 1", (time.time(),))
    if rows:
        r = rows[0]
        nxt.append(f"Next {r['kind']}: {r['text'][:60]} at {datetime.fromtimestamp(r['next_run']).strftime('%a %H:%M')}.")
    if nxt:
        parts.append(" ".join(nxt))
    vm = psutil.virtual_memory()
    bat = psutil.sensors_battery()
    laptop = f"Laptop: RAM {vm.percent:.0f}%, CPU {psutil.cpu_percent(0.3):.0f}%"
    if bat is not None:
        laptop += f", battery {bat.percent:.0f}%{' charging' if bat.power_plugged else ''}"
    parts.append(laptop + ".")
    alerts = [a for a in store.alerts_recent(5) if time.time() - float(a.get("ts") or 0) < 3 * 3600]
    if alerts:
        parts.append("Recent alerts: " + "; ".join(f"{a['title']} ({_ago(a['ts'])})" for a in alerts[:3]))
    if len(parts) == 1:
        parts.insert(0, "All quiet: nothing is training, downloading or running in the background.")
    return "\n\n".join(parts)
