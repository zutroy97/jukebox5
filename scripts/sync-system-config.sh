#!/bin/bash
#
# Syncs system config files that can't be symlinked into the repo (a FAT32
# boot partition has no symlink support at all; /etc/shairport-sync.conf
# would need a symlink target the shairport-sync service user can't
# traverse into under /home) between their live system paths and tracked
# snapshots in config/.
#
# Usage:
#   sync-system-config.sh pull   # live system -> repo (after editing live)
#   sync-system-config.sh push   # repo -> live system (after git pull)
#
# Neither direction restarts shairport-sync or reboots -- do that
# separately once you've reviewed what changed.

set -euo pipefail

PROJECT_DIR="/home/simonbs/jukebox5"

# repo-relative path : live system path
FILES=(
    "config/shairport-sync.conf:/etc/shairport-sync.conf"
    "config/boot-firmware-config.txt:/boot/firmware/config.txt"
)

usage() {
    echo "Usage: $(basename "$0") pull|push" >&2
    exit 1
}

[ $# -eq 1 ] || usage

case "$1" in
    pull)
        for pair in "${FILES[@]}"; do
            repo_path="${PROJECT_DIR}/${pair%%:*}"
            live_path="${pair##*:}"
            cp "$live_path" "$repo_path"
            echo "pulled $live_path -> $repo_path"
        done
        echo "Review with: git -C $PROJECT_DIR diff -- config/"
        ;;
    push)
        for pair in "${FILES[@]}"; do
            repo_path="${PROJECT_DIR}/${pair%%:*}"
            live_path="${pair##*:}"
            sudo cp "$repo_path" "$live_path"
            echo "pushed $repo_path -> $live_path"
        done
        ;;
    *)
        usage
        ;;
esac
