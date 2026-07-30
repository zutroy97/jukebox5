#!/bin/bash
#
# Ensures the standard set of jukebox0 tmux sessions exist, then attaches
# to one of them. Safe to run repeatedly: each session is created once
# (detached) and reused -- rerunning never spawns duplicates.
#
# Usage: jukebox-tmux.sh [root|jukebox|shell|logs|mqtt]
#   (default: jukebox)
#
# Sessions:
#   root     sudo -i                                   -- root shell
#   jukebox  venv activated, cwd src/                   -- run main.py manually
#   shell    plain shell, cwd repo root                 -- general use
#   logs     journalctl -u jukebox -f                    -- live service log
#   mqtt     mosquitto_sub -t 'shairport-sync/#' -v       -- MQTT traffic

set -euo pipefail

PROJECT_DIR="/home/simonbs/jukebox5"
VENV_DIR="$PROJECT_DIR/venv"

ensure_session() {
    local name="$1" dir="$2" cmd="$3"
    if ! tmux has-session -t "$name" 2>/dev/null; then
        tmux new-session -d -s "$name" -c "$dir"
        if [ -n "$cmd" ]; then
            tmux send-keys -t "$name" "$cmd" C-m
        fi
    fi
}

ensure_session root "$PROJECT_DIR" "sudo -i"
ensure_session jukebox "$PROJECT_DIR/src" "source \"$VENV_DIR/bin/activate\""
ensure_session shell "$PROJECT_DIR" ""
ensure_session logs "$PROJECT_DIR" "journalctl -u jukebox -f"
ensure_session mqtt "$PROJECT_DIR" "mosquitto_sub -h localhost -t 'shairport-sync/#' -v"

target="${1:-jukebox}"
case "$target" in
    root|jukebox|shell|logs|mqtt) ;;
    *)
        echo "Unknown session '$target'. Choose one of: root jukebox shell logs mqtt" >&2
        exit 1
        ;;
esac

# Not an interactive terminal (e.g. invoked from a script or at boot) --
# just make sure the sessions exist and report how to reach them.
if [ ! -t 0 ] || [ ! -t 1 ]; then
    echo "Sessions ready: root jukebox shell logs mqtt"
    echo "Attach with: tmux attach -t $target"
    exit 0
fi

if [ -n "${TMUX:-}" ]; then
    tmux switch-client -t "$target"
else
    tmux attach -t "$target"
fi
