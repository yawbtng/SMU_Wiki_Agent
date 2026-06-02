#!/usr/bin/env bash
set -euo pipefail

site_root=""
prompt=""
autosave="true"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --site-root) site_root="$2"; shift 2 ;;
    --prompt) prompt="$2"; shift 2 ;;
    --autosave) autosave="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$site_root" || -z "$prompt" ]]; then
  echo "--site-root and --prompt are required" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
PYTHON="${ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${PYTHON:-python3}"
fi

export PYTHONPATH="$ROOT"
report_dir="$site_root/jobs/reports"
mkdir -p "$report_dir"
report_path="$report_dir/site-url-curation-latest.json"

"$PYTHON" - <<'PY' "$site_root" "$prompt" "$autosave" "$report_path"
import json
import sys
from pathlib import Path

from src.scrape_planner.webapp.approved_urls import approval_chat_payload
from src.scrape_planner.webapp.schemas import ApprovedUrlsChatRequest

site_root = Path(sys.argv[1])
prompt = sys.argv[2]
autosave = sys.argv[3].lower() in {"1", "true", "yes", "on"}
report_path = Path(sys.argv[4])
site_id = site_root.name

result = approval_chat_payload(
    site_id,
    ApprovedUrlsChatRequest(message=prompt, autosave=autosave, limit=500),
)
payload = {
    "status": "completed",
    "job_status": "completed",
    "skill": "site-url-curation",
    "site_root": str(site_root),
    "prompt": prompt,
    "intent": result.get("intent"),
    "saved": result.get("saved"),
    "approved_count": result.get("count"),
    "report": {
        "assistant_message": result.get("assistant_message"),
        "path": result.get("path"),
    },
}
report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
print(json.dumps({"ok": True, "count": result.get("count")}))
PY
