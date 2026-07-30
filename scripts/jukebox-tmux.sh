#!/bin/bash
#
# Ensures a single tmux session with the standard set of jukebox0 windows
# exists, then attaches to it. Safe to run repeatedly: the session is
# created once and reused -- rerunning never respawns windows.
#
# Ctrl-b n / Ctrl-b p move between windows; Ctrl-b <number> jumps directly.
#
# Usage: jukebox-tmux.sh [root|jukebox|shell|logs|mqtt]
#   (default: jukebox -- selects which window is active on attach)
#
# Windows:
#   root     sudo -i                                    -- root shell
#   jukebox  venv activated, cwd src/                    -- run main.py manually
#   shell    plain shell, cwd repo root                  -- general use
#   logs     journalctl -u jukebox -f                    -- live service log
#   mqtt     mosquitto_sub -t 'shairport-sync/#' -v        -- MQTT traffic

set -euo pipefail

PROJECT_DIR="/home/simonbs/jukebox5"
VENV_DIR="$PROJECT_DIR/venv"
SESSION="jukebox0"

if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux new-session -d -s "$SESSION" -n root -c "$PROJECT_DIR"
    tmux send-keys -t "$SESSION:root" "sudo -i" C-m

    tmux new-window -t "$SESSION" -n jukebox -c "$PROJECT_DIR/src"
    tmux send-keys -t "$SESSION:jukebox" "source \"$VENV_DIR/bin/activate\"" C-m

    tmux new-window -t "$SESSION" -n shell -c "$PROJECT_DIR"

    tmux new-window -t "$SESSION" -n logs -c "$PROJECT_DIR"
    tmux send-keys -t "$SESSION:logs" "journalctl -u jukebox -f" C-m

    tmux new-window -t "$SESSION" -n mqtt -c "$PROJECT_DIR"
    tmux send-keys -t "$SESSION:mqtt" "mosquitto_sub -h localhost -t 'shairport-sync/#' -v" C-m
fi

target="${1:-jukebox}"
case "$target" in
    root|jukebox|shell|logs|mqtt) ;;
    *)
        echo "Unknown window '$target'. Choose one of: root jukebox shell logs mqtt" >&2
        exit 1
        ;;
esac
tmux select-window -t "$SESSION:$target"

# Not an interactive terminal (e.g. invoked from a script or at boot) --
# just make sure the session/windows exist and report how to reach them.
if [ ! -t 0 ] || [ ! -t 1 ]; then
    echo "Session ready: $SESSION (windows: root jukebox shell logs mqtt)"
    echo "Attach with: tmux attach -t $SESSION"
    exit 0
fi

if [ -n "${TMUX:-}" ]; then
    tmux switch-client -t "$SESSION"
else
    tmux attach -t "$SESSION"
fi
