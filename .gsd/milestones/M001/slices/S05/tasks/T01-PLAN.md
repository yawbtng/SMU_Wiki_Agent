---
estimated_steps: 1
estimated_files: 3
skills_used: []
---

# T01: Implemented deterministic PDF intake classification plus page-preserving chunk contracts with stable chunk IDs and quarantine/source row schemas.

## Inputs

- None specified.

## Expected Output

- `src/scrape_planner/pdf_ingest.py`
- `src/scrape_planner/pdf_contracts.py`
- `tests/test_pdf_ingest.py`

## Verification

python3 -m pytest tests/test_pdf_ingest.py -q
