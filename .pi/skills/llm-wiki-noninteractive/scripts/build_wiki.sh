#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: build_wiki.sh --site-root <path> [--mode rebuild|resume] [--query <smoke query>] [--skip-smoke] [--skip-pi]

LLM Wiki v2 pipeline (non-interactive):
  1. Pi llm-wiki-v2 compile (semantic pages from raw_sources)
  2. Python lint
  3. Python hybrid index rebuild
  4. optional smoke query
USAGE
}

site_root=""
mode="rebuild"
query="What graduate catalog programs are available?"
skip_smoke=0
skip_pi=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --site-root) site_root="${2:-}"; shift 2 ;;
    --mode) mode="${2:-}"; shift 2 ;;
    --query) query="${2:-}"; shift 2 ;;
    --skip-smoke) skip_smoke=1; shift ;;
    --skip-pi) skip_pi=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$site_root" ]] || { echo "Missing --site-root" >&2; exit 2; }
[[ "$mode" == "rebuild" || "$mode" == "resume" ]] || { echo "--mode must be rebuild or resume" >&2; exit 2; }

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root"
[[ -d "$site_root" ]] || { echo "Site root missing: $site_root" >&2; exit 1; }
[[ -f .venv/bin/activate ]] && source .venv/bin/activate
python_bin="${PYTHON:-python3}"
command -v "$python_bin" >/dev/null || { echo "Python not found" >&2; exit 1; }

echo "[llm-wiki] site_root=$site_root mode=$mode"
"$python_bin" -m py_compile src/scrape_planner/wiki/llm_wiki_builder.py src/scrape_planner/wiki/llm_wiki_index.py

if [[ "$skip_pi" -eq 0 ]]; then
  echo "[llm-wiki] pi compile (llm-wiki-v2)"
  bash .pi/skills/llm-wiki-v2/scripts/generate_wiki.sh --site-root "$site_root" --mode "$mode"
else
  echo "[llm-wiki] skipping pi (--skip-pi)"
fi

echo "[llm-wiki] lint"
"$python_bin" -m src.scrape_planner.wiki.llm_wiki_builder --site-root "$site_root" --lint

echo "[llm-wiki] rebuild index"
"$python_bin" -m src.scrape_planner.wiki.llm_wiki_index --site-root "$site_root"

if [[ "$skip_smoke" -eq 0 ]]; then
  echo "[llm-wiki] smoke: $query"
  "$python_bin" -m src.scrape_planner.wiki.llm_wiki_index --site-root "$site_root" --query "$query"
fi

echo "[llm-wiki] done"
