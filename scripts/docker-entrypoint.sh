#!/usr/bin/env bash
set -euo pipefail

mkdir -p "${SCRAPE_PLANNER_DATA_ROOT:-/app/data}/sites"
mkdir -p "${PI_CODING_AGENT_DIR:-${SCRAPE_PLANNER_DATA_ROOT:-/app/data}/pi-agent}"
mkdir -p "${PI_CODING_AGENT_SESSION_DIR:-${SCRAPE_PLANNER_DATA_ROOT:-/app/data}/pi-agent/sessions}"

exec "$@"
