#!/usr/bin/env bash
# Start Jarvis: background workers + the voice session with the "Hey Jarvis" wake word.
#   scripts/jarvis-start.sh               workers (background) + voice (foreground)
#   scripts/jarvis-start.sh --no-workers  voice only (workers run as the systemd --user service)
# Logs: data/logs/voice.log and data/logs/workers.out
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR" || exit 1
PY="$DIR/venv/bin/python"
LOGS="$DIR/data/logs"
umask 077
mkdir -p "$LOGS" && chmod 700 "$DIR/data" 2>/dev/null

[ -x "$PY" ] || { echo "venv missing: python3.12 -m venv venv && venv/bin/pip install -r requirements.txt" >&2; exit 1; }

WORKERS=1
for a in "$@"; do [ "$a" = "--no-workers" ] && WORKERS=0; done

# Wait (max 60 s) for the sound server after login, or the mic/player can't open.
for _ in $(seq 1 30); do
  pactl info >/dev/null 2>&1 && break
  sleep 2
done

WPID=""
if [ "$WORKERS" = 1 ]; then
  if systemctl --user is-active --quiet jarvis-workers.service 2>/dev/null || pgrep -f "python -m jarvis.workers" >/dev/null; then
    echo "workers already running"
  else
    nohup "$PY" -u -m jarvis.workers >>"$LOGS/workers.out" 2>&1 &
    WPID=$!
    echo "workers started (pid $WPID, log data/logs/workers.out)"
  fi
fi
cleanup() { [ -n "$WPID" ] && kill "$WPID" 2>/dev/null; }
trap cleanup EXIT INT TERM

if [ -t 0 ]; then  # terminal: show the conversation and keep a log
  "$PY" -u -m jarvis --voice --wake 2>&1 | tee -a "$LOGS/voice.log"
else              # desktop autostart: no terminal
  "$PY" -u -m jarvis --voice --wake >>"$LOGS/voice.log" 2>&1
fi
