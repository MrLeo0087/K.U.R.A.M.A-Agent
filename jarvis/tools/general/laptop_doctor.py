"""laptop_doctor: why is my laptop slow? Real measurements -> problems and fixes; free RAM (idle Jupyter kernels),
what's on a port, stop a process (safe; stopping anything asks first). Replaces resource_status (alias kept)."""
from __future__ import annotations

from typing import Literal

from jarvis.core import doctor, safety
from jarvis.core.registry import alias, tool


@tool(group="system", safety="safe",
      description="Laptop doctor: why it's slow (RAM/swap per app, CPU hogs, heat, full disks, updates), free RAM by "
                  "stopping idle Jupyter kernels, what's using a port, stop a process (asks first), KURAMA's own health.")
def laptop_doctor(action: Literal["check", "free_ram", "port", "stop", "kurama"] = "check", target: str = "") -> str:
    """Laptop doctor.

    Args:
        action: check = diagnose; free_ram = stop idle Jupyter kernels; port = what is listening (on `target` port,
            or all); stop = stop the process `target` (PID or name) or what is on port `target`; kurama = KURAMA's
            own memory and workers.
        target: A port number, PID or process name, depending on the action.
    """
    if action == "kurama":
        from jarvis.tools.general.resource_status import resource_status
        return resource_status()
    if action == "check":
        return doctor.text(doctor.check())
    if action == "free_ram":
        ks = doctor.idle_kernels()
        if not ks:
            return "No idle Jupyter kernels to stop. " + doctor.check().findings[0]
        mb = sum(k[1] for k in ks)
        if not safety.ask(f"Stop {len(ks)} idle Jupyter kernel(s) to free about {mb:.0f} MB? Their notebook "
                          f"variables are lost (the notebooks stay)."):
            return "The user said no, so nothing was stopped."
        return f"Stopped {', '.join(doctor.stop([k[0] for k in ks]))}; about {mb:.0f} MB freed."
    port = int(target) if target.strip().isdigit() and len(target.strip()) <= 5 and action == "port" else None
    if action == "port":
        rows = doctor.listeners(port)
        if not rows:
            return f"Nothing is listening on port {port}." if port else "Nothing is listening on any port."
        return "\n".join(f"port {pt}: {name} (PID {pid})" if pid else f"port {pt}: (another user's process)"
                         for pt, pid, name in rows[:20])
    # stop
    t = target.strip()
    if not t:
        return "error: which process (PID, name) or port should I stop?"
    procs = doctor.find(t)
    if not procs and t.isdigit():  # a port
        procs = [doctor.psutil.Process(pid) for _, pid, _ in doctor.listeners(int(t)) if pid]
    if not procs:
        return f"No running process matches {t!r}."
    names = ", ".join(f"{doctor.app_name(p)} (PID {p.pid})" for p in procs[:5])
    if not safety.ask(f"Stop {names}{' and more' if len(procs) > 5 else ''}? Unsaved work in it is lost."):
        return "The user said no, so it keeps running."
    return "Stopped " + ", ".join(doctor.stop([p.pid for p in procs])) + "."


alias("resource_status", "laptop_doctor", action="kurama")
