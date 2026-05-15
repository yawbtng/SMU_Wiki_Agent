# S05: S05

**Goal:** Prove internal/operator PDF ingestion into Zvec with page-number-preserving chunks, citation-bearing query results, and explicit quarantine artifacts for unsupported PDFs.
**Demo:** A born-digital PDF is chunked with page numbers, indexed/queryable through Zvec, and scanned/encrypted/malformed/low-text PDFs are quarantined with reasons.

## Must-Haves

- Complete the planned slice outcomes.

## Verification

- Run the task and slice verification checks for this slice.

## Tasks

- [x] **T01: Implemented deterministic PDF intake classification plus page-preserving chunk contracts with stable chunk IDs and quarantine/source row schemas.**
  - Files: `src/scrape_planner/pdf_ingest.py`, `src/scrape_planner/pdf_contracts.py`, `tests/test_pdf_ingest.py`
  - Verify: python3 -m pytest tests/test_pdf_ingest.py -q

- [x] **T02: Wire PDF chunks into Zvec and produce citation-bearing query proof artifacts**
  - Files: `scripts/zvec_pdf_proof.py`, `src/scrape_planner/pdf_zvec.py`, `mcp_servers/smu_zvec_mcp.py`, `tests/test_pdf_zvec_proof.py`
  - Verify: python3 -m pytest tests/test_pdf_zvec_proof.py -q

## Files Likely Touched

- src/scrape_planner/pdf_ingest.py
- src/scrape_planner/pdf_contracts.py
- tests/test_pdf_ingest.py
- scripts/zvec_pdf_proof.py
- src/scrape_planner/pdf_zvec.py
- mcp_servers/smu_zvec_mcp.py
- tests/test_pdf_zvec_proof.py
