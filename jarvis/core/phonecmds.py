"""The Telegram commands on the laptop too (0 tokens): /camera, /video, /where, /here, /history, /guard, /track,
/mute, /unmute, /notifications, /control... Typed in KURAMA's chat they act here: a camera photo or clip goes to the
workspace instead of the phone. The secret ones stay phone-only (the RustDesk password needs the Telegram PIN)."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from jarvis.core import config

PHONE_ONLY = {"control": "The remote-desktop password is only given on Telegram after your PIN: send /control there.",
              "changepass": "A new remote password is only given on Telegram: send /changepass there.",
              "lock": "/lock blocks risky Telegram commands (if your phone is lost): send it on Telegram. "
                      "To lock this screen use /lockscreen.",
              "unlock": "/unlock <pin> unlocks Telegram after /lock: send it on Telegram."}


def _to_workspace(p: Path | None, sub: str) -> Path | None:
    if not p:
        return None
    d = config.OUTPUTS_DIR / sub
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{time.strftime('%Y%m%d-%H%M%S')}-camera{p.suffix}"
    shutil.copy(p, out)
    return out


def run(cmd: str, arg: str = "") -> str:
    """One command's answer on the laptop."""
    from jarvis.core import guard
    words = arg.split()
    if cmd in PHONE_ONLY:
        return PHONE_ONLY[cmd]
    if cmd == "camera":
        out = _to_workspace(guard.photo(), "images")
        return "Took a photo with the laptop camera. It's in the workspace." if out else guard._no_camera_msg()
    if cmd == "video":
        secs = int(words[0]) if words and words[0].isdigit() else 5
        out = _to_workspace(guard.clip(secs), "videos")
        return f"Recorded {secs} s with the laptop camera. It's in the workspace." if out else guard._no_camera_msg()
    if cmd == "where":
        return guard.where()
    if cmd == "here":
        from jarvis.core import geolocate
        return geolocate.label_here(arg.strip() or "home")
    if cmd == "history":
        from jarvis.core import locationlog
        dev = "phone" if words and words[0].lower().startswith("phone") else "laptop"
        hrs = next((int(w) for w in words if w.isdigit()), 24)
        return locationlog.summary(dev, hrs)
    if cmd == "guard":
        a = (words[0].lower() if words else "")
        return guard.arm(a == "on") if a in ("on", "off") else guard.status()
    if cmd == "track":
        from jarvis.core import locationlog
        return locationlog.set_lost("laptop", (words[0].lower() if words else "on") != "off")
    if cmd in ("mute", "unmute", "notifications"):
        from jarvis.tools.general.mute_alerts import mute_alerts
        if cmd == "notifications":
            return mute_alerts("status")
        mins = next((float(w) for w in words if w.replace(".", "", 1).isdigit()), 0)
        what = next((w.lower() for w in words if not w.replace(".", "", 1).isdigit()), "")
        what = {"ram": "resource", "memory": "resource", "cpu": "resource"}.get(what, what)
        return mute_alerts("off" if cmd == "unmute" else "on", what or ("all" if cmd == "unmute" else "last"), mins)
    if cmd == "clearchat":
        from jarvis.core import reset
        return reset.clear_chat()
    if cmd == "clear":  # chat + every reminder/alarm/timer: only with 'yes'
        if arg.strip().lower() not in ("yes", "y", "ok", "sure"):
            return "This clears the chat AND all reminders, alarms and timers. Send '/clear yes' to do it."
        from jarvis.core import reset
        return reset.clear_recent()
    if cmd == "reset":
        return "A full reset wipes everything KURAMA knows. Do it from Settings, or send /reset on Telegram."
    if cmd == "stop":
        return "On the laptop, press the ■ button (or say 'stop') to stop an answer; 'stop the music' stops music."
    if cmd == "clipnow":
        from jarvis.core import phone
        return phone.clipboard_text()
    return f"I don't know /{cmd}."
