#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${DOCKER_SMOKE_BASE_URL:-http://127.0.0.1:8000}"

echo "==> Docker smoke against ${BASE_URL}"

curl -fsS "${BASE_URL}/api/health" | python3 -c "
import json, sys
p = json.load(sys.stdin)
assert p.get('status') == 'ok', p
print('health ok:', p.get('data_root', ''))
"

curl -fsS "${BASE_URL}/api/sites" | python3 -c "
import json, sys
p = json.load(sys.stdin)
assert 'sites' in p
print('sites:', len(p['sites']))
"

code="$(curl -s -o /dev/null -w '%{http_code}' "${BASE_URL}/")"
if [[ "$code" != "200" && "$code" != "304" ]]; then
  echo "ERROR: frontend root returned HTTP ${code}" >&2
  exit 1
fi
echo "frontend root HTTP ${code}"

echo "OK: docker smoke passed"
