#!/bin/bash
# Install teamc-stick on this Pi: sudo bash tools/install-stick.sh
# Copies it to /usr/local/sbin (owned by root, so it cannot be edited without sudo) and lets the
# user who ran this use "sudo teamc-stick ..." without a password. Undo:
#   sudo rm /usr/local/sbin/teamc-stick /etc/sudoers.d/teamc-stick
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run it with sudo"; exit 1; }
user=${SUDO_USER:?run it with sudo from the transceiver user}
here=$(cd "$(dirname "$0")" && pwd)

install -o root -g root -m 0755 "$here/teamc-stick" /usr/local/sbin/teamc-stick
rule=$(mktemp)
echo "$user ALL=(root) NOPASSWD: /usr/local/sbin/teamc-stick" > "$rule"
visudo -cf "$rule" > /dev/null
install -o root -g root -m 0440 "$rule" /etc/sudoers.d/teamc-stick
rm -f "$rule"
echo "installed: sudo teamc-stick mount | umount | status (no password for $user)"
