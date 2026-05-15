---
estimated_steps: 51
estimated_files: 4
skills_used: []
---

# T01: Implement raw retrieval index + query module and artifact contract

---
estimated_steps: 8
estimated_files: 4
skills_used:
  - tdd
  - verify-before-complete
  - design-an-interface
---
# T01: Implement raw retrieval index + query module and artifact contract

**Slice:** S02 — Index-first raw retrieval
**Milestone:** M001

## Description
Create a dedicated raw-first retrieval subsystem in `src/scrape_planner/raw_retrieval.py` that builds a deterministic lexical index from raw markdown sources and serves bounded evidence from index artifacts only. The API must expose explicit status outcomes (`ok`, `missing_index`, `stale_index`) and avoid taxonomy-bound logic.

## Failure Modes

| Dependency | On error | On timeout | On malformed response |
|------------|----------|-----------|----------------------|
| Raw source records (`scrape_manifest.json`/source markdown paths) | Return structured build error with offending source metadata and skip corrupt entry | N/A (local file IO) | Mark source as invalid in build report and continue where safe |
| Index artifact reads | Return `missing_index` or `stale_index` status with reason | N/A | Return structured parse error status, do not silently fallback to full scan |

## Load Profile

- **Shared resources**: filesystem reads/writes for index artifacts
- **Per-operation cost**: build is O(total chunks/tokens); query is bounded by postings lookup + top-K ranking
- **10x breakpoint**: artifact size and postings fanout; mitigated via bounded candidate aggregation and top-K truncation

## Negative Tests

- **Malformed inputs**: empty query, missing source_id/path/url fields, unreadable markdown file
- **Error paths**: missing index artifact, mismatched index fingerprint vs source ledger hash
- **Boundary conditions**: `max_results=0/1`, oversized query terms, snippet truncation threshold

## Steps

1. Add `src/scrape_planner/raw_retrieval.py` with typed dataclasses/dicts for source records, chunk rows, index manifest, query request/response.
2. Implement index builder that ingests raw markdown records (source-id/url/path/hash aware), chunks text deterministically, tokenizes lexically, and persists JSON/JSONL artifacts.
3. Implement query path that loads index artifacts, computes candidate scores from postings, bounds candidates/results/snippet lengths, and emits evidence rows with required metadata.
4. Implement explicit status contract for `missing_index` and `stale_index` (based on source fingerprint/version mismatch) without fallback full-file scans.
5. Add/adjust lightweight wiring in existing planner package exports or script helper so future slices can call build/query directly.

## Must-Haves

- [ ] Query logic is index-first and does not depend on `DEFAULT_TOPIC_PATTERNS` or similar hardcoded taxonomy.
- [ ] Evidence rows include `source_id`, `url`, `path`, `chunk_id`, `score`, `snippet` plus bound flags in response metadata.

## Verification

- `python3 -m pytest -q tests/test_raw_retrieval.py`
- `python3 -m pytest -q tests/test_raw_retrieval_integration.py -k "missing_index or stale_index or bounded"`

## Observability Impact

- Signals added/changed: index manifest version/fingerprint and query truncation flags
- How a future agent inspects this: read retrieval artifacts under run output + failing test output
- Failure state exposed: explicit status and reason instead of silent scan fallback

## Inputs

- `src/scrape_planner/wiki_planner.py` — existing scan/taxonomy retrieval behavior to avoid
- `scripts/zvec_index_run.py` — reference for index artifact style only
- `src/scrape_planner/run_persistence.py` — JSON/JSONL persistence helpers

## Expected Output

- `src/scrape_planner/raw_retrieval.py` — new index-first retrieval subsystem
- `src/scrape_planner/__init__.py` — optional exports/wiring for new module
- `tests/test_raw_retrieval.py` — unit tests for index/query bounds and schema
- `tests/test_raw_retrieval_integration.py` — integration tests for status contracts and bounded query path

## Inputs

- `src/scrape_planner/wiki_planner.py`
- `scripts/zvec_index_run.py`
- `src/scrape_planner/run_persistence.py`

## Expected Output

- `src/scrape_planner/raw_retrieval.py`
- `src/scrape_planner/__init__.py`
- `tests/test_raw_retrieval.py`
- `tests/test_raw_retrieval_integration.py`

## Verification

python3 -m pytest -q tests/test_raw_retrieval.py && python3 -m pytest -q tests/test_raw_retrieval_integration.py

## Observability Impact

Introduces explicit retrieval status/fingerprint/truncation diagnostics in index artifacts and query responses.
