#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/webapp-runtime.sh
source "$ROOT/scripts/lib/webapp-runtime.sh"

LOG_DIR="$ROOT/logs"
BACKEND_PID_FILE="$LOG_DIR/webapp-${WEBAPP_BACKEND_PORT}.pid"
FRONTEND_PID_FILE="$LOG_DIR/frontend-${WEBAPP_FRONTEND_PORT}.pid"

stop_pid_file() {
  local pid_file="$1"
  local label="$2"
  local pid
  pid="$(webapp_read_pid_file "$pid_file" || true)"
  if webapp_is_pid_running "$pid"; then
    kill "$pid" 2>/dev/null || true
    sleep 1
    if webapp_is_pid_running "$pid"; then
      kill -9 "$pid" 2>/dev/null || true
    fi
    echo "Stopped $label (PID $pid)"
  else
    echo "$label not running via PID file"
  fi
  rm -f "$pid_file"
}

stop_pid_file "$BACKEND_PID_FILE" "backend"
stop_pid_file "$FRONTEND_PID_FILE" "frontend"

webapp_kill_uvicorn_tree
webapp_kill_vite_tree
webapp_kill_port "$WEBAPP_BACKEND_PORT" "backend"
webapp_kill_port "$WEBAPP_FRONTEND_PORT" "frontend"

if webapp_tmux_has_session; then
  tmux send-keys -t "$WEBAPP_TMUX_SESSION:backend" C-c 2>/dev/null || true
  tmux send-keys -t "$WEBAPP_TMUX_SESSION:frontend" C-c 2>/dev/null || true
  echo "Sent stop signals to tmux session '$WEBAPP_TMUX_SESSION' (session kept for logs; kill with: tmux kill-session -t $WEBAPP_TMUX_SESSION)"
fi

echo "Done."
