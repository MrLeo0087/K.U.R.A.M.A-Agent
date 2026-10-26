#!/usr/bin/env bash
# Login autostart: background workers (Telegram, reminders, alerts) + the KURAMA live wallpaper (starts the API).
cd "$(dirname "$0")/.."
mkdir -p data/logs
# the workers run inside the server by default (one process, ~55 MB less); JARVIS_WORKERS_IN_SERVER=0 = separate
if [ "${JARVIS_WORKERS_IN_SERVER:-1}" = 0 ]; then
  pgrep -f "m jarvis[.]workers" >/dev/null || nohup venv/bin/python -m jarvis.workers >> data/logs/workers.out 2>&1 &
fi
exec scripts/kurama-wallpaper.sh
