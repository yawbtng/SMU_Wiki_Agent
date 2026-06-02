#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/resolve-data-root.sh
source "$ROOT/scripts/lib/resolve-data-root.sh"
DATA_ROOT="${SCRAPE_PLANNER_DATA_ROOT:-$(resolve_data_root "$ROOT")}"
PYTHON="${ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${PYTHON:-python3}"
fi

cd "$ROOT"
export PYTHONPATH="$ROOT"

echo "==> py_compile webapp modules"
PYTHONPATH="$ROOT" "$PYTHON" -m py_compile \
  src/scrape_planner/webapp/api.py \
  src/scrape_planner/webapp/deps.py \
  src/scrape_planner/webapp/schemas.py \
  src/scrape_planner/webapp/approved_urls.py \
  src/scrape_planner/webapp/embeddings.py \
  src/scrape_planner/webapp/routes.py \
  src/scrape_planner/webapp/jobs.py \
  src/scrape_planner/app/job_launcher.py \
  src/scrape_planner/app/operator_skills.py \
  src/scrape_planner/app/pi_agent.py

echo "==> pytest webapp API"
PYTHONPATH="$ROOT" SCRAPE_PLANNER_DATA_ROOT="$DATA_ROOT" "$PYTHON" -m pytest tests/test_webapp_api.py -q

echo "==> frontend build"
cd frontend
npm run build

echo "OK: webapp verification passed"
