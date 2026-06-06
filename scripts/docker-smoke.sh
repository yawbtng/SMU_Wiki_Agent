#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${DOCKER_SMOKE_BASE_URL:-http://127.0.0.1:8000}"
RUN_E2E="${DOCKER_SMOKE_E2E:-0}"
SMOKE_SITE_ID="${DOCKER_SMOKE_SITE_ID:-}"

echo "==> Docker smoke against ${BASE_URL}"

curl -fsS "${BASE_URL}/api/health" | python3 -c "
import json, sys
p = json.load(sys.stdin)
assert p.get('status') == 'ok', p
print('health ok:', p.get('data_root', ''))
"

curl -fsS "${BASE_URL}/api/sites" | python3 -c "
import json, os, sys
p = json.load(sys.stdin)
sites = p.get('sites', [])
assert 'sites' in p
require_sites = os.environ.get('DOCKER_SMOKE_REQUIRE_SITES', '1') == '1'
if require_sites:
    assert sites, 'expected at least one seeded workspace; run scripts/bootstrap-data.sh or restart Docker'
print('sites:', len(sites))
"

curl -fsS "${BASE_URL}/api/operator/skills" | python3 -c "
import json, sys
p = json.load(sys.stdin)
skills = {item.get('id') for item in p.get('skills', [])}
required = {'site-discovery', 'site-url-curation', 'llm-wiki-noninteractive'}
missing = sorted(required - skills)
assert not missing, missing
print('operator skills:', ', '.join(sorted(required)))
"

if [[ "$RUN_E2E" == "1" ]]; then
  echo "==> Docker e2e smoke"
  if [[ -z "$SMOKE_SITE_ID" ]]; then
    echo "ERROR: DOCKER_SMOKE_E2E=1 requires DOCKER_SMOKE_SITE_ID for an existing mounted workspace" >&2
    exit 2
  fi
  curl -fsS "${BASE_URL}/api/sites/${SMOKE_SITE_ID}/jobs/site-discovery" | python3 -c "
import json, sys
p = json.load(sys.stdin)
assert p.get('skill') == 'site-discovery', p
assert 'report' in p, p
print('job status endpoint ok:', p.get('skill'))
"
fi

code="$(curl -s -o /dev/null -w '%{http_code}' "${BASE_URL}/")"
if [[ "$code" != "200" && "$code" != "304" ]]; then
  echo "ERROR: frontend root returned HTTP ${code}" >&2
  exit 1
fi
echo "frontend root HTTP ${code}"

echo "OK: docker smoke passed"
