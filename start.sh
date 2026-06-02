#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/resolve-data-root.sh
source "$ROOT/scripts/lib/resolve-data-root.sh"
# shellcheck source=scripts/lib/webapp-runtime.sh
source "$ROOT/scripts/lib/webapp-runtime.sh"

LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "ERROR: missing virtualenv at $ROOT/.venv — run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi

if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  echo "ERROR: missing frontend deps — run: cd frontend && npm install" >&2
  exit 1
fi

DATA_ROOT="$(resolve_data_root "$ROOT")"
webapp_write_env_file "$LOG_DIR/webapp.env" "$DATA_ROOT"
export SCRAPE_PLANNER_DATA_ROOT="$DATA_ROOT"

USE_TMUX="${WEBAPP_USE_TMUX:-1}"
if [[ "$USE_TMUX" == "1" ]] && webapp_tmux_available; then
  webapp_start_via_tmux "$ROOT"
else
  if [[ "$USE_TMUX" == "1" ]]; then
    echo "tmux not found; falling back to nohup (set WEBAPP_USE_TMUX=0 to silence this warning)"
  fi
  webapp_start_via_nohup "$ROOT"
fi

if ! webapp_verify_health "$ROOT" "$DATA_ROOT"; then
  echo "Start completed with errors. Inspect logs under $LOG_DIR and attach tmux with: tmux attach -t $WEBAPP_TMUX_SESSION" >&2
  exit 1
fi

echo "App is up."
echo "  UI:       $WEBAPP_FRONTEND_URL"
echo "  API:      $WEBAPP_BACKEND_URL"
echo "  Data:     $DATA_ROOT"
if webapp_tmux_has_session; then
  echo "  Tmux:     tmux attach -t $WEBAPP_TMUX_SESSION"
fi
echo "Use ./status.sh to inspect processes and ./stop.sh to stop."
