#!/usr/bin/env bash
set -euo pipefail

site_root=""
site_url=""
prompt=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --site-root) site_root="$2"; shift 2 ;;
    --site-url) site_url="$2"; shift 2 ;;
    --prompt) prompt="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$site_root" ]]; then
  echo "--site-root is required" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
PYTHON="${ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="${PYTHON_BIN:-python3}"
fi

export PYTHONPATH="$ROOT"
export SCRAPE_PLANNER_DATA_ROOT="${SCRAPE_PLANNER_DATA_ROOT:-$ROOT/data}"

report_dir="$site_root/jobs/reports"
mkdir -p "$report_dir"
report_path="$report_dir/site-discovery-latest.json"

write_status() {
  local status="$1"
  local note="${2:-}"
  "$PYTHON" - <<'PY' "$report_path" "$status" "$note" "$site_root" "$prompt"
import json, sys
from datetime import datetime, timezone
path, status, note, site_root, prompt = sys.argv[1:6]
payload = {
    "status": status,
    "job_status": status,
    "skill": "site-discovery",
    "site_root": site_root,
    "prompt": prompt,
    "note": note,
    "updated_at": datetime.now(timezone.utc).isoformat(),
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2)
PY
}

write_status running "starting discovery"

if [[ -z "$site_url" ]]; then
  site_url="$("$PYTHON" - <<'PY' "$site_root"
import json, sys
from pathlib import Path
from urllib.parse import urlparse
site_root = Path(sys.argv[1])
for candidate in (site_root / "discovery_summary.json",):
    if candidate.exists():
        data = json.loads(candidate.read_text(encoding="utf-8"))
        url = str(data.get("site_url") or "").strip()
        if url:
            print(url)
            raise SystemExit(0)
host = site_root.name
print(f"https://{host}")
PY
)"
fi

set +e
result="$("$PYTHON" - <<'PY' "$site_url"
import json, sys
from urllib.parse import urlparse
from src.scrape_planner.scrape.sitemap_discovery import discover_site_urls, normalize_site_url

site_url = normalize_site_url(sys.argv[1])
result = discover_site_urls(site_url, timeout=30)
site_id = urlparse(site_url).netloc
rows = [item.to_dict() for item in result.urls]
selected = sum(1 for item in result.urls if item.selected and not item.excluded_reason)
print(json.dumps({
    "site_id": site_id,
    "site_url": site_url,
    "rows": rows,
    "selected_count": selected,
    "discovered_total": len(result.urls),
    "sitemap_sources": result.sitemap_sources,
    "notes": result.notes,
}))
PY
)"
code=$?
set -e

if [[ $code -ne 0 ]]; then
  write_status failed "discovery command failed"
  exit "$code"
fi

"$PYTHON" - <<'PY' "$site_root" "$result"
import json, sys
from pathlib import Path
from src.scrape_planner.core.storage import write_json
from src.scrape_planner.sources.source_registry import utc_now_iso

site_root = Path(sys.argv[1])
payload = json.loads(sys.argv[2])
rows = payload["rows"]
write_json(site_root / "discovered_urls.json", rows)
summary = {
    "site_id": payload["site_id"],
    "site_url": payload["site_url"],
    "discovered_total": payload["discovered_total"],
    "eligible_total": payload["selected_count"],
    "rejected_total": payload["discovered_total"] - payload["selected_count"],
    "sitemap_sources": payload["sitemap_sources"],
    "notes": payload["notes"],
    "generated_at": utc_now_iso(),
}
write_json(site_root / "discovery_summary.json", summary)
print(json.dumps(summary))
PY

write_status completed "discovery finished"
