# S02: S02

**Goal:** Deliver an index-first raw markdown retrieval path that builds a precomputed lexical index and serves bounded evidence from that index (not full-corpus scans) with explicit stale/missing index status behavior.
**Demo:** A query over fixture raw markdown uses an index-first path and returns bounded evidence without scanning every raw file.

## Must-Haves

- Complete the planned slice outcomes.

## Verification

- Run the task and slice verification checks for this slice.

## Tasks

- [x] **T01: Added an index-first raw markdown lexical retrieval module with explicit missing/stale index status contracts and bounded evidence query responses.**
  - Files: `src/scrape_planner/raw_retrieval.py`, `src/scrape_planner/__init__.py`, `tests/test_raw_retrieval.py`, `tests/test_raw_retrieval_integration.py`
  - Verify: python3 -m pytest -q tests/test_raw_retrieval.py && python3 -m pytest -q tests/test_raw_retrieval_integration.py

- [ ] **T02: Add fixture-level proof command coverage for index-first bounded retrieval**
  - Files: `scripts/raw_retrieval_proof.py`, `tests/test_raw_retrieval_integration.py`, `README.md`
  - Verify: python3 -m pytest -q tests/test_raw_retrieval_integration.py -k "index_first or bounded or read" && python3 scripts/raw_retrieval_proof.py --help

## Files Likely Touched

- src/scrape_planner/raw_retrieval.py
- src/scrape_planner/__init__.py
- tests/test_raw_retrieval.py
- tests/test_raw_retrieval_integration.py
- scripts/raw_retrieval_proof.py
- README.md
