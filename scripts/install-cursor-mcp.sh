#!/usr/bin/env bash
# Merge the query-only LLM Wiki MCP server into Cursor's ~/.cursor/mcp.json.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/resolve-data-root.sh
source "$ROOT/scripts/lib/resolve-data-root.sh"

SITE_ID="${LLM_WIKI_SITE_ID:-www.smu.edu}"
DATA_ROOT="$(resolve_data_root "$ROOT")"
SITE_ROOT="$DATA_ROOT/sites/$SITE_ID"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
PYTHON="$(cd "$(dirname "$PYTHON")" && pwd -P)/$(basename "$PYTHON")"
CURSOR_MCP="${CURSOR_MCP_CONFIG:-$HOME/.cursor/mcp.json}"
SERVER_NAME="${LLM_WIKI_MCP_NAME:-llm-wiki-${SITE_ID}}"

if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: missing venv python at $PYTHON" >&2
  exit 1
fi
if [[ ! -d "$SITE_ROOT" ]]; then
  echo "ERROR: site root not found: $SITE_ROOT" >&2
  exit 1
fi

mkdir -p "$(dirname "$CURSOR_MCP")"
export ROOT SITE_ROOT PYTHON SERVER_NAME CURSOR_MCP
"$PYTHON" <<'PY'
import json
import os
from pathlib import Path

cursor_mcp = Path(os.environ["CURSOR_MCP"])
root = Path(os.environ["ROOT"]).resolve()
site_root = Path(os.environ["SITE_ROOT"]).resolve()
python = Path(os.environ["PYTHON"]).resolve()
server_name = os.environ["SERVER_NAME"]

entry = {
    "command": str(python),
    "args": [
        "-m",
        "mcp_servers.llm_wiki_mcp",
        "--site-root",
        str(site_root),
    ],
    "cwd": str(root),
    "env": {
        "PYTHONPATH": str(root),
        "LLM_WIKI_SITE_ROOT": str(site_root),
    },
}

payload: dict = {"mcpServers": {}}
if cursor_mcp.exists():
    loaded = json.loads(cursor_mcp.read_text(encoding="utf-8"))
    if isinstance(loaded, dict):
        servers = loaded.get("mcpServers")
        if isinstance(servers, dict):
            payload["mcpServers"] = dict(servers)

payload["mcpServers"][server_name] = entry
cursor_mcp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(f"Updated {cursor_mcp}")
print(f"  server: {server_name}")
print(f"  site:   {site_root}")
print("")
print("In Cursor: Settings → MCP → enable", server_name, "then reload the window.")
PY
