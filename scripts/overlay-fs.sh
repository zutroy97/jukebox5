#!/bin/bash
#
# Switches between a read-only root filesystem (overlayfs, protects the SD
# card) and a normal read-write root, using raspi-config's built-in
# overlay-root mechanism (see docs/deployment.md). Both directions require
# a reboot to take effect -- this script only stages the change unless you
# pass --reboot, since jumping straight to a reboot would drop your SSH
# session and stop the jukebox service without warning.
#
# Usage:
#   overlay-fs.sh status          # show current + configured-for-boot state
#   overlay-fs.sh ro [--reboot]   # switch to read-only (protects SD card)
#   overlay-fs.sh rw [--reboot]   # switch to read-write (for maintenance)

set -euo pipefail

# raspi-config's own convention: 0 = read-only/overlay active, 1 = read-write.
state_label() {
    if [ "$1" -eq 0 ]; then echo "read-only (overlay active)"; else echo "read-write"; fi
}

status() {
    local now conf
    now=$(raspi-config nonint get_overlay_now)
    conf=$(raspi-config nonint get_overlay_conf)
    echo "Currently running:        $(state_label "$now")"
    echo "Configured for next boot: $(state_label "$conf")"
}

usage() {
    echo "Usage: $(basename "$0") status|ro|rw [--reboot]" >&2
    exit 1
}

[ $# -ge 1 ] || usage
cmd="$1"
shift
reboot_now=0
if [ "${1:-}" = "--reboot" ]; then
    reboot_now=1
fi

case "$cmd" in
    status)
        status
        ;;
    ro)
        sudo raspi-config nonint enable_overlayfs
        echo "Staged: read-only on next boot."
        ;;
    rw)
        sudo raspi-config nonint disable_overlayfs
        echo "Staged: read-write on next boot."
        ;;
    *)
        usage
        ;;
esac

if [ "$cmd" = "ro" ] || [ "$cmd" = "rw" ]; then
    if [ "$reboot_now" -eq 1 ]; then
        echo "Rebooting now..."
        sudo reboot
    else
        echo "Not rebooted -- run 'sudo reboot' when ready, or rerun with --reboot."
    fi
fi
