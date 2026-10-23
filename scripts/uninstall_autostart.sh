#!/usr/bin/env bash
# Remove what scripts/install_autostart.sh installed (no sudo). Your data/ folder is kept.
set -u
if [ -f "$HOME/.config/systemd/user/jarvis-workers.service" ]; then
  systemctl --user disable --now jarvis-workers.service 2>/dev/null
  rm -f "$HOME/.config/systemd/user/jarvis-workers.service"
  systemctl --user daemon-reload
  echo "workers: removed"
fi
if [ -f "$HOME/.config/autostart/jarvis.desktop" ]; then
  rm -f "$HOME/.config/autostart/jarvis.desktop"
  echo "voice autostart: removed (a running session keeps going until you quit it)"
fi
