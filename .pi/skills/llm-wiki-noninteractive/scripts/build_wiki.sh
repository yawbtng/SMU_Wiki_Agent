#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: build_wiki.sh --site-root <path> [--mode rebuild|resume] [--query <smoke query>] [--skip-smoke]

Runs the ultra-fast-rag LLM Wiki pipeline in non-interactive mode:
  1. syntax-check wiki builder/indexer modules
  2. build or resume wiki generation with --no-input
  3. rebuild the local wiki/raw index
  4. run an optional bounded smoke query
USAGE
}

site_root=""
mode="rebuild"
query="What graduate catalog programs are available?"
skip_smoke=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --site-root)
      site_root="${2:-}"
      shift 2
      ;;
    --mode)
      mode="${2:-}"
      shift 2
      ;;
    --query)
      query="${2:-}"
      shift 2
      ;;
    --skip-smoke)
      skip_smoke=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$site_root" ]]; then
  echo "Missing required --site-root" >&2
  usage >&2
  exit 2
fi

if [[ "$mode" != "rebuild" && "$mode" != "resume" ]]; then
  echo "--mode must be either 'rebuild' or 'resume'" >&2
  exit 2
fi

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root"

if [[ ! -d "$site_root" ]]; then
  echo "Site root does not exist: $site_root" >&2
  exit 1
fi

if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

python_bin="${PYTHON:-python3}"

if ! command -v "$python_bin" >/dev/null 2>&1; then
  echo "Python not found: $python_bin" >&2
  exit 1
fi

build_flag="--rebuild"
if [[ "$mode" == "resume" ]]; then
  build_flag="--resume"
fi

echo "[llm-wiki] repo_root=$repo_root"
echo "[llm-wiki] site_root=$site_root"
echo "[llm-wiki] mode=$mode"

echo "[llm-wiki] syntax check"
"$python_bin" -m py_compile \
  src/scrape_planner/llm_wiki_builder.py \
  src/scrape_planner/llm_wiki_index.py

echo "[llm-wiki] build wiki"
"$python_bin" -m src.scrape_planner.llm_wiki_builder \
  --site-root "$site_root" \
  --no-input \
  "$build_flag"

echo "[llm-wiki] rebuild query index"
"$python_bin" -m src.scrape_planner.llm_wiki_index \
  --site-root "$site_root"

if [[ "$skip_smoke" -eq 0 ]]; then
  echo "[llm-wiki] smoke query: $query"
  "$python_bin" -m src.scrape_planner.llm_wiki_index \
    --site-root "$site_root" \
    --query "$query"
fi

echo "[llm-wiki] done"
echo "[llm-wiki] wiki_index=$site_root/wiki/index.md"
echo "[llm-wiki] build_report=$site_root/wiki/reports/wiki-build-latest.json"
echo "[llm-wiki] query_manifest=$site_root/indexes/llm_wiki_manifest.json"
