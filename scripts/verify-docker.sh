#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER_BIN="${DOCKER_BIN:-docker}"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-ultra-fast-rag-smoke}"
export WEBAPP_HOST_PORT="${WEBAPP_HOST_PORT:-18080}"
BASE_URL="${DOCKER_SMOKE_BASE_URL:-http://127.0.0.1:${WEBAPP_HOST_PORT:-8000}}"
KEEP_RUNNING="${DOCKER_VERIFY_KEEP_RUNNING:-0}"
BUILD_TIMEOUT_SECONDS="${DOCKER_VERIFY_BUILD_TIMEOUT_SECONDS:-600}"
ANONYMOUS_DOCKER_CONFIG="${DOCKER_VERIFY_ANONYMOUS_DOCKER_CONFIG:-1}"
TEMP_DOCKER_CONFIG=""

if ! command -v "$DOCKER_BIN" >/dev/null 2>&1; then
  if [[ -x /Applications/Docker.app/Contents/Resources/bin/docker ]]; then
    export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
    DOCKER_BIN="/Applications/Docker.app/Contents/Resources/bin/docker"
  else
    echo "ERROR: docker CLI not found. Set DOCKER_BIN or start Docker Desktop." >&2
    exit 127
  fi
fi

if [[ "$ANONYMOUS_DOCKER_CONFIG" == "1" && -z "${DOCKER_CONFIG:-}" ]]; then
  TEMP_DOCKER_CONFIG="$(mktemp -d)"
  printf '{}\n' >"$TEMP_DOCKER_CONFIG/config.json"
  if [[ -d "$HOME/.docker/cli-plugins" ]]; then
    ln -s "$HOME/.docker/cli-plugins" "$TEMP_DOCKER_CONFIG/cli-plugins"
  fi
  export DOCKER_CONFIG="$TEMP_DOCKER_CONFIG"
fi

compose() {
  "$DOCKER_BIN" compose --project-name "$PROJECT_NAME" "$@"
}

run_with_timeout() {
  local seconds="$1"
  local label="$2"
  shift 2
  "$@" &
  local pid=$!
  local elapsed=0
  while kill -0 "$pid" >/dev/null 2>&1; do
    if (( elapsed >= seconds )); then
      echo "ERROR: ${label} did not finish within ${seconds}s." >&2
      echo "This usually means Docker cannot resolve or pull a required base image." >&2
      kill "$pid" >/dev/null 2>&1 || true
      wait "$pid" >/dev/null 2>&1 || true
      return 124
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  wait "$pid"
}

cleanup() {
  if [[ "$KEEP_RUNNING" != "1" ]]; then
    compose down --remove-orphans >/dev/null 2>&1 || true
  fi
  if [[ -n "$TEMP_DOCKER_CONFIG" ]]; then
    rm -rf "$TEMP_DOCKER_CONFIG"
  fi
}
trap cleanup EXIT

cd "$ROOT"

echo "==> Docker version"
"$DOCKER_BIN" version

echo "==> Compose config"
compose config >/dev/null

echo "==> Build app image"
run_with_timeout "$BUILD_TIMEOUT_SECONDS" "compose build app" compose build app

echo "==> Start compose stack"
compose up -d redis app

echo "==> Wait for app health at ${BASE_URL}/api/health"
for _ in {1..60}; do
  if curl -fsS "${BASE_URL}/api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl -fsS "${BASE_URL}/api/health" >/dev/null

echo "==> Verify container health uses /app/data"
compose exec -T app sh -lc 'curl -fsS http://127.0.0.1:8000/api/health | python3 -c "import json,sys; p=json.load(sys.stdin); assert p.get(\"data_root\") == \"/app/data\", p; print(\"container data_root:\", p[\"data_root\"])"'

echo "==> Verify container runtime tools"
compose exec -T app sh -lc 'command -v python3 && command -v tmux && command -v zsh && command -v git && command -v pi'
compose exec -T app sh -lc 'python3 -m py_compile src/scrape_planner/webapp/api.py src/scrape_planner/app/pi_agent.py'
compose exec -T app sh -lc 'pi --version >/dev/null'

echo "==> HTTP smoke"
DOCKER_SMOKE_BASE_URL="$BASE_URL" ./scripts/docker-smoke.sh

if [[ "$KEEP_RUNNING" == "1" ]]; then
  echo "OK: Docker verification passed; compose stack kept running (${PROJECT_NAME})."
else
  echo "OK: Docker verification passed."
fi
