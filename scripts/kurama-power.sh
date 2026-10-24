#!/usr/bin/env bash
# KURAMA power switch: off = every KURAMA process stops (wallpaper window, API, workers, voice, gesture control)
# and your normal wallpaper comes back: 0 RAM, 0 CPU. on = start it all again.
#   scripts/kurama-power.sh on | off | toggle | status
# Also: the power button in the UI, Super+K, and the "KURAMA" app icon (installed by install_wallpaper_autostart.sh).
# While off, a flag in ~/.local/share/kurama keeps it off after a reboot too, until you turn it on.
set -u
cd "$(dirname "$0")/.."
FLAG="$HOME/.local/share/kurama/off"
PROCS="venv/bin/python -m jarvis[.]|kurama_[w]allpaper[.]py|gesture_[r]unner[.]py|jarvis-[s]tart[.]sh"
note() { command -v notify-send >/dev/null && notify-send -a KURAMA -i "$HOME/.local/share/kurama/kurama.svg" "KURAMA" "$1" 2>/dev/null; echo "$1"; }
running() { pgrep -f -- "$PROCS" >/dev/null; }

off() {
  mkdir -p "$(dirname "$FLAG")" && touch "$FLAG"
  scripts/kurama-wallpaper.sh stop >/dev/null  # closes the window and puts the real wallpaper back
  pkill -TERM -f -- "$PROCS" 2>/dev/null
  for _ in $(seq 1 20); do running || break; sleep 0.25; done
  pkill -KILL -f -- "$PROCS" 2>/dev/null  # anything that ignored the polite stop
  note "Off. Press Super+K (or click the KURAMA app) to turn it back on."
}

on() {
  rm -f "$FLAG"
  note "Starting…"
  nohup scripts/kurama-login.sh >/dev/null 2>&1 &
}

case "${1:-toggle}" in
  on) on ;;
  off) off ;;
  toggle) if running; then off; else on; fi ;;
  status) if running; then echo on; else echo off; fi ;;
  *) echo "usage: $0 on|off|toggle|status" >&2; exit 2 ;;
esac
