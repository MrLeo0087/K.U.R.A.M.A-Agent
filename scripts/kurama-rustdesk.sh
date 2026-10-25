#!/bin/sh
# KURAMA RustDesk helper. Runs as root (RustDesk only lets root set the password/options).
# Install root-owned so it can't be edited:  sudo install -o root -g root -m 755 scripts/kurama-rustdesk.sh /usr/local/sbin/kurama-rustdesk
# and allow only this file without a sudo password:  leo ALL=(root) NOPASSWD: /usr/local/sbin/kurama-rustdesk
# Usage: kurama-rustdesk on <password>   (unattended, password-only access)
#        kurama-rustdesk off             (replace the password with a random unknown one = nobody can connect)
set -e
RD=/usr/bin/rustdesk
case "$1" in
  on)
    echo "$2" | grep -Eq '^[a-z0-9]{8,32}$' || { echo "bad password" >&2; exit 2; }
    $RD --option approve-mode password >/dev/null 2>&1 || true
    $RD --option verification-method use-permanent-password >/dev/null 2>&1 || true
    $RD --password "$2"
    ;;
  off)
    $RD --password "$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    ;;
  *)
    echo "usage: kurama-rustdesk on <password> | off" >&2
    exit 2
    ;;
esac
