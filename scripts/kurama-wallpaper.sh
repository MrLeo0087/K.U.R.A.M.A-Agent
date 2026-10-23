#!/usr/bin/env bash
# Show the KURAMA holographic UI as a "live wallpaper": a borderless full-screen app window that stays
# BEHIND all other windows, on every workspace, and out of the taskbar/alt-tab.
#   scripts/kurama-wallpaper.sh          start (also starts the API server if it isn't running)
#   scripts/kurama-wallpaper.sh stop     close the wallpaper window (server keeps running)
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${JARVIS_API_PORT:-8000}"
URL="http://127.0.0.1:${PORT}/?lowpower=1"
PROFILE="${HOME}/.cache/kurama-wallpaper-profile"   # separate browser profile = its own small process
TITLE="KURAMA"

if [[ "${1:-}" == "stop" ]]; then
  pkill -f -- "--user-data-dir=${PROFILE}" 2>/dev/null && echo "wallpaper closed" || echo "not running"
  exit 0
fi

for b in wmctrl xdotool; do command -v "$b" >/dev/null || { echo "need $b: sudo apt install $b"; exit 1; }; done
BROWSER="$(command -v brave-browser || command -v google-chrome || command -v chromium || true)"
[[ -n "$BROWSER" ]] || { echo "need a Chromium-based browser (brave-browser / google-chrome / chromium)"; exit 1; }

# 1) API server (skip if already up)
if ! curl -fs "http://127.0.0.1:${PORT}/api/v1/health" >/dev/null 2>&1; then
  mkdir -p data/logs
  nohup venv/bin/python -m jarvis.server --port "$PORT" >> data/logs/server.log 2>&1 &
  for _ in $(seq 1 30); do curl -fs "http://127.0.0.1:${PORT}/api/v1/health" >/dev/null 2>&1 && break; sleep 1; done
fi

# 2) app-mode window (no tabs/URL bar); low-power flags keep it light
nohup "$BROWSER" --app="$URL" --user-data-dir="$PROFILE" --no-first-run --disable-extensions \
  --disable-background-networking --renderer-process-limit=1 --class="$TITLE" >/dev/null 2>&1 &

# 3) wait for the window, then pin it behind everything, on all workspaces, full screen, no taskbar
for _ in $(seq 1 40); do
  WID="$(wmctrl -lx | awk -v c="$TITLE" 'tolower($3) ~ tolower(c) {print $1; exit}')"
  [[ -n "$WID" ]] && break; sleep 0.5
done
[[ -n "${WID:-}" ]] || { echo "window not found (it may still open; run again to pin it)"; exit 1; }
wmctrl -i -r "$WID" -b add,below,sticky,skip_taskbar,skip_pager
wmctrl -i -r "$WID" -b add,fullscreen
echo "KURAMA wallpaper is running (stop: scripts/kurama-wallpaper.sh stop)"
