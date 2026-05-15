---
estimated_steps: 1
estimated_files: 4
skills_used: []
---

# T01: Added an index-first raw markdown lexical retrieval module with explicit missing/stale index status contracts and bounded evidence query responses.

## Inputs

- None specified.

## Expected Output

- `src/scrape_planner/raw_retrieval.py`
- `src/scrape_planner/__init__.py`
- `tests/test_raw_retrieval.py`
- `tests/test_raw_retrieval_integration.py`

## Verification

python3 -m pytest -q tests/test_raw_retrieval.py && python3 -m pytest -q tests/test_raw_retrieval_integration.py
