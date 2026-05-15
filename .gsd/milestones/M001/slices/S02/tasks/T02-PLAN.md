---
estimated_steps: 1
estimated_files: 3
skills_used: []
---

# T02: Add fixture-level proof command coverage for index-first bounded retrieval

## Inputs

- None specified.

## Expected Output

- `scripts/raw_retrieval_proof.py`
- `tests/test_raw_retrieval_integration.py`
- `README.md`

## Verification

python3 -m pytest -q tests/test_raw_retrieval_integration.py -k "index_first or bounded or read" && python3 scripts/raw_retrieval_proof.py --help
