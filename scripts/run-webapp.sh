#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=scripts/lib/resolve-data-root.sh
source "$ROOT/scripts/lib/resolve-data-root.sh"

if [[ -f "$ROOT/logs/webapp.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT/logs/webapp.env"
  set +a
fi

export SCRAPE_PLANNER_DATA_ROOT="${SCRAPE_PLANNER_DATA_ROOT:-$(resolve_data_root "$ROOT")}"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"

RELOAD_ARGS=()
if [[ "${WEBAPP_RELOAD:-1}" == "1" ]]; then
  RELOAD_ARGS+=(--reload --reload-dir src/scrape_planner --reload-exclude 'tests/*' --reload-exclude 'frontend/*')
fi

UVICORN_ARGS=(
  -m uvicorn src.scrape_planner.webapp.api:app
  --host "${HOST:-127.0.0.1}"
  --port "${PORT:-${WEBAPP_BACKEND_PORT:-8000}}"
)
if ((${#RELOAD_ARGS[@]} > 0)); then
  UVICORN_ARGS+=("${RELOAD_ARGS[@]}")
fi
exec "${PYTHON:-$ROOT/.venv/bin/python}" "${UVICORN_ARGS[@]}"
