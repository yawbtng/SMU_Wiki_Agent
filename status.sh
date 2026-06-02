#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/resolve-data-root.sh
source "$ROOT/scripts/lib/resolve-data-root.sh"
# shellcheck source=scripts/lib/webapp-runtime.sh
source "$ROOT/scripts/lib/webapp-runtime.sh"

LOG_DIR="$ROOT/logs"
BACKEND_PID_FILE="$LOG_DIR/webapp-${WEBAPP_BACKEND_PORT}.pid"
FRONTEND_PID_FILE="$LOG_DIR/frontend-${WEBAPP_FRONTEND_PORT}.pid"
ENV_FILE="$LOG_DIR/webapp.env"

print_service_status() {
  local label="$1"
  local port="$2"
  local pid_file="$3"
  local pid listener_pid cmd health="down"

  pid="$(webapp_read_pid_file "$pid_file" || true)"
  listener_pid="$(webapp_listener_pid "$port" || true)"

  echo "[$label]"
  echo "  port: $port"
  echo "  pid_file: $pid_file"
  if [[ -n "$pid" ]]; then
    echo "  pid_file_value: $pid"
  else
    echo "  pid_file_value: (none)"
  fi

  if webapp_is_pid_running "$pid"; then
    cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    echo "  status: running (PID $pid)"
    [[ -n "$cmd" ]] && echo "  command: $cmd"
  elif [[ -n "$listener_pid" ]]; then
    cmd="$(ps -p "$listener_pid" -o command= 2>/dev/null || true)"
    echo "  status: running (port listener PID $listener_pid)"
    [[ -n "$cmd" ]] && echo "  command: $cmd"
  else
    echo "  status: stopped"
  fi

  if webapp_is_port_listening "$port"; then
    health="listening"
  fi
  if [[ "$label" == "backend" ]] && webapp_curl_ok "$WEBAPP_BACKEND_URL/api/health" 2; then
    health="healthy"
  elif [[ "$label" == "frontend" ]] && webapp_curl_ok "$WEBAPP_FRONTEND_URL/" 2; then
    health="healthy"
  fi
  echo "  health: $health"
  echo
}

DATA_ROOT="$(resolve_data_root "$ROOT")"
SITE_COUNT="$(resolve_data_root_site_count "$ROOT")"

echo "[runtime]"
echo "  data_root: $DATA_ROOT"
echo "  sites: $SITE_COUNT"
if [[ -f "$ENV_FILE" ]]; then
  echo "  env_file: $ENV_FILE"
else
  echo "  env_file: (missing — run ./start.sh)"
fi
if webapp_tmux_has_session; then
  echo "  tmux: $WEBAPP_TMUX_SESSION (attach with: tmux attach -t $WEBAPP_TMUX_SESSION)"
else
  echo "  tmux: not running"
fi
echo

print_service_status "backend" "$WEBAPP_BACKEND_PORT" "$BACKEND_PID_FILE"
print_service_status "frontend" "$WEBAPP_FRONTEND_PORT" "$FRONTEND_PID_FILE"

if webapp_is_port_listening "$WEBAPP_BACKEND_PORT" && webapp_curl_ok "$WEBAPP_BACKEND_URL/api/sites" 3; then
  curl -fsS --max-time 5 "$WEBAPP_BACKEND_URL/api/sites" | python3 -c "import json,sys; payload=json.load(sys.stdin); print('API sites:', ', '.join(site['id'] for site in payload.get('sites',[])) or '(none)')"
fi
