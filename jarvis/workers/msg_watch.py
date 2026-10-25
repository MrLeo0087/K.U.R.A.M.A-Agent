"""Message watcher (worker "msg_watch"): saves new WhatsApp Web / Facebook / Instagram / email notifications.

Runs `dbus-monitor` (read-only) on the session bus filtered to org.freedesktop.Notifications.Notify; a reader thread
parses each call (app, summary, body) and jarvis.core.inbox keeps only the four message kinds. The tick (30 s)
restarts the monitor if it died, prunes old messages and writes a heartbeat. ~3 MB, no polling of the browser.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time

from jarvis.core import inbox, store
from jarvis.workers.base import Worker

_FILTER = "interface='org.freedesktop.Notifications',member='Notify'"
_STR = re.compile(r'^\s*string "(.*)"\s*$', re.S)


def parse_block(lines: list[str]) -> tuple[str, str, str] | None:
    """dbus-monitor lines of one Notify call -> (app_name, summary, body). Strings may span several lines."""
    strings, cur = [], None
    for ln in lines[1:]:
        if cur is not None:
            cur.append(ln)
            if ln.rstrip().endswith('"'):
                strings.append("\n".join(cur).rstrip()[:-1])
                cur = None
            continue
        st = ln.strip()
        if st.startswith("array") or st.startswith("dict entry"):
            break  # actions/hints follow the 4 strings we need
        if st.startswith('string "'):
            if st.endswith('"') and len(st) > len('string "'):
                strings.append(st[len('string "'):-1])
            else:
                cur = [st[len('string "'):]]
    if len(strings) < 4:
        return None
    app, _icon, summary, body = strings[:4]
    return app, summary, body


class MsgWatch(Worker):
    name = "msg_watch"
    interval_s = 30.0

    def available(self) -> str | None:
        return None if shutil.which("dbus-monitor") else "dbus-monitor missing (sudo apt install dbus-x11)"

    def setup(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.saved = 0
        self._start()

    def _start(self) -> None:
        self.proc = subprocess.Popen(["dbus-monitor", "--session", _FILTER], stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, text=True, bufsize=1)
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
        self.log.info("listening for message notifications (pid %d)", self.proc.pid)

    def _handle(self, block: list[str]) -> None:
        if not block or "member=Notify" not in block[0]:
            return
        parsed = parse_block(block)
        if not parsed:
            return
        hit = inbox.classify(*parsed)
        if hit and inbox.add(*hit):
            self.saved += 1
            self.log.info("new %s message", hit[0])

    def _read(self, proc: subprocess.Popen) -> None:
        block: list[str] = []
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.rstrip("\n")
            if line.startswith(("method call", "signal", "method return", "error")):
                try:
                    self._handle(block)
                except Exception as e:  # noqa: BLE001 - one odd notification must not stop the watcher
                    self.log.warning("couldn't parse a notification: %s", e)
                block = [line]
            elif block:
                block.append(line)
                if line.strip().startswith("int32") and "member=Notify" in block[0]:
                    try:  # expire_timeout is Notify's last argument: the call is complete, save it now
                        self._handle(block)
                    except Exception as e:  # noqa: BLE001
                        self.log.warning("couldn't parse a notification: %s", e)
                    block = []
        try:
            self._handle(block)
        except Exception:  # noqa: BLE001
            pass

    def tick(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            self.log.warning("dbus-monitor stopped; restarting")
            self._start()
        inbox.prune()
        store.kv_set("msg_watch_alive", str(time.time()))

    def teardown(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def info(self) -> dict:
        return {"saved": self.saved}
