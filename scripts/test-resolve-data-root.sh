#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/resolve-data-root.sh
source "$ROOT/scripts/lib/resolve-data-root.sh"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

empty="$tmp/empty-data"
project="$tmp/webapp"
sibling="$tmp/sibling"
mkdir -p "$empty/sites" "$project" "$sibling/data/sites/demo.edu"

export SCRAPE_PLANNER_DATA_ROOT="$empty"
resolved="$(resolve_data_root "$project")"
[[ "$resolved" == "$sibling/data" ]] || { echo "expected sibling populated data root, got $resolved"; exit 1; }

mkdir -p "$project/data/sites/local.edu"
unset SCRAPE_PLANNER_DATA_ROOT
resolved="$(resolve_data_root "$project")"
[[ "$resolved" == "$project/data" ]] || { echo "expected local populated data root, got $resolved"; exit 1; }

count="$(resolve_data_root_site_count "$project")"
[[ "$count" == "1" ]] || { echo "expected one local site, got $count"; exit 1; }

echo "resolve-data-root.sh: OK"
