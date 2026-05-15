# S02: Index-first raw retrieval

**Goal:** Deliver an index-first raw markdown retrieval path that builds a precomputed lexical index and serves bounded evidence from that index (not full-corpus scans) with explicit stale/missing index status behavior.
**Demo:** A query over fixture raw markdown uses an index-first path and returns bounded evidence without scanning every raw file.

## Must-Haves

- Raw retrieval index can be built from raw source records into durable artifacts under run outputs.
- Query path consumes prebuilt index artifacts and returns bounded evidence fields (`source_id`, `url`, `path`, `chunk_id`, `score`, `snippet`) with bound flags.
- Query behavior does not rely on hardcoded university taxonomy and does not read every raw markdown file per query.
- Missing/stale index conditions are surfaced via explicit status contract and covered by tests.
- Automated tests prove index-first bounded behavior (including query-time read-boundedness assertion).

## Proof Level

- This slice proves: integration

## Integration Closure

Completes M001 retrieval boundary by introducing a standalone raw retrieval subsystem plus tests/CLI wiring that downstream stale-dependency and tracer slices can consume directly.

## Verification

- Adds inspectable retrieval index/query artifacts and status surfaces so future agents can diagnose retrieval failures (missing index, stale index, bound truncation) without opaque runtime behavior.

## Tasks

- [ ] **T01: Implement raw retrieval index + query module and artifact contract** `est:2.5h`
  ---
  estimated_steps: 8
  estimated_files: 4
  skills_used:
    - tdd
    - verify-before-complete
    - design-an-interface
  ---
  - Files: `src/scrape_planner/raw_retrieval.py`, `src/scrape_planner/__init__.py`, `tests/test_raw_retrieval.py`, `tests/test_raw_retrieval_integration.py`
  - Verify: python3 -m pytest -q tests/test_raw_retrieval.py && python3 -m pytest -q tests/test_raw_retrieval_integration.py

- [ ] **T02: Add fixture-level proof command coverage for index-first bounded retrieval** `est:1.5h`
  ---
  estimated_steps: 6
  estimated_files: 3
  skills_used:
    - tdd
    - verify-before-complete
    - write-docs
  ---
  - Files: `scripts/raw_retrieval_proof.py`, `tests/test_raw_retrieval_integration.py`, `README.md`
  - Verify: python3 -m pytest -q tests/test_raw_retrieval_integration.py -k "index_first or bounded or read" && python3 scripts/raw_retrieval_proof.py --help

## Files Likely Touched

- src/scrape_planner/raw_retrieval.py
- src/scrape_planner/__init__.py
- tests/test_raw_retrieval.py
- tests/test_raw_retrieval_integration.py
- scripts/raw_retrieval_proof.py
- README.md
