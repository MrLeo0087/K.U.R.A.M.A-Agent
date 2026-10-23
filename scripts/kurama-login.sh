#!/usr/bin/env bash
# Login autostart: background workers (Telegram, reminders, alerts) + the KURAMA live wallpaper (starts the API).
cd "$(dirname "$0")/.."
mkdir -p data/logs
pgrep -f "m jarvis[.]workers" >/dev/null || nohup venv/bin/python -m jarvis.workers >> data/logs/workers.out 2>&1 &
exec scripts/kurama-wallpaper.sh
