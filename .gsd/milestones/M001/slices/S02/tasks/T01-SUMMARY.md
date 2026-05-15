---
id: T01
parent: S02
milestone: M001
key_files:
  - src/scrape_planner/raw_retrieval.py
  - src/scrape_planner/__init__.py
  - tests/test_raw_retrieval.py
  - tests/test_raw_retrieval_integration.py
key_decisions:
  - (none)
duration: 
verification_result: mixed
completed_at: 2026-05-15T20:39:09.780Z
blocker_discovered: false
---

# T01: Added an index-first raw markdown lexical retrieval module with explicit missing/stale index status contracts and bounded evidence query responses.

**Added an index-first raw markdown lexical retrieval module with explicit missing/stale index status contracts and bounded evidence query responses.**

## What Happened

Implemented `src/scrape_planner/raw_retrieval.py` with typed dataclasses for source records, chunks, manifest, query request/evidence/response, plus deterministic chunking/tokenization and JSON/JSONL artifact persistence (`raw_index_manifest.json`, `raw_postings.json`, `raw_chunks.jsonl`, `raw_index_build_report.json`). The query path now reads only index artifacts, returns explicit `missing_index` and `stale_index` statuses (fingerprint mismatch), and never falls back to raw corpus scans. Added bounded candidate/result/snippet behavior and truncation flags in response metadata. Wired package-level exports in `src/scrape_planner/__init__.py` for future slices to call build/query directly. Added unit/integration tests in `tests/test_raw_retrieval.py` and `tests/test_raw_retrieval_integration.py` covering schema/metadata expectations, bounds, missing index, stale index, and bounded query behavior.

## Verification

Ran targeted pytest verification for the new module and required integration statuses using `PYTHONPATH=src uv run pytest -q tests/test_raw_retrieval.py` and `PYTHONPATH=src uv run pytest -q tests/test_raw_retrieval_integration.py -k "missing_index or stale_index or bounded"`; both passed.

## Verification Evidence

| # | Command | Exit Code | Verdict | Duration |
|---|---------|-----------|---------|----------|
| 1 | `python3 -m pytest -q tests/test_raw_retrieval.py` | 1 | ❌ fail (pytest not installed in system python) | 36ms |
| 2 | `uv run pytest -q tests/test_raw_retrieval.py` | 2 | ❌ fail (missing PYTHONPATH=src import path) | 618ms |
| 3 | `PYTHONPATH=src uv run pytest -q tests/test_raw_retrieval.py` | 0 | ✅ pass | 165ms |
| 4 | `PYTHONPATH=src uv run pytest -q tests/test_raw_retrieval_integration.py -k "missing_index or stale_index or bounded"` | 0 | ✅ pass | 164ms |

## Deviations

Used `uv run pytest` with `PYTHONPATH=src` because system `python3 -m pytest` was unavailable in this environment and package import path was not preconfigured.

## Known Issues

`query_raw_index` currently maps malformed artifact JSON to `missing_index` with reason `index_artifacts_malformed` instead of introducing a separate parse-error status; this preserves explicit non-fallback behavior but may be refined later if a distinct status is required.

## Files Created/Modified

- `src/scrape_planner/raw_retrieval.py`
- `src/scrape_planner/__init__.py`
- `tests/test_raw_retrieval.py`
- `tests/test_raw_retrieval_integration.py`
