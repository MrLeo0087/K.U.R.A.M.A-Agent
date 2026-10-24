#!/usr/bin/env bash
# Login launcher, copied to ~/.local/bin/kurama-autostart by scripts/install_wallpaper_autostart.sh. It lives on
# the home drive so it runs even before the project drive is mounted, then starts KURAMA as soon as it is.
DIR="@KURAMA_DIR@"
for _ in $(seq 1 600); do
  [[ -x "$DIR/scripts/kurama-login.sh" ]] && exec "$DIR/scripts/kurama-login.sh"
  sleep 0.5
done
echo "KURAMA: $DIR is not mounted (add it to /etc/fstab to mount it at boot)" >&2
