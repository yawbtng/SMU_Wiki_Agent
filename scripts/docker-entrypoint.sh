#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${ULTRA_FAST_RAG_APP_ROOT:-/app}"
DATA_ROOT="${SCRAPE_PLANNER_DATA_ROOT:-/app/data}"

mkdir -p "${DATA_ROOT}/sites"
mkdir -p "${PI_CODING_AGENT_DIR:-${DATA_ROOT}/pi-agent}"
mkdir -p "${PI_CODING_AGENT_SESSION_DIR:-${DATA_ROOT}/pi-agent/sessions}"

DEMO_WORKSPACE_SEED="${DEMO_WORKSPACE_SEED:-${APP_ROOT}/fixtures/demo-workspace}" \
  "${APP_ROOT}/scripts/bootstrap-data.sh" "${DATA_ROOT}"

exec "$@"
