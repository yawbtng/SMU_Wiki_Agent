#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-$ROOT/data}"
SEED="${DEMO_WORKSPACE_SEED:-$ROOT/fixtures/demo-workspace}"

bootstrap_data_has_sites() {
  local root="${1:-}"
  [[ -d "$root/sites" ]] || return 1
  local entry
  for entry in "$root/sites"/*; do
    [[ -e "$entry" ]] || continue
    [[ -d "$entry" ]] && return 0
  done
  return 1
}

if bootstrap_data_has_sites "$TARGET"; then
  exit 0
fi

if [[ ! -d "$SEED/sites" ]]; then
  echo "ERROR: demo workspace seed is missing at $SEED/sites" >&2
  echo "Run: python3 scripts/generate-demo-workspace.py" >&2
  exit 1
fi

mkdir -p "$TARGET"
echo "Seeding demo workspace into ${TARGET}"
cp -a "${SEED}/." "${TARGET}/"
