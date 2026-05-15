---
estimated_steps: 1
estimated_files: 4
skills_used: []
---

# T02: Wire PDF chunks into Zvec and produce citation-bearing query proof artifacts

## Inputs

- None specified.

## Expected Output

- `scripts/zvec_pdf_proof.py`
- `src/scrape_planner/pdf_zvec.py`
- `mcp_servers/smu_zvec_mcp.py`
- `tests/test_pdf_zvec_proof.py`

## Verification

python3 -m pytest tests/test_pdf_zvec_proof.py -q
