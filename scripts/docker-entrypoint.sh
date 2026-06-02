#!/usr/bin/env bash
set -euo pipefail

mkdir -p "${SCRAPE_PLANNER_DATA_ROOT:-/app/data}/sites"

exec "$@"
