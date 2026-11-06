"""Claude Code hook for KURAMA's Claude Code watch (jarvis/core/claudewatch.py). Claude Code runs this at its key
moments (a prompt, each tool, a permission question, the end) ONLY while the watch is on: the command in Claude
Code's settings checks KURAMA's flag file first. Standard library only; it never blocks Claude Code for long and
never fails it: any problem = exit quietly.

A permission question waits here for the owner's answer from Telegram ("/claude yes|no"): allow / deny goes back to
Claude Code; no answer in time = Claude Code shows its own dialog on the laptop as usual.
"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1/claude"


def call(path, body=None, timeout=4.0):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def main():
    import os
    if os.environ.get("KURAMA_NO_WATCH"):  # KURAMA's own '/usage' check: not a task
        return
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return
    try:
        got = call("/event", data)
    except Exception:  # KURAMA not running: Claude Code goes on as if nothing happened
        return
    if got.get("stop"):  # '/claude stop': Claude Code stops here (it shows the reason)
        print(json.dumps({"continue": False, "stopReason": got["stop"]}))
        return
    qid, wait_s = got.get("wait"), float(got.get("wait_s") or 0)
    if not qid or data.get("hook_event_name") != "PermissionRequest":
        return
    end = time.time() + wait_s
    while time.time() < end:
        time.sleep(2)
        try:
            ans = call(f"/decision?id={qid}").get("answer")
        except Exception:
            return
        if ans in ("allow", "deny"):
            decision = {"behavior": ans}
            if ans == "deny":
                decision["message"] = "The owner said no (from KURAMA / Telegram)."
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}}))
            return


if __name__ == "__main__":
    main()
